"""RAG seed — docs/rag_seed (veya RAG_SEED_PATH) → runbook Chroma (idempotent)."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_STATE_NAME = ".seed_state.json"
_TEXT_SUFFIXES = {".md", ".txt", ".markdown"}
_PDF_SUFFIXES = {".pdf"}


def resolve_rag_seed_dir() -> Optional[Path]:
    """Kurulum köküne göre seed dizini.

    Öncelik:
    1) RAG_SEED_PATH env / settings
    2) /app/docs/rag_seed (compose mount)
    3) repo root = …/backend/app/services → parents[3]/docs/rag_seed
    """
    try:
        from app.core.config import settings
        configured = (getattr(settings, "RAG_SEED_PATH", None) or "").strip()
    except Exception:
        import os
        configured = (os.getenv("RAG_SEED_PATH") or "").strip()

    candidates: List[Path] = []
    if configured:
        candidates.append(Path(configured))
    candidates.append(Path("/app/docs/rag_seed"))
    try:
        # backend/app/services/rag_seed.py → repo root
        repo_root = Path(__file__).resolve().parents[3]
        candidates.append(repo_root / "docs" / "rag_seed")
    except Exception:
        pass
    candidates.append(Path("/dttadvance/app/docs/rag_seed"))

    for p in candidates:
        try:
            if p.is_dir():
                return p
        except Exception:
            continue
    return None


def _state_path(seed_dir: Path) -> Path:
    """Durum dosyası: chroma yanında kalıcı olsun (seed dizini :ro olabilir)."""
    try:
        from app.core.config import settings
        chroma = Path(getattr(settings, "RAG_CHROMA_PATH", "/app/chroma") or "/app/chroma")
        chroma.mkdir(parents=True, exist_ok=True)
        return chroma / "rag_seed_state.json"
    except Exception:
        return seed_dir / _STATE_NAME


def _load_state(path: Path) -> Dict[str, str]:
    try:
        from app.services.rag_store import load_seed_state
        db_state = load_seed_state()
        if db_state:
            return db_state
    except Exception as e:
        logger.debug("rag_seed DB state: %s", e)
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
    except Exception as e:
        logger.debug("rag_seed state okunamadı: %s", e)
    return {}


def _save_state(path: Path, state: Dict[str, str]) -> None:
    try:
        from app.services.rag_store import save_seed_state
        save_seed_state(state)
    except Exception as e:
        logger.debug("rag_seed DB state yazılamadı: %s", e)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as e:
        logger.warning("rag_seed state yazılamadı (%s): %s", path, e)


def _manifest_disabled_files(seed_dir: Path) -> set:
    """manifest'te `enabled:false` olan dosya adları (manifest dışı taramada da dışlanır)."""
    manifest = seed_dir / "manifest.json"
    out: set = set()
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for d in (data.get("documents") if isinstance(data, dict) else None) or []:
            if isinstance(d, dict) and d.get("enabled") is False and d.get("file"):
                out.add(str(d["file"]).strip())
    except Exception:
        pass
    return out


def _load_manifest_docs(seed_dir: Path) -> List[Dict[str, Any]]:
    manifest = seed_dir / "manifest.json"
    if not manifest.is_file():
        return []
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        docs = data.get("documents") if isinstance(data, dict) else None
        if not isinstance(docs, list):
            return []
        out = []
        for d in docs:
            if not isinstance(d, dict):
                continue
            if d.get("enabled") is False:
                continue
            title = (d.get("title") or "").strip()
            file_name = (d.get("file") or "").strip()
            if not title or not file_name:
                continue
            out.append({
                "title": title,
                "file": file_name,
                "version": str(d.get("version") or "1").strip() or "1",
            })
        return out
    except Exception as e:
        logger.warning("rag_seed manifest okunamadı: %s", e)
        return []


def _scan_dir_docs(seed_dir: Path) -> List[Dict[str, Any]]:
    docs = []
    for p in sorted(seed_dir.iterdir()):
        if not p.is_file():
            continue
        if p.name.startswith(".") or p.name in ("manifest.json", "README.md"):
            continue
        suf = p.suffix.lower()
        if suf not in _PDF_SUFFIXES and suf not in _TEXT_SUFFIXES:
            continue
        title = p.stem.strip()
        if not title:
            continue
        docs.append({"title": title, "file": p.name, "version": "1"})
    return docs


def collect_docs(seed_dir: Path) -> List[Dict[str, Any]]:
    """Manifest girdileri (öncelikli) + manifest dışı desteklenen dosyalar (Adım 8R/R1.2).

    `enabled:false` dosyaları ve manifest'te zaten geçen dosya/başlıklar tekrar eklenmez.
    Her girdi `source`: manifest|scan taşır.
    """
    docs = [dict(d, source="manifest") for d in _load_manifest_docs(seed_dir)]
    known_files = {d["file"] for d in docs} | _manifest_disabled_files(seed_dir)
    known_titles = {d["title"] for d in docs}
    for d in _scan_dir_docs(seed_dir):
        if d["file"] in known_files or d["title"] in known_titles:
            continue
        docs.append(dict(d, source="scan"))
    return docs


SHORT_PDF_BYTES = 50_000  # «kaynak dosya kısa» uyarı eşiği (örn. OCP-4.18-Monitoring 29,9 KB / 8 sayfa)


def _read_file_text(path: Path) -> str:
    suf = path.suffix.lower()
    if suf in _PDF_SUFFIXES:
        from app.services.pdf_parser import extract_text_from_pdf
        return extract_text_from_pdf(path.read_bytes()) or ""
    return path.read_text(encoding="utf-8", errors="replace")


async def seed_rag_from_directory(seed_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Seed dizinindeki dokümanları runbook'a yazar. Dönüş: özet dict."""
    root = seed_dir or resolve_rag_seed_dir()
    summary: Dict[str, Any] = {
        "seed_dir": str(root) if root else None,
        "added": [],
        "skipped": [],
        "updated": [],
        "errors": [],
        "off_manifest": [],
        "short_source": [],
        "chunks_by_title": {},
    }
    if root is None:
        logger.warning("RAG seed: dizin yok (RAG_SEED_PATH / docs/rag_seed), atlandı")
        return summary

    docs = collect_docs(root)
    if not docs:
        logger.info("RAG seed: %s boş (manifest/documents yok)", root)
        return summary

    state_file = _state_path(root)
    state = _load_state(state_file)

    from app.services.rag_service import ingest_runbook_append, ingest_runbook_pages
    from app.services.rag_store import delete_runbook_by_title

    for doc in docs:
        title = doc["title"]
        version = doc["version"]
        path = root / doc["file"]
        if not path.is_file():
            summary["errors"].append({"title": title, "error": f"dosya yok: {doc['file']}"})
            continue
        if doc.get("source") == "scan":
            summary["off_manifest"].append(title)
        try:
            if path.suffix.lower() in _PDF_SUFFIXES and path.stat().st_size < SHORT_PDF_BYTES:
                summary["short_source"].append({"title": title, "bytes": path.stat().st_size})
                logger.warning("RAG seed: kaynak dosya kısa (%s bayt) title=%r — tam kitap değil olabilir",
                               path.stat().st_size, title)
        except Exception:
            pass
        prev = state.get(title)
        if prev == version:
            # Title Chroma'da var mı diye de bak (state var ama silinmiş olabilir)
            try:
                from app.services.rag_store import list_runbook_documents
                titles = {d.get("title") for d in list_runbook_documents()}
                if title in titles:
                    summary["skipped"].append(title)
                    continue
            except Exception:
                summary["skipped"].append(title)
                continue

        try:
            pages = None
            if path.suffix.lower() in _PDF_SUFFIXES:
                from app.services.pdf_parser import extract_pages_from_pdf
                pages = extract_pages_from_pdf(path.read_bytes())
                text = "\n\n".join(t for _, t in pages)
            else:
                text = _read_file_text(path)
            if not (text or "").strip():
                summary["errors"].append({"title": title, "error": "metin boş / PDF extract başarısız"})
                continue
            if prev and prev != version:
                try:
                    delete_runbook_by_title(title)
                except Exception:
                    pass
                action = "updated"
            elif prev is None:
                # İlk kurulum veya state yok — varsa üzerine yazmamak için title varsa skip
                try:
                    from app.services.rag_store import list_runbook_documents
                    titles = {d.get("title") for d in list_runbook_documents()}
                    if title in titles and prev is None:
                        # Manuel yüklenmiş olabilir; version işaretle, yeniden embed etme
                        state[title] = version
                        _save_state(state_file, state)
                        summary["skipped"].append(title)
                        continue
                except Exception:
                    pass
                action = "added"
            else:
                action = "added"

            if pages:
                n = await ingest_runbook_pages(title=title, pages=pages)  # PDF: metadata.page korunur
            else:
                n = await ingest_runbook_append(title=title, content=text)
            if not n:
                raise RuntimeError("chunk üretilemedi / eklenmedi")
            summary["chunks_by_title"][title] = n
            state[title] = version
            # Belge bitince kalıcı state — restart'ta tüm tur bitmeden kaybolmasın
            _save_state(state_file, state)
            summary[action].append({"title": title, "chunks": n, "version": version})
            logger.info("RAG seed %s: title=%r chunks=%s version=%s", action, title, n, version)
        except Exception as e:
            logger.warning("RAG seed hata title=%r: %s", title, e)
            summary["errors"].append({"title": title, "error": str(e)})

    _save_state(state_file, state)
    logger.info(
        "RAG seed bitti: dir=%s added=%s updated=%s skipped=%s errors=%s manifest_disi=%s kisa_kaynak=%s chunks=%s",
        root,
        len(summary["added"]),
        len(summary["updated"]),
        len(summary["skipped"]),
        len(summary["errors"]),
        len(summary["off_manifest"]),
        len(summary["short_source"]),
        summary["chunks_by_title"],
    )
    return summary
