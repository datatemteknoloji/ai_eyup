"""ainew ürün GUIDE — docs/guides Markdown birleştirme ve HTML.

Canlı envanter snapshot'ı değildir. RAG ingest yoktur.
"""
from __future__ import annotations

import html
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.core.version import get_app_version

_FULL_FILES = [
    "01-overview.md",
    "02-architecture.md",
    "03-capability.md",
    "04-scenarios.md",
    "05-reference.md",
]

PACKS: Dict[str, Dict[str, Any]] = {
    "full": {
        "files": _FULL_FILES,
        "title_tr": "ainew Ana GUIDE — Mimari ve Yetenekler",
        "title_en": "ainew Master GUIDE — Architecture & Capabilities",
        "sort": 0,
    },
    "linux": {
        "files": ["modules/linux.md"],
        "title_tr": "ainew Linux GUIDE",
        "title_en": "ainew Linux GUIDE",
        "sort": 10,
    },
    "virtualization": {
        "files": ["modules/virtualization.md"],
        "title_tr": "ainew Sanallaştırma GUIDE",
        "title_en": "ainew Virtualization GUIDE",
        "sort": 20,
    },
    "windows": {
        "files": ["modules/windows.md"],
        "title_tr": "ainew Windows GUIDE",
        "title_en": "ainew Windows GUIDE",
        "sort": 30,
    },
    "openshift": {
        "files": ["modules/openshift.md"],
        "title_tr": "ainew OpenShift ve oVirt GUIDE",
        "title_en": "ainew OpenShift and oVirt GUIDE",
        "sort": 40,
    },
    # AI sohbet/tool/RAG davranış haritası. Routing veya tool değişince
    # docs/guides/{tr,en}/modules/ai-architecture.md aynı turda güncellenir.
    "ai-architecture": {
        "files": ["modules/ai-architecture.md"],
        "title_tr": "ainew AI Mimari GUIDE",
        "title_en": "ainew AI Architecture GUIDE",
        "sort": 50,
    },
}


def resolve_guide_root() -> Path:
    env = (os.environ.get("PRODUCT_GUIDE_PATH") or "").strip()
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates.append(Path("/app/docs/guides"))
    here = Path(__file__).resolve()
    # repo: …/app/backend/app/services/this.py → parents[3] = repo root on host
    candidates.append(here.parents[3] / "docs" / "guides")
    candidates.append(here.parents[2] / "docs" / "guides")
    for p in candidates:
        if p.is_dir() and (p / "tr").is_dir():
            return p
    raise FileNotFoundError(
        "docs/guides bulunamadı. PRODUCT_GUIDE_PATH veya ./docs/guides volume gerekir."
    )


def list_packs(locale: str = "tr") -> List[Dict[str, str]]:
    loc = "en" if locale == "en" else "tr"
    title_key = "title_en" if loc == "en" else "title_tr"
    rows = []
    for pid, meta in sorted(PACKS.items(), key=lambda kv: kv[1]["sort"]):
        rows.append({"id": pid, "title": meta[title_key]})
    return rows


def _inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def _table(rows: List[str]) -> str:
    if len(rows) < 2:
        return ""
    def cells(line: str) -> List[str]:
        raw = [c.strip() for c in line.strip().strip("|").split("|")]
        return raw

    head = cells(rows[0])
    body_lines = rows[2:] if re.match(r"^\s*\|?\s*:?-+:?", rows[1]) else rows[1:]
    th = "".join(f"<th>{_inline(c)}</th>" for c in head)
    trs = []
    for line in body_lines:
        if not line.strip():
            continue
        tds = "".join(f"<td>{_inline(c)}</td>" for c in cells(line))
        trs.append(f"<tr>{tds}</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(trs)}</tbody></table>"


def markdown_to_html(md: str) -> str:
    """Sınırlı Markdown → HTML (başlık, liste, tablo, kod, mermaid)."""
    lines = md.replace("\r\n", "\n").split("\n")
    out: List[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.strip().startswith("```"):
            fence = line.strip()[3:].strip()
            i += 1
            buf: List[str] = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            raw = "\n".join(buf)
            body = html.escape(raw)
            kind = (fence or "").split()[0].lower() if fence else ""
            looks_diagram = (
                kind in ("mermaid", "diagram", "ascii", "text")
                or "│" in raw
                or "└" in raw
                or "┌" in raw
            )
            if looks_diagram:
                out.append(
                    '<pre class="diagram"><span class="diagram-label">Diagram</span>\n'
                    + body
                    + "</pre>"
                )
            else:
                out.append(f"<pre><code>{body}</code></pre>")
            continue
        if re.match(r"^\s*\|", line) and i + 1 < n and re.search(r"\|", lines[i + 1]):
            tbl = [line]
            i += 1
            while i < n and re.match(r"^\s*\|", lines[i]):
                tbl.append(lines[i])
                i += 1
            rendered = _table(tbl)
            if rendered:
                out.append(rendered)
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue
        if re.match(r"^---+\s*$", line):
            out.append("<hr/>")
            i += 1
            continue
        if re.match(r"^[-*]\s+", line):
            items = []
            bullet_re = re.compile(r"^[-*]\s+")
            while i < n and bullet_re.match(lines[i]):
                items.append("<li>" + _inline(bullet_re.sub("", lines[i], count=1)) + "</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        if re.match(r"^\d+\.\s+", line):
            items = []
            num_re = re.compile(r"^\d+\.\s+")
            while i < n and num_re.match(lines[i]):
                items.append("<li>" + _inline(num_re.sub("", lines[i], count=1)) + "</li>")
                i += 1
            out.append("<ol>" + "".join(items) + "</ol>")
            continue
        if not line.strip():
            i += 1
            continue
        para = [line]
        i += 1
        while i < n and lines[i].strip() and not re.match(
            r"^(#{1,3}\s|```|---|[-*]\s|\d+\.\s|\|)", lines[i]
        ):
            para.append(lines[i])
            i += 1
        out.append(f"<p>{_inline(' '.join(para))}</p>")
    return "\n".join(out)


def assemble_markdown(pack: str, locale: str) -> Tuple[str, str]:
    if pack not in PACKS:
        raise KeyError(pack)
    loc = "en" if locale == "en" else "tr"
    root = resolve_guide_root() / loc
    parts: List[str] = []
    for rel in PACKS[pack]["files"]:
        path = root / rel
        if not path.is_file():
            raise FileNotFoundError(str(path))
        parts.append(path.read_text(encoding="utf-8").strip())
    title = PACKS[pack]["title_en" if loc == "en" else "title_tr"]
    return title, "\n\n".join(parts) + "\n"


def build_product_guide(pack: str, locale: str) -> Dict[str, Any]:
    loc = "en" if locale == "en" else "tr"
    title, md = assemble_markdown(pack, loc)
    version = get_app_version()
    body = markdown_to_html(md)
    filename = f"ainew-guide-{pack}-{loc}-v{version}.pdf"
    return {
        "pack": pack,
        "locale": loc,
        "title": title,
        "version": version,
        "filename": filename,
        "html": body,
    }
