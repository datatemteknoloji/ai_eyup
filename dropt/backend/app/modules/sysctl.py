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

ACTION_TITLES = {"set": "Kernel / HugePages ayarla"}

CONF_FILE = "/etc/sysctl.d/99-dropt-portal.conf"
_CACHE_TTL_SEC = 60 * 15  # 15 dk

# Hazır seçim listesi (UI Select)
PRESET_PARAMS: list[str] = [
    "vm.nr_hugepages",
    "vm.swappiness",
    "vm.min_free_kbytes",
    "vm.dirty_ratio",
    "vm.dirty_background_ratio",
    "kernel.panic",
    "kernel.unknown_nmi_panic",
    "kernel.panic_on_unrecovered_nmi",
    "kernel.panic_on_io_nmi",
    "kernel.sysrq",
    "kernel.panic_on_oops",
    "kernel.sem",
    "kernel.shmmni",
    "kernel.shmall",
    "kernel.shmmax",
    "fs.file-max",
    "fs.aio-max-nr",
    "net.core.somaxconn",
    "net.core.rmem_default",
    "net.core.rmem_max",
    "net.core.wmem_default",
    "net.core.wmem_max",
    "net.ipv4.conf.all.rp_filter",
    "net.ipv4.conf.default.rp_filter",
    "net.ipv4.ip_local_port_range",
]

# Geriye uyum: eski şablon API’si
TEMPLATES: dict[str, dict[str, Any]] = {
    "oracle_hugepages": {
        "label": "Oracle HugePages (vm.nr_hugepages)",
        "params": ["vm.nr_hugepages"],
    },
    "swappiness": {
        "label": "Swappiness (vm.swappiness)",
        "params": ["vm.swappiness"],
    },
}

PARAM_RE = re.compile(r"^[a-zA-Z0-9_.]+$")
# Tek sayı veya boşlukla ayrılmış çoklu sayı (kernel.sem, ip_local_port_range)
VALUE_RE = re.compile(r"^[0-9]+(?:[ \t]+[0-9]+)*$")
LINE_RE = re.compile(
    r"^([a-zA-Z0-9_.]+)\s*=\s*(.+)$"
)


def list_templates() -> list[dict[str, Any]]:
    """Eski API — preset listesiyle birlikte kullanılabilir."""
    return [
        {"id": k, "label": v["label"], "params": v["params"], "reboot_hint": False}
        for k, v in TEMPLATES.items()
    ]


def list_allowed_params() -> list[str]:
    return list(PRESET_PARAMS)


def list_presets() -> list[dict[str, str]]:
    return [{"key": k, "label": k} for k in PRESET_PARAMS]


def job_summary(action: str, payload: dict[str, Any]) -> str:
    params = _resolve_params(payload)
    keys = ", ".join(params.keys())
    return f"{ACTION_TITLES.get(action, action)}: {keys}"


def parse_custom_lines(text: str) -> dict[str, str]:
    """Çok satır: 'key = value' veya 'key=value'. # yorum satırları yok sayılır."""
    out: dict[str, str] = {}
    for i, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = LINE_RE.match(line)
        if not m:
            raise ValueError(f"Satır {i}: beklenen biçim 'parametre = değer' ({line!r})")
        key, val = m.group(1).strip(), m.group(2).strip()
        if not PARAM_RE.match(key):
            raise ValueError(f"Satır {i}: geçersiz parametre adı: {key}")
        if not VALUE_RE.match(val):
            raise ValueError(
                f"Satır {i}: değer sayı(lar) olmalı (örn. 10 veya 250 32000 100 200): {key}={val}"
            )
        out[key] = re.sub(r"[ \t]+", " ", val)
    return out


def _resolve_params(payload: dict[str, Any]) -> dict[str, str]:
    """
    Payload:
      - preset_key + preset_value  (hazır seçim)
      - params: {key: value, ...}
      - custom: "key = val\\n..."
      - template (eski): oracle_hugepages / swappiness + params
    """
    params: dict[str, str] = {}

    # Legacy template
    template_id = (payload.get("template") or "").strip()
    raw = payload.get("params") or {}
    if not isinstance(raw, dict):
        raise ValueError("params nesne olmalı")
    legacy = {str(k).strip(): str(v).strip() for k, v in raw.items() if str(k).strip()}

    if template_id:
        if template_id not in TEMPLATES:
            raise ValueError("Geçersiz şablon")
        expected = TEMPLATES[template_id]["params"]
        for key in expected:
            if key not in legacy or not legacy[key]:
                raise ValueError(f"Şablon için değer gerekli: {key}")
        params.update({k: legacy[k] for k in expected})
    else:
        params.update(legacy)

    preset_key = (payload.get("preset_key") or "").strip()
    preset_value = str(payload.get("preset_value") or "").strip()
    if preset_key:
        if preset_key not in PRESET_PARAMS:
            raise ValueError(f"Hazır listede yok: {preset_key}")
        if not preset_value:
            raise ValueError(f"Hazır parametre için değer gerekli: {preset_key}")
        params[preset_key] = preset_value

    custom = payload.get("custom") or payload.get("custom_lines") or ""
    if custom:
        custom_params = parse_custom_lines(str(custom))
        # custom aynı key'i ezer (bilinçli)
        params.update(custom_params)

    if not params:
        raise ValueError("En az bir parametre gerekli (hazır seçim veya custom)")

    for key, val in params.items():
        if not PARAM_RE.match(key):
            raise ValueError(f"Geçersiz parametre adı: {key}")
        if not VALUE_RE.match(val):
            raise ValueError(
                f"Değer sayı(lar) olmalı (örn. 10 veya 9000 65500): {key}={val}"
            )
        params[key] = re.sub(r"[ \t]+", " ", val.strip())
    return params


def read_current(session: Session, server: TargetServer, keys: list[str]) -> dict[str, str]:
    """Tek SSH ile birden fazla sysctl -n (sıralı KEY=VALUE satırları)."""
    out: dict[str, str] = {k: "" for k in keys}
    if not keys:
        return out
    parts: list[str] = []
    for key in keys:
        q = shlex.quote(key)
        parts.append(f'printf "%s=" {q}; sysctl -n {q} 2>/dev/null || true; printf "\\n"')
    script = "\n".join(parts)
    r = run_ssh(session, server, script, timeout=45)
    for line in (r.stdout or "").splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if k in out:
            out[k] = v.strip()
    return out


def _assert_params_exist(session: Session, server: TargetServer, keys: list[str]) -> None:
    """Hedef sunucuda parametre varlığını tek SSH ile doğrula."""
    if not keys:
        return
    parts: list[str] = []
    for i, key in enumerate(keys):
        q = shlex.quote(key)
        parts.append(f"sysctl -n {q} >/dev/null 2>&1 && echo OK:{i} || echo MISS:{i}")
    r = run_ssh(session, server, "\n".join(parts), timeout=45)
    missing: list[str] = []
    for ln in (r.stdout or "").splitlines():
        if ln.startswith("MISS:"):
            try:
                idx = int(ln.split(":", 1)[1].strip())
                missing.append(keys[idx])
            except (ValueError, IndexError):
                continue
    if missing:
        raise ValueError(
            "Sunucuda sysctl parametresi yok / okunamıyor: " + ", ".join(missing)
        )


def _redis():
    import redis

    return redis.from_url(get_settings().redis_url, decode_responses=True)


def _cache_key(server_id: int) -> str:
    return f"sysctl:current:{server_id}"


def get_cached_current(server_id: int) -> dict[str, str] | None:
    try:
        raw = _redis().get(_cache_key(server_id))
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def set_cached_current(server_id: int, values: dict[str, str]) -> None:
    try:
        _redis().setex(_cache_key(server_id), _CACHE_TTL_SEC, json.dumps(values))
    except Exception:
        pass


def invalidate_cached_current(server_id: int) -> None:
    try:
        _redis().delete(_cache_key(server_id))
    except Exception:
        pass


def get_current_values(
    session: Session,
    server: TargetServer,
    keys: list[str] | None = None,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    """
    refresh=False: cache varsa dön; yoksa SSH + cache yaz.
    refresh=True: SSH zorunlu + cache güncelle.
    """
    key_list = list(keys) if keys else list(PRESET_PARAMS)
    sid = int(server.id)  # type: ignore[arg-type]
    if not refresh:
        cached = get_cached_current(sid)
        if cached is not None:
            # İstenen key'ler cache'te varsa kullan; eksik key varsa canlı oku
            if all(k in cached for k in key_list):
                return {
                    "values": {k: cached.get(k, "") for k in key_list},
                    "cached": True,
                    "server_id": sid,
                }
    values = read_current(session, server, key_list)
    # Cache'i preset tamamıyla birleştir (kısmi okumada diğerleri kaybolmasın)
    merged = dict(get_cached_current(sid) or {})
    merged.update(values)
    set_cached_current(sid, merged)
    return {"values": values, "cached": False, "server_id": sid}


def build_plans(session: Session, action: str, servers: list[TargetServer], payload: dict[str, Any]) -> list[HostPlan]:
    plans: list[HostPlan] = []
    for server in servers:
        try:
            if action != "set":
                raise ValueError(f"Bilinmeyen aksiyon: {action}")
            params = _resolve_params(payload)
            _assert_params_exist(session, server, list(params.keys()))
            before = read_current(session, server, list(params.keys()))
            lines = [f"{k} = {v}" for k, v in params.items()]
            diffs = [f"{k}: {before.get(k) or '?'} → {v}" for k, v in params.items()]
            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=True,
                    summary_tr=f"{server.hostname}: {', '.join(diffs)}",
                    planned_commands=[
                        "comment matching keys in /etc/sysctl.conf and /etc/sysctl.d/*.conf (bak)",
                        f"write {CONF_FILE} (eski aynı key satırları # ile yorumlanır)",
                        f"sysctl -p {CONF_FILE}",
                        *[f"sysctl -n {k}" for k in params],
                    ],
                    before_state={
                        "params": params,
                        "current": before,
                        "conf_file": CONF_FILE,
                        "lines": lines,
                    },
                    risk_notes=(
                        "Portal conf yazılacak; aynı key’ler /etc/sysctl.conf ve diğer "
                        "/etc/sysctl.d/*.conf dosyalarında # ile yorumlanacak (yedek .bak); "
                        "sysctl -p ile anlık yüklenecek."
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
    params: dict[str, str] = plan.before_state.get("params") or {}
    conf = plan.before_state.get("conf_file") or CONF_FILE
    try:
        _assert_params_exist(session, server, list(params.keys()))
    except ValueError as exc:
        return False, plan.before_state, "", str(exc)

    # 1) Diğer /etc conf’larda aynı key’leri # yap (reboot’ta override olmasın)
    # 2) Portal conf’ta eski key’leri # yap + yeni satır ekle
    # 3) sysctl -p portal conf
    body_lines = "\n".join(f"{k} = {v}" for k, v in params.items())
    keys_joined = " ".join(params.keys())
    script = f"""
set -e
CONF={shlex.quote(conf)}
KEYS={shlex.quote(keys_joined)}
comment_keys() {{
  local f="$1"
  [ -f "$f" ] || return 0
  local TMP
  TMP=$(mktemp)
  awk -v keys="$KEYS" '
BEGIN {{ n=split(keys,a," "); for(i=1;i<=n;i++) skip[a[i]]=1 }}
{{
  raw=$0
  line=$0
  sub(/^[ \\t]+/,"",line)
  if (line == "") {{ print raw; next }}
  if (line ~ /^#/) {{ print raw; next }}
  split(line, p, /=/)
  k=p[1]; gsub(/[ \\t]+/, "", k)
  if (k in skip) {{
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
# /etc/sysctl.conf + /etc/sysctl.d/*.conf (portal conf hariç)
if [ -f /etc/sysctl.conf ]; then
  comment_keys /etc/sysctl.conf
fi
for f in /etc/sysctl.d/*.conf; do
  [ -f "$f" ] || continue
  [ "$f" = "$CONF" ] && continue
  comment_keys "$f"
done
echo COMMENT_PASS_END

mkdir -p "$(dirname "$CONF")"
if [ -f "$CONF" ]; then cp -a "$CONF" "$CONF.bak.$(date +%s)"; fi
touch "$CONF"
TMP=$(mktemp)
awk -v keys="$KEYS" '
BEGIN {{ n=split(keys,a," "); for(i=1;i<=n;i++) skip[a[i]]=1 }}
{{
  raw=$0
  line=$0
  sub(/^[ \\t]+/,"",line)
  if (line == "") {{ print raw; next }}
  if (line ~ /^#/) {{ print raw; next }}
  split(line, p, /=/)
  k=p[1]; gsub(/[ \\t]+/, "", k)
  if (k in skip) {{
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
sysctl -p "$CONF" >/tmp/dropt-sysctl.out 2>&1 || sysctl --system >/tmp/dropt-sysctl.out 2>&1
echo VERIFY_BEGIN
"""
    for k in params:
        script += f"sysctl -n {shlex.quote(k)} 2>/dev/null || echo FAIL\n"
    script += f"""echo VERIFY_END
cat /tmp/dropt-sysctl.out 2>/dev/null | tail -n 30
echo CONF_BEGIN
cat {shlex.quote(conf)}
echo CONF_END
"""
    r = run_ssh(session, server, script, timeout=90)
    # Tek SSH: uygulanan + preset değerleri (cache + doğrulama)
    sid = int(server.id)  # type: ignore[arg-type]
    keys_for_read = list(dict.fromkeys([*PRESET_PARAMS, *params.keys()]))
    snapshot = read_current(session, server, keys_for_read)
    after_vals = {k: snapshot.get(k, "") for k in params}
    ok = r.ok and all(
        re.sub(r"\s+", " ", (after_vals.get(k) or "").strip())
        == re.sub(r"\s+", " ", v.strip())
        for k, v in params.items()
    )
    invalidate_cached_current(sid)
    if ok:
        set_cached_current(sid, {k: snapshot.get(k, "") for k in PRESET_PARAMS} | after_vals)
    after = {
        **plan.before_state,
        "after": after_vals,
        "checklist": [
            "sysctl -n ile değerleri doğrula",
            "COMMENTED: satırlarında /etc/sysctl.conf ve diğer conf’lar kontrol",
        ],
    }
    return ok, after, r.stdout, r.stderr
