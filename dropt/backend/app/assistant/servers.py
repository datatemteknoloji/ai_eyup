from __future__ import annotations

import json
import re
from typing import Any

from sqlmodel import Session, col, select

from app.core.config import get_settings
from app.models.server import TargetServer

_CACHE_KEY = "assistant:server_index:v1"
_CACHE_TTL = 60

_REF_CUES = (
    r"gibi",
    r"benzer(?:i|ine)?",
    r"ayn[ıi]",
    r"referans",
    r"kopya",
    r"örne[gğ]i",
    r"ornegi",
    r"like",
    r"similar\s+to",
    r"same\s+as",
    r"as\s+on",
)


def _redis():
    import redis

    return redis.from_url(get_settings().redis_url, decode_responses=True)


def _short_host(hostname: str) -> str:
    h = (hostname or "").strip().lower()
    if not h:
        return ""
    return h.split(".", 1)[0]


def load_server_index(session: Session) -> list[dict[str, Any]]:
    """Cached list of {id, hostname, short, ip} for assistant resolve."""
    try:
        r = _redis()
        raw = r.get(_CACHE_KEY)
        if raw:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
    except Exception:
        pass

    rows = session.exec(select(TargetServer).order_by(col(TargetServer.hostname))).all()
    out: list[dict[str, Any]] = []
    for s in rows:
        hn = (s.hostname or "").strip()
        out.append(
            {
                "id": int(s.id),  # type: ignore[arg-type]
                "hostname": hn,
                "short": _short_host(hn),
                "ip": (s.ip or "").strip(),
            }
        )
    try:
        r = _redis()
        r.setex(_CACHE_KEY, _CACHE_TTL, json.dumps(out, ensure_ascii=True))
    except Exception:
        pass
    return out


def invalidate_server_index() -> None:
    try:
        _redis().delete(_CACHE_KEY)
    except Exception:
        pass


def resolve_servers_in_message(
    session: Session,
    message: str,
) -> dict[str, Any]:
    """
    Short hostname match is enough (enesapp → enesapp.datatem.local).
    Multiple different servers → ambiguous.
    """
    index = load_server_index(session)
    if not index or not (message or "").strip():
        return {"matches": [], "ambiguous": False}

    text = message.lower()
    found: dict[int, dict[str, Any]] = {}

    for row in index:
        candidates = []
        if row.get("hostname"):
            candidates.append(str(row["hostname"]).lower())
        if row.get("short"):
            candidates.append(str(row["short"]).lower())
        if row.get("ip"):
            candidates.append(str(row["ip"]).lower())
        for cand in candidates:
            if len(cand) < 2:
                continue
            if re.search(rf"(?<![a-z0-9_-]){re.escape(cand)}(?![a-z0-9_-])", text):
                found[int(row["id"])] = row
                break

    matches = list(found.values())
    return {
        "matches": matches,
        "ambiguous": len(matches) > 1,
    }


def _host_names(row: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for k in ("hostname", "short", "ip"):
        v = (row.get(k) or "").strip().lower()
        if v and v not in out:
            out.append(v)
    return out


def _appearance_index(text: str, row: dict[str, Any]) -> int:
    best = 10**9
    for name in _host_names(row):
        if len(name) < 2:
            continue
        m = re.search(rf"(?<![a-z0-9_-]){re.escape(name)}(?![a-z0-9_-])", text)
        if m:
            best = min(best, m.start())
    return best


def _is_reference_mention(text: str, row: dict[str, Any]) -> bool:
    for name in _host_names(row):
        if len(name) < 2:
            continue
        for cue in _REF_CUES:
            pat = (
                rf"(?<![a-z0-9_-]){re.escape(name)}(?![a-z0-9_-]).{{0,48}}(?:{cue})"
                rf"|(?:{cue}).{{0,48}}(?<![a-z0-9_-]){re.escape(name)}(?![a-z0-9_-])"
            )
            if re.search(pat, text, flags=re.IGNORECASE):
                return True
    return False


def classify_servers_in_message(session: Session, message: str) -> dict[str, Any]:
    """
    Split inventory hits into target vs reference.
    'enesprotocol ... minio1 gibi' → target=enesprotocol, reference=minio1
    """
    resolved = resolve_servers_in_message(session, message)
    matches = list(resolved.get("matches") or [])
    text = (message or "").lower()
    if not matches:
        return {"targets": [], "references": [], "matches": [], "ambiguous": False}
    if len(matches) == 1:
        return {
            "targets": matches,
            "references": [],
            "matches": matches,
            "ambiguous": False,
        }

    refs: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    for row in matches:
        if _is_reference_mention(text, row):
            refs.append(row)
        else:
            targets.append(row)

    has_cue = any(re.search(c, text, flags=re.IGNORECASE) for c in _REF_CUES)
    if not refs and has_cue and len(matches) >= 2:
        ordered = sorted(matches, key=lambda r: _appearance_index(text, r))
        targets = [ordered[0]]
        refs = ordered[1:]
    elif not targets and refs:
        ordered = sorted(refs, key=lambda r: _appearance_index(text, r))
        targets = [ordered[0]]
        refs = ordered[1:]
    elif len(targets) > 1 and refs:
        targets = sorted(targets, key=lambda r: _appearance_index(text, r))[:1]

    return {
        "targets": targets,
        "references": refs,
        "matches": matches,
        "ambiguous": len(targets) > 1,
    }


def build_deep_link(route: str | None, targets: list[dict[str, Any]]) -> str | None:
    if not route:
        return None
    if not targets:
        return route
    primary = int(targets[0]["id"])
    qs = f"serverId={primary}"
    if len(targets) > 1:
        ids = ",".join(str(int(t["id"])) for t in targets[:2])
        qs += f"&serverIds={ids}"
    sep = "&" if "?" in route else "?"
    return f"{route}{sep}{qs}"
