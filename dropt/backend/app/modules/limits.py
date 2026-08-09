from __future__ import annotations

import json
import re
import shlex
from typing import Any

from sqlmodel import Session

from app.core.config import get_settings
from app.models.server import TargetServer
from app.modules.base import HostPlan
from app.services.target_ssh import run_ssh

ACTION_TITLES = {"set": "Security limits ayarla"}

CONF_FILE = "/etc/security/limits.d/99-dropt-portal.conf"
LIMITS_CONF = "/etc/security/limits.conf"
LIMITS_D = "/etc/security/limits.d"
_CACHE_TTL_SEC = 60 * 15

LIMIT_TYPES = ("soft", "hard", "-")

# Yaygın pam_limits item’leri (UI hazır listesi)
PRESET_ITEMS: list[str] = [
    "nofile",
    "nproc",
    "stack",
    "memlock",
    "data",
    "core",
    "fsize",
    "cpu",
    "as",
    "locks",
    "sigpending",
    "msgqueue",
    "nice",
    "rtprio",
    "priority",
    "maxlogins",
    "maxsyslogins",
]

DOMAIN_RE = re.compile(r"^(@?%?[A-Za-z0-9_.*-]+|\*)$")
ITEM_RE = re.compile(r"^[a-z][a-z0-9_]*$")
VALUE_RE = re.compile(r"^(unlimited|[0-9]+)$", re.IGNORECASE)
LINE_RE = re.compile(
    r"^(\S+)\s+(soft|hard|-)\s+(\S+)\s+(\S+)\s*$",
    re.IGNORECASE,
)

# ulimit doğrulama (login shell soft/hard)
ULIMIT_MAP: dict[str, str] = {
    "core": "c",
    "data": "d",
    "fsize": "f",
    "memlock": "l",
    "nofile": "n",
    "stack": "s",
    "cpu": "t",
    "nproc": "u",
    "as": "v",
    "nice": "e",
    "rtprio": "r",
    "locks": "x",
    "sigpending": "i",
    "msgqueue": "q",
}


def list_allowed_items() -> list[str]:
    return list(PRESET_ITEMS)


def list_limit_types() -> list[str]:
    return list(LIMIT_TYPES)


def job_summary(action: str, payload: dict[str, Any]) -> str:
    entries = _resolve_entries(payload)
    bits = [f"{e['domain']} {e['type']} {e['item']}={e['value']}" for e in entries[:4]]
    more = f" (+{len(entries) - 4})" if len(entries) > 4 else ""
    return f"{ACTION_TITLES.get(action, action)}: {', '.join(bits)}{more}"


def entry_id(domain: str, typ: str, item: str) -> str:
    return f"{domain}|{typ}|{item}"


def _normalize_value(val: str) -> str:
    v = val.strip()
    if v.lower() == "unlimited":
        return "unlimited"
    return v


def _parse_line(raw: str) -> dict[str, str] | None:
    line = raw.strip()
    if not line or line.startswith("#"):
        return None
    m = LINE_RE.match(line)
    if not m:
        return None
    domain, typ, item, value = m.group(1), m.group(2).lower(), m.group(3).lower(), m.group(4)
    if typ == "-":
        typ = "-"
    return {
        "domain": domain,
        "type": typ,
        "item": item,
        "value": _normalize_value(value),
    }


def parse_custom_lines(text: str) -> list[dict[str, str]]:
    """Çok satır: 'domain soft|hard|- item value'."""
    out: list[dict[str, str]] = []
    for i, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entry = _parse_line(line)
        if entry is None:
            raise ValueError(
                f"Satır {i}: beklenen biçim 'domain soft|hard|- item value' ({line!r})"
            )
        _validate_entry(entry, where=f"Satır {i}")
        out.append(entry)
    return out


def _validate_entry(entry: dict[str, str], *, where: str = "") -> None:
    prefix = f"{where}: " if where else ""
    domain = entry["domain"]
    typ = entry["type"]
    item = entry["item"]
    value = entry["value"]
    if not DOMAIN_RE.match(domain):
        raise ValueError(f"{prefix}geçersiz domain: {domain}")
    if typ not in LIMIT_TYPES:
        raise ValueError(f"{prefix}type soft|hard|- olmalı: {typ}")
    if not ITEM_RE.match(item):
        raise ValueError(f"{prefix}geçersiz item: {item}")
    if not VALUE_RE.match(value):
        raise ValueError(f"{prefix}değer sayı veya unlimited olmalı: {value}")
    entry["value"] = _normalize_value(value)


def _soft_hard_consistent(entries: list[dict[str, str]]) -> None:
    """Aynı domain+item için soft > hard olmasın (payload içi)."""
    soft: dict[tuple[str, str], int] = {}
    hard: dict[tuple[str, str], int] = {}
    for e in entries:
        key = (e["domain"], e["item"])
        if e["value"].lower() == "unlimited":
            continue
        try:
            n = int(e["value"])
        except ValueError:
            continue
        if e["type"] == "soft":
            soft[key] = n
        elif e["type"] == "hard":
            hard[key] = n
        elif e["type"] == "-":
            soft[key] = n
            hard[key] = n
    for key, s in soft.items():
        h = hard.get(key)
        if h is not None and s > h:
            raise ValueError(
                f"soft > hard olamaz: {key[0]} {key[1]} soft={s} hard={h}"
            )


def _resolve_entries(payload: dict[str, Any]) -> list[dict[str, str]]:
    """
    Payload:
      - domain + limit_type + item + value
      - entries: [{domain,type,item,value}, ...]
      - custom: multiline limits satırları
    """
    by_id: dict[str, dict[str, str]] = {}

    raw_entries = payload.get("entries")
    if isinstance(raw_entries, list):
        for i, row in enumerate(raw_entries, start=1):
            if not isinstance(row, dict):
                raise ValueError(f"entries[{i}] nesne olmalı")
            entry = {
                "domain": str(row.get("domain") or "").strip(),
                "type": str(row.get("type") or row.get("limit_type") or "").strip().lower(),
                "item": str(row.get("item") or "").strip().lower(),
                "value": str(row.get("value") or "").strip(),
            }
            _validate_entry(entry, where=f"entries[{i}]")
            by_id[entry_id(entry["domain"], entry["type"], entry["item"])] = entry

    domain = str(payload.get("domain") or "").strip()
    typ = str(payload.get("limit_type") or payload.get("type") or "").strip().lower()
    item = str(payload.get("item") or "").strip().lower()
    value = str(payload.get("value") or "").strip()
    if domain or typ or item or value:
        if not (domain and typ and item and value):
            raise ValueError("Hazır form: domain, type, item ve value birlikte gerekli")
        entry = {"domain": domain, "type": typ, "item": item, "value": value}
        _validate_entry(entry, where="Hazır form")
        by_id[entry_id(domain, typ, item)] = entry

    custom = payload.get("custom") or payload.get("custom_lines") or ""
    if custom:
        for entry in parse_custom_lines(str(custom)):
            by_id[entry_id(entry["domain"], entry["type"], entry["item"])] = entry

    entries = list(by_id.values())
    if not entries:
        raise ValueError("En az bir limit satırı gerekli (hazır form veya custom)")
    _soft_hard_consistent(entries)
    return entries


def _conflict_keys(entries: list[dict[str, str]]) -> set[str]:
    """Yorumlanacak satır kimlikleri (domain|type|item)."""
    keys: set[str] = set()
    for e in entries:
        d, t, it = e["domain"], e["type"], e["item"]
        keys.add(entry_id(d, t, it))
        if t in ("soft", "hard"):
            keys.add(entry_id(d, "-", it))
        if t == "-":
            keys.add(entry_id(d, "soft", it))
            keys.add(entry_id(d, "hard", it))
    return keys


def read_limits_files(session: Session, server: TargetServer) -> list[dict[str, str]]:
    """limits.conf + limits.d/*.conf aktif satırları (son kazanan)."""
    script = f"""
set -e
echo FILES_BEGIN
if [ -f {shlex.quote(LIMITS_CONF)} ]; then
  echo "FILE:{LIMITS_CONF}"
  cat {shlex.quote(LIMITS_CONF)}
  echo "FILE_END"
fi
for f in {shlex.quote(LIMITS_D)}/*.conf; do
  [ -f "$f" ] || continue
  echo "FILE:$f"
  cat "$f"
  echo "FILE_END"
done
echo FILES_END
"""
    r = run_ssh(session, server, script, timeout=45)
    if not r.ok and not (r.stdout or "").strip():
        raise RuntimeError(r.stderr or "limits dosyaları okunamadı")

    by_id: dict[str, dict[str, str]] = {}
    current_file = ""
    for raw in (r.stdout or "").splitlines():
        if raw.startswith("FILE:") and not raw.startswith("FILE_END"):
            current_file = raw[5:].strip()
            continue
        if raw in ("FILE_END", "FILES_BEGIN", "FILES_END"):
            continue
        entry = _parse_line(raw)
        if entry is None:
            continue
        eid = entry_id(entry["domain"], entry["type"], entry["item"])
        by_id[eid] = {
            **entry,
            "source": current_file,
        }
    # Stabilize order: domain, item, type
    rows = list(by_id.values())
    rows.sort(key=lambda e: (e["domain"], e["item"], e["type"]))
    return rows


def read_ulimit_for_user(
    session: Session, server: TargetServer, username: str
) -> dict[str, Any]:
    """su - user ile soft/hard ulimit özeti (domain gerçek user ise)."""
    user = username.strip()
    if not user or user.startswith("@") or user == "*" or "%" in user:
        raise ValueError("ulimit doğrulaması için gerçek kullanıcı adı gerekli")
    if not re.match(r"^[A-Za-z0-9_.-]+$", user):
        raise ValueError("geçersiz kullanıcı adı")
    q = shlex.quote(user)
    # soft (-S) ve hard (-H) seçili item’ler
    parts = [f"echo USER:{user}"]
    for item, flag in ULIMIT_MAP.items():
        parts.append(
            f'printf "soft:{item}="; ulimit -S -{flag} 2>/dev/null || echo FAIL; printf "\\n"'
        )
        parts.append(
            f'printf "hard:{item}="; ulimit -H -{flag} 2>/dev/null || echo FAIL; printf "\\n"'
        )
    inner = "\n".join(parts)
    script = f"su - {q} -c {shlex.quote(inner)}"
    r = run_ssh(session, server, script, timeout=30)
    soft: dict[str, str] = {}
    hard: dict[str, str] = {}
    for line in (r.stdout or "").splitlines():
        if line.startswith("soft:") and "=" in line:
            k, _, v = line.partition("=")
            soft[k[5:]] = v.strip()
        elif line.startswith("hard:") and "=" in line:
            k, _, v = line.partition("=")
            hard[k[5:]] = v.strip()
    return {
        "user": user,
        "soft": soft,
        "hard": hard,
        "ok": r.ok,
        "stderr": (r.stderr or "")[:500],
    }


def _redis():
    import redis

    return redis.from_url(get_settings().redis_url, decode_responses=True)


def _cache_key(server_id: int) -> str:
    return f"limits:current:{server_id}"


def get_cached_limits(server_id: int) -> list[dict[str, str]] | None:
    try:
        raw = _redis().get(_cache_key(server_id))
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, list) else None
    except Exception:
        return None


def set_cached_limits(server_id: int, entries: list[dict[str, str]]) -> None:
    try:
        _redis().setex(_cache_key(server_id), _CACHE_TTL_SEC, json.dumps(entries))
    except Exception:
        pass


def invalidate_cached_limits(server_id: int) -> None:
    try:
        _redis().delete(_cache_key(server_id))
    except Exception:
        pass


def get_current_limits(
    session: Session,
    server: TargetServer,
    *,
    refresh: bool = False,
    verify_user: str | None = None,
) -> dict[str, Any]:
    sid = int(server.id)  # type: ignore[arg-type]
    if not refresh:
        cached = get_cached_limits(sid)
        if cached is not None:
            out: dict[str, Any] = {
                "entries": cached,
                "cached": True,
                "server_id": sid,
            }
            if verify_user:
                try:
                    out["ulimit"] = read_ulimit_for_user(session, server, verify_user)
                except Exception as exc:  # noqa: BLE001
                    out["ulimit_error"] = str(exc)
            return out

    entries = read_limits_files(session, server)
    set_cached_limits(sid, entries)
    out = {"entries": entries, "cached": False, "server_id": sid}
    if verify_user:
        try:
            out["ulimit"] = read_ulimit_for_user(session, server, verify_user)
        except Exception as exc:  # noqa: BLE001
            out["ulimit_error"] = str(exc)
    return out


def build_plans(
    session: Session, action: str, servers: list[TargetServer], payload: dict[str, Any]
) -> list[HostPlan]:
    plans: list[HostPlan] = []
    for server in servers:
        try:
            if action != "set":
                raise ValueError(f"Bilinmeyen aksiyon: {action}")
            entries = _resolve_entries(payload)
            current = read_limits_files(session, server)
            cur_map = {
                entry_id(e["domain"], e["type"], e["item"]): e for e in current
            }
            diffs: list[str] = []
            for e in entries:
                eid = entry_id(e["domain"], e["type"], e["item"])
                before = (cur_map.get(eid) or {}).get("value") or "?"
                diffs.append(f"{e['domain']} {e['type']} {e['item']}: {before} → {e['value']}")
            lines = [f"{e['domain']} {e['type']} {e['item']} {e['value']}" for e in entries]
            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=True,
                    summary_tr=f"{server.hostname}: {', '.join(diffs)}",
                    planned_commands=[
                        "comment matching lines in /etc/security/limits.conf and limits.d/*.conf (bak)",
                        f"write {CONF_FILE}",
                        *[f"# {ln}" for ln in lines],
                    ],
                    before_state={
                        "entries": entries,
                        "current": current,
                        "conf_file": CONF_FILE,
                        "lines": lines,
                        "conflict_keys": sorted(_conflict_keys(entries)),
                    },
                    risk_notes=(
                        "Portal limits conf yazılacak; çakışan satırlar limits.conf ve "
                        "limits.d içinde # ile yorumlanacak. Limitler yeni login’de geçerli olur "
                        "(mevcut oturum değişmez)."
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=False,
                    summary_tr=f"{server.hostname}: {msg}",
                    error=msg,
                )
            )
    return plans


def apply_plan(
    session: Session,
    server: TargetServer,
    action: str,
    payload: dict[str, Any],
    plan: HostPlan,
    *,
    job_id: int = 0,
) -> tuple[bool, dict[str, Any], str, str]:
    _ = (job_id, action, payload)
    if not plan.ok:
        return False, plan.before_state, "", plan.error
    entries: list[dict[str, str]] = plan.before_state.get("entries") or []
    conf = plan.before_state.get("conf_file") or CONF_FILE
    conflict = plan.before_state.get("conflict_keys") or sorted(_conflict_keys(entries))
    body_lines = "\n".join(
        f"{e['domain']} {e['type']} {e['item']} {e['value']}" for e in entries
    )
    # conflict keys: domain|type|item — awk’te | ile ayır
    keys_joined = " ".join(conflict)

    script = f"""
set -e
CONF={shlex.quote(conf)}
KEYS={shlex.quote(keys_joined)}
comment_limits() {{
  local f="$1"
  [ -f "$f" ] || return 0
  local TMP
  TMP=$(mktemp)
  awk -v keys="$KEYS" '
BEGIN {{
  n=split(keys,a," ")
  for(i=1;i<=n;i++) skip[a[i]]=1
}}
{{
  raw=$0
  line=$0
  sub(/^[ \\t]+/,"",line)
  if (line == "" || line ~ /^#/) {{ print raw; next }}
  # domain type item value
  n=split(line, p, /[ \\t]+/)
  if (n < 4) {{ print raw; next }}
  d=p[1]; t=tolower(p[2]); it=tolower(p[3])
  if (t!="soft" && t!="hard" && t!="-") {{ print raw; next }}
  id=d "|" t "|" it
  if (id in skip) {{
    print "# " line
    next
  }}
  print raw
}}
' "$f" > "$TMP"
  if cmp -s "$f" "$TMP"; then
    rm -f "$TMP"
  else
    cp -a "$f" "$f.bak.$(date +%s)"
    mv "$TMP" "$f"
    echo "COMMENTED:$f"
  fi
}}

echo COMMENT_PASS_BEGIN
if [ -f {shlex.quote(LIMITS_CONF)} ]; then
  comment_limits {shlex.quote(LIMITS_CONF)}
fi
for f in {shlex.quote(LIMITS_D)}/*.conf; do
  [ -f "$f" ] || continue
  [ "$f" = "$CONF" ] && continue
  comment_limits "$f"
done
echo COMMENT_PASS_END

mkdir -p "$(dirname "$CONF")"
if [ -f "$CONF" ]; then cp -a "$CONF" "$CONF.bak.$(date +%s)"; fi
touch "$CONF"
TMP=$(mktemp)
awk -v keys="$KEYS" '
BEGIN {{
  n=split(keys,a," ")
  for(i=1;i<=n;i++) skip[a[i]]=1
}}
{{
  raw=$0
  line=$0
  sub(/^[ \\t]+/,"",line)
  if (line == "" || line ~ /^#/) {{ print raw; next }}
  n=split(line, p, /[ \\t]+/)
  if (n < 4) {{ print raw; next }}
  d=p[1]; t=tolower(p[2]); it=tolower(p[3])
  if (t!="soft" && t!="hard" && t!="-") {{ print raw; next }}
  id=d "|" t "|" it
  if (id in skip) {{
    print "# " line
    next
  }}
  print raw
}}
' "$CONF" > "$TMP" || true
{{
  echo ""
  echo "# updated $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  cat <<'EOF'
{body_lines}
EOF
}} >> "$TMP"
mv "$TMP" "$CONF"
echo CONF_BEGIN
cat "$CONF"
echo CONF_END
"""
    # Opsiyonel: gerçek user domain’leri için soft/hard ulimit smoke
    verify_users = sorted(
        {
            e["domain"]
            for e in entries
            if e["domain"] not in ("*",)
            and not e["domain"].startswith("@")
            and not e["domain"].startswith("%")
            and re.match(r"^[A-Za-z0-9_.-]+$", e["domain"])
        }
    )
    for user in verify_users[:5]:
        q = shlex.quote(user)
        script += f"""
echo ULIMIT_BEGIN:{user}
su - {q} -c 'ulimit -a' 2>&1 | head -n 40 || true
echo ULIMIT_END:{user}
"""

    r = run_ssh(session, server, script, timeout=90)
    sid = int(server.id)  # type: ignore[arg-type]
    invalidate_cached_limits(sid)
    after_entries: list[dict[str, str]] = []
    try:
        after_entries = read_limits_files(session, server)
        set_cached_limits(sid, after_entries)
    except Exception:  # noqa: BLE001
        pass

    # Dosyada istenen satırlar aktif mi?
    after_map = {
        entry_id(e["domain"], e["type"], e["item"]): e for e in after_entries
    }
    ok = r.ok and all(
        (after_map.get(entry_id(e["domain"], e["type"], e["item"])) or {}).get("value")
        == e["value"]
        for e in entries
    )
    after = {
        **plan.before_state,
        "after": after_entries,
        "checklist": [
            "limits dosyalarında yeni satırları doğrula",
            "COMMENTED: satırlarını kontrol et",
            "Yeni login / su - user ile ulimit -a",
        ],
    }
    return ok, after, r.stdout, r.stderr
