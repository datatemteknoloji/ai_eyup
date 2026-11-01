"""RAG bakım işleri (Adım 8R): `runbook.metadata.module` geri doldurma (yalnız metadata; embed YOK) + R4 saklama (retention) planı/yedek/budama.

Veri yazan tek fonksiyon `backfill_runbook_module` — varsayılan `dry_run=True`; gerçek koşuda ÖNCE dosyaya yedek
(id + önceki metadata) yazılır, tek işlemde güncellenir. Geri alma: `rollback_runbook_module` (yedek dosyasından).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


def plan_runbook_module_backfill() -> Dict[str, Any]:
    """Salt-okunur: modülü olmayan runbook satırları başlığa göre → (title, modül, satır sayısı)."""
    from app.core.database import engine
    from app.services.rag_store import module_for_title
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT metadata->>'title' AS t, count(*) FROM rag_embeddings "
            "WHERE collection='runbook' AND NOT (metadata ? 'module') GROUP BY 1 ORDER BY 2 DESC"
        )).fetchall()
    items = [{"title": r[0], "module": module_for_title(r[0] or ""), "rows": int(r[1])} for r in rows]
    return {
        "titles": items,
        "rows_total": sum(i["rows"] for i in items),
        "rows_mappable": sum(i["rows"] for i in items if i["module"]),
        "unmapped": [i for i in items if not i["module"]],
    }


def backfill_runbook_module(*, dry_run: bool = True, backup_path: Optional[str] = None) -> Dict[str, Any]:
    """Modülü olmayan runbook satırlarına `module` yazar (başlık eşlemesi). Yalnız `metadata`; embed/document dokunulmaz."""
    from app.core.database import engine
    from app.services.rag_store import module_for_title
    plan = plan_runbook_module_backfill()
    report: Dict[str, Any] = {"dry_run": dry_run, "plan": plan, "updated": 0, "backup": None}
    if dry_run or not plan["rows_mappable"]:
        return report
    if not backup_path:
        raise ValueError("backup_path zorunlu (gerçek koşu)")
    targets = {i["title"]: i["module"] for i in plan["titles"] if i["module"]}
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT id, metadata FROM rag_embeddings WHERE collection='runbook' AND NOT (metadata ? 'module') "
            "AND metadata->>'title' = ANY(CAST(:titles AS text[]))"
        ), {"titles": list(targets)}).fetchall()
        path = Path(backup_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for rid, meta in rows:
                fh.write(json.dumps({"id": rid, "metadata": meta}, ensure_ascii=False) + "\n")
        report["backup"] = {"path": str(path), "rows": len(rows)}
        n = 0
        for title, mod in targets.items():
            r = conn.execute(text(
                "UPDATE rag_embeddings SET metadata = metadata || jsonb_build_object('module', CAST(:m AS text)) "
                "WHERE collection='runbook' AND NOT (metadata ? 'module') AND metadata->>'title' = :t"
            ), {"m": mod, "t": title})
            n += r.rowcount or 0
        if n != len(rows):
            raise RuntimeError(f"güncellenen satır {n} != yedeklenen {len(rows)} — işlem geri alındı")
        report["updated"] = n
    logger.info("[RAG] runbook module backfill: %s satır güncellendi, yedek=%s", n, backup_path)
    return report


def rollback_runbook_module(backup_path: str) -> int:
    """Yedek dosyasındaki id'ler için `module` anahtarını kaldırır (önceki metadata'da yoktu)."""
    from app.core.database import engine
    ids = []
    with open(backup_path, encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if "module" not in (d.get("metadata") or {}):
                ids.append(d["id"])
    with engine.begin() as conn:
        r = conn.execute(text(
            "UPDATE rag_embeddings SET metadata = metadata - 'module' WHERE collection='runbook' AND id = ANY(CAST(:ids AS text[]))"
        ), {"ids": ids})
    return int(r.rowcount or 0)


# ───────────────────────── R4: incidents saklama (yaş bazlı budama) ─────────────────────────
# Politika (kullanıcı kararı, 2026-10-22): yalnız event/log türleri 60 günden eskiyse budanır;
# `incident` (metadata.incident_id), `vcenter_alarm`, `vcenter_task`, `virt_resource` KALICI (budanmaz).
# Varsayılan KAPALI (`rag_incidents_retention_enabled`); silme için kullanıcının AYRI açık onayı gerekir.
RETENTION_COLLECTION = "incidents"
RETENTION_EVENT_TYPES = ("vcenter_event", "openshift_event", "openshift_virt_event", "log_entry", "virt_log")
DEFAULT_RETENTION_DAYS = 60
RETENTION_BACKUP_DIR = os.environ.get("RAG_RETENTION_BACKUP_DIR", "/app/uploads/_backups/rag-retention")

_RET_WHERE = (
    "collection = :coll AND metadata->>'event_type' = ANY(CAST(:types AS text[])) "
    "AND created_at < now() - make_interval(days => :days)"
)


def _ret_params(days: int, collection: str) -> Dict[str, Any]:
    d = int(days)
    if d < 1:
        raise ValueError("saklama süresi en az 1 gün olmalı")
    return {"coll": collection, "types": list(RETENTION_EVENT_TYPES), "days": d}


def plan_incidents_retention(days: int = DEFAULT_RETENTION_DAYS, *, collection: str = RETENTION_COLLECTION) -> Dict[str, Any]:
    """Salt-okunur dry-run: silinecek satır sayısı/türü/yaşı + korunanlar. HİÇBİR şey yazılmaz/silinmez."""
    from app.core.database import engine
    params = _ret_params(days, collection)
    with engine.connect() as conn:
        by_type = conn.execute(text(
            f"SELECT metadata->>'event_type' t, count(*) n, min(created_at) oldest, max(created_at) newest, "
            f"round(avg(length(document))) avg_len, sum(length(document)) doc_chars "
            f"FROM rag_embeddings WHERE {_RET_WHERE} GROUP BY 1 ORDER BY 2 DESC"
        ), params).fetchall()
        total = conn.execute(text("SELECT count(*) FROM rag_embeddings WHERE collection = :coll"), {"coll": collection}).scalar()
    items = [{
        "event_type": r[0], "rows": int(r[1]), "oldest": str(r[2]), "newest": str(r[3]),
        "avg_len": int(r[4] or 0), "doc_chars": int(r[5] or 0),
    } for r in by_type]
    n = sum(i["rows"] for i in items)
    return {
        "collection": collection, "days": params["days"], "types": list(RETENTION_EVENT_TYPES),
        "would_delete": n, "collection_rows": int(total or 0), "would_keep": int(total or 0) - n,
        "by_type": items, "protected": "incident / vcenter_alarm / vcenter_task / virt_resource ve süresi dolmamış satırlar",
        "dry_run": True,
    }


def backup_incidents_retention(
    backup_path: str, *, days: int = DEFAULT_RETENTION_DAYS, limit: Optional[int] = None,
    collection: str = RETENTION_COLLECTION,
) -> Dict[str, Any]:
    """Budanacak satırların TAM dökümü (embedding HARİÇ): id, document, metadata, created_at → JSONL (+ .sha256).
    Mevcut dosyanın üzerine YAZMAZ. Yalnız okur."""
    from app.core.database import engine
    path = Path(backup_path)
    if path.exists():
        raise FileExistsError(f"yedek dosyası zaten var: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    params = _ret_params(days, collection)
    lim = ""
    if limit is not None and int(limit) > 0:
        lim = " LIMIT :lim"
        params["lim"] = int(limit)
    h = hashlib.sha256()
    n = 0
    tmp = path.with_suffix(path.suffix + ".part")
    try:
        with engine.connect() as conn, open(tmp, "w", encoding="utf-8") as f:
            res = conn.execution_options(stream_results=True).execute(text(
                f"SELECT id, document, metadata, created_at FROM rag_embeddings WHERE {_RET_WHERE} "
                f"ORDER BY created_at ASC, id ASC{lim}"
            ), params)
            for row in res:
                line = json.dumps({
                    "id": row[0], "document": row[1], "metadata": row[2],
                    "created_at": row[3].isoformat() if row[3] is not None else None,
                }, ensure_ascii=False) + "\n"
                f.write(line)
                h.update(line.encode("utf-8"))
                n += 1
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    Path(str(path) + ".sha256").write_text(f"{h.hexdigest()}  {path.name}  rows={n}\n", encoding="utf-8")
    return {"path": str(path), "rows": n, "bytes": path.stat().st_size, "sha256": h.hexdigest()}


def prune_incidents_by_age(
    days: int = DEFAULT_RETENTION_DAYS, *, dry_run: bool = True, backup_path: Optional[str] = None,
    limit: Optional[int] = None, collection: str = RETENTION_COLLECTION,
) -> Dict[str, Any]:
    """Yaş bazlı budama. `dry_run=True` (varsayılan) → yalnız rapor. Gerçek koşu: ÖNCE yedek (embedding hariç) yazılır,
    SONRA yalnız yedekteki id'ler TEK işlemde silinir; silinen satır ≠ yedek satırı ise işlem GERİ ALINIR.
    VACUUM/REINDEX yapmaz (ayrı bakım işi)."""
    if dry_run:
        return plan_incidents_retention(days, collection=collection)
    if not backup_path:
        raise ValueError("silme için backup_path zorunlu")
    from app.core.database import engine
    bk = backup_incidents_retention(backup_path, days=days, limit=limit, collection=collection)
    n = int(bk["rows"])
    if n == 0:
        return {"deleted": 0, "backup": bk, "dry_run": False}
    with engine.begin() as conn:
        conn.execute(text("CREATE TEMP TABLE _rag_prune_ids (id text PRIMARY KEY) ON COMMIT DROP"))
        batch: list = []
        with open(backup_path, encoding="utf-8") as f:
            for line in f:
                batch.append({"i": json.loads(line)["id"]})
                if len(batch) >= 5000:
                    conn.execute(text("INSERT INTO _rag_prune_ids (id) VALUES (:i)"), batch)
                    batch = []
        if batch:
            conn.execute(text("INSERT INTO _rag_prune_ids (id) VALUES (:i)"), batch)
        res = conn.execute(text(
            "DELETE FROM rag_embeddings r USING _rag_prune_ids t WHERE r.id = t.id AND r.collection = :coll"
        ), {"coll": collection})
        deleted = int(res.rowcount or 0)
        if deleted != n:
            raise RuntimeError(f"silinen satır ({deleted}) yedek satırına ({n}) eşit değil — işlem geri alındı")
    logger.info("RAG incidents retention: %s satır silindi (yedek %s)", deleted, backup_path)
    return {"deleted": deleted, "backup": bk, "dry_run": False}


def run_incidents_retention_job() -> Dict[str, Any]:
    """Zamanlı bakım (`fleet_jobs.run_rag_maintenance`) kancası. `rag_incidents_retention_enabled` KAPALI (varsayılan)
    ise hiçbir şey yapmaz. Açıksa: `rag_incidents_retention_days` günden eski event/log satırları, tur başına en çok
    `rag_maintenance_max_delete`, yedekli ve tek işlemde silinir."""
    try:
        from app.services import runtime_settings as rs
        if not rs.get_bool("rag_incidents_retention_enabled"):
            return {"skipped": "disabled"}
        days = int(rs.get_int("rag_incidents_retention_days"))
        cap = int(rs.get_int("rag_maintenance_max_delete") or 50000)
    except Exception:
        return {"skipped": "settings_unavailable"}
    path = os.path.join(RETENTION_BACKUP_DIR, f"incidents-retention-{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
    try:
        plan = plan_incidents_retention(days)
        if int(plan.get("would_delete") or 0) == 0:  # silinecek yoksa boş yedek dosyası bırakma
            logger.info("RAG incidents retention: silinecek satır yok (%s gün)", days)
            return {"deleted": 0, "would_delete": 0, "days": days}
        return prune_incidents_by_age(days, dry_run=False, backup_path=path, limit=max(1, cap))
    except Exception as exc:
        logger.exception("RAG incidents retention hata")
        return {"error": str(exc)}
