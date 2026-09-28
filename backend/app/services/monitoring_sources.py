"""
Multi-source monitoring registry.

Kaynaklar AppSettings `monitoring_prometheus_sources` JSON listesinde tutulur.
Her kayıt: id, label, url, token (şifreli), binding (linux|openshift|virtualization|none),
collector_type (prometheus|telegraf|opentelemetry|zabbix), isteğe bağlı username/password.

Geriye uyum: registry boşsa settings.PROMETHEUS_URL → binding=linux seed.
collector_type yoksa prometheus sayılır. Modül binding’lerinde collector her zaman prometheus.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

Binding = Literal["linux", "openshift", "virtualization", "none"]
VALID_BINDINGS = frozenset({"linux", "openshift", "virtualization", "none"})

CollectorType = Literal["prometheus", "telegraf", "opentelemetry", "zabbix"]
VALID_COLLECTORS = frozenset({"prometheus", "telegraf", "opentelemetry", "zabbix"})
PROM_COMPATIBLE = frozenset({"prometheus", "telegraf", "opentelemetry"})

SETTINGS_KEY = "monitoring_prometheus_sources"
LINUX_SEED_ID = "linux-default"

_URL_RE = re.compile(r"^https?://", re.I)
_SAFE_METRIC_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")


@dataclass
class MonitoringSource:
    id: str
    label: str
    url: str
    binding: Binding
    token: str = ""
    token_set: bool = False
    collector_type: CollectorType = "prometheus"
    username: str = ""
    password: str = ""
    password_set: bool = False
    verify_ssl: bool = True
    # Prom uyumlu kaynaklar: scrape job adları + isteğe bağlı ek label seçiciler
    # (örn. cluster="prod"). OCP Views panellerine enjekte edilmez; explorer/chat kullanır.
    jobs: List[str] = field(default_factory=list)
    extra_selectors: str = ""

    def public_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "url": self.url,
            "binding": self.binding,
            "token_set": bool(self.token) or self.token_set,
            "collector_type": self.collector_type,
            "username": self.username or "",
            "password_set": bool(self.password) or self.password_set,
            "verify_ssl": bool(self.verify_ssl),
            "prom_compatible": is_prom_compatible(self),
            "jobs": list(self.jobs or []),
            "extra_selectors": self.extra_selectors or "",
        }


def normalize_label(label: str) -> str:
    s = (label or "").strip().lower()
    s = re.sub(r"[\s_\-]+", " ", s)
    return s.strip()


def validate_label(label: str) -> Optional[str]:
    """Geçersizse hata mesajı, geçerliyse None."""
    raw = (label or "").strip()
    if not raw:
        return "Label zorunludur"
    norm = normalize_label(raw)
    words = [w for w in norm.split(" ") if w]
    if len(norm) < 6 and len(words) < 2:
        return "Label en az 6 karakter veya en az 2 kelime olmalı"
    if norm in {"prod", "gpu", "ocp", "lab", "dev", "test", "prom", "other"}:
        return "Label çok genel; daha açıklayıcı bir ad kullanın"
    return None


def validate_url(url: str) -> Optional[str]:
    u = (url or "").strip().rstrip("/")
    if not u:
        return "URL zorunludur"
    if not _URL_RE.match(u):
        return "URL http:// veya https:// ile başlamalı"
    return None


def normalize_collector_type(
    raw: Optional[str],
    binding: str = "none",
) -> CollectorType:
    ct = (raw or "prometheus").strip().lower()
    if ct not in VALID_COLLECTORS:
        ct = "prometheus"
    # Modüle bağlı kaynaklar her zaman Prometheus HTTP API
    if (binding or "").strip().lower() != "none":
        return "prometheus"
    return ct  # type: ignore[return-value]


def normalize_jobs(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = re.split(r"[,;\s]+", raw.strip())
        return [p for p in (x.strip() for x in parts) if p]
    if isinstance(raw, (list, tuple)):
        out: List[str] = []
        for x in raw:
            s = str(x or "").strip()
            if s and s not in out:
                out.append(s)
        return out
    return []


def validate_extra_selectors(raw: Optional[str]) -> Optional[str]:
    """Geçersizse hata; boş/OK → None. Süslü parantez yok; yalnız a=\"b\",c=~\"d\"."""
    s = (raw or "").strip().strip(",")
    if not s:
        return None
    if len(s) > 400:
        return "Ek label seçicileri çok uzun"
    if "{" in s or "}" in s:
        return "Süslü parantez yazmayın (örn. cluster=\"prod\")"
    if any(c in s for c in (";", "`", "$", "\n", "\r")):
        return "Ek seçicilerde geçersiz karakter"
    return None


def job_matcher(jobs: Optional[Sequence[str]]) -> str:
    """PromQL job seçici parçası; boş liste → \"\"."""
    cleaned = [j.strip() for j in (jobs or []) if j and str(j).strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        j = cleaned[0].replace("\\", "\\\\").replace('"', '\\"')
        return f'job="{j}"'
    pattern = "|".join(re.escape(j) for j in cleaned)
    return f'job=~"{pattern}"'


def source_label_matchers(source: MonitoringSource) -> str:
    """job + extra_selectors birleşik PromQL label body (süslü parantezsiz)."""
    parts: List[str] = []
    jm = job_matcher(source.jobs)
    if jm:
        parts.append(jm)
    extra = (source.extra_selectors or "").strip().strip(",")
    if extra:
        parts.append(extra)
    return ",".join(parts)


def apply_source_matchers(expr: str, source: MonitoringSource) -> str:
    """Metrik adı veya basit selector’a kaynak job/extra ekle."""
    m = source_label_matchers(source)
    if not m:
        return expr
    expr = (expr or "").strip()
    if not expr:
        return expr
    if _SAFE_METRIC_NAME.match(expr):
        return f"{expr}{{{m}}}"
    brace = expr.find("{")
    if brace >= 0:
        close = expr.find("}", brace)
        if close > brace:
            inner = expr[brace + 1 : close].strip()
            merged = m if not inner else f"{inner},{m}"
            return expr[: brace + 1] + merged + expr[close:]
    return expr


def is_prom_compatible(source: MonitoringSource) -> bool:
    ct = normalize_collector_type(source.collector_type, source.binding)
    return ct in PROM_COMPATIBLE


def _decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        from app.core.encryption import decrypt_secret
        return decrypt_secret(value) or ""
    except Exception:
        return value


def _encrypt(value: str) -> str:
    if not value:
        return ""
    try:
        from app.core.encryption import encrypt_secret
        return encrypt_secret(value) or value
    except Exception:
        return value


def _linux_seed_from_settings() -> MonitoringSource:
    from app.core.config import settings
    url = (getattr(settings, "PROMETHEUS_URL", None) or "http://prometheus:9090").rstrip("/")
    return MonitoringSource(
        id=LINUX_SEED_ID,
        label="Linux Prometheus",
        url=url,
        binding="linux",
        token="",
        token_set=False,
        collector_type="prometheus",
    )


def _parse_raw_list(raw: Optional[str]) -> List[Dict[str, Any]]:
    if not raw or not str(raw).strip():
        return []
    try:
        data = json.loads(raw)
    except Exception:
        logger.warning("monitoring_prometheus_sources JSON parse hatası")
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def _from_item(item: Dict[str, Any]) -> Optional[MonitoringSource]:
    sid = str(item.get("id") or "").strip() or str(uuid.uuid4())
    label = str(item.get("label") or "").strip()
    url = str(item.get("url") or "").strip().rstrip("/")
    binding = str(item.get("binding") or "none").strip().lower()
    if binding not in VALID_BINDINGS:
        binding = "none"
    collector_type = normalize_collector_type(item.get("collector_type"), binding)
    token_enc = str(item.get("token") or "")
    token = _decrypt(token_enc) if token_enc else ""
    password_enc = str(item.get("password") or "")
    password = _decrypt(password_enc) if password_enc else ""
    username = str(item.get("username") or "").strip()
    verify_ssl = item.get("verify_ssl")
    if verify_ssl is None:
        verify_ssl = True
    if not label or not url:
        return None
    jobs = normalize_jobs(item.get("jobs"))
    extra = str(item.get("extra_selectors") or "").strip()
    return MonitoringSource(
        id=sid,
        label=label,
        url=url,
        binding=binding,  # type: ignore[arg-type]
        token=token,
        token_set=bool(token_enc),
        collector_type=collector_type,
        username=username,
        password=password,
        password_set=bool(password_enc),
        verify_ssl=bool(verify_ssl),
        jobs=jobs,
        extra_selectors=extra,
    )


def load_sources_from_db(db) -> List[MonitoringSource]:
    """DB + linux seed birleşimi. Token/password çözülmüş halde."""
    from app.models.app_settings import AppSettings

    row = db.query(AppSettings).filter(AppSettings.key == SETTINGS_KEY).first()
    raw_items = _parse_raw_list(row.value if row else None)
    out: List[MonitoringSource] = []
    seen_ids = set()
    for item in raw_items:
        src = _from_item(item)
        if not src:
            continue
        out.append(src)
        seen_ids.add(src.id)

    has_linux = any(s.binding == "linux" for s in out)
    if not has_linux:
        seed = _linux_seed_from_settings()
        if seed.id not in seen_ids:
            out.insert(0, seed)
    return out


def load_sources_runtime() -> List[MonitoringSource]:
    """Session açıp kaynakları yükle (chat/proxy)."""
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        return load_sources_from_db(db)
    finally:
        db.close()


def list_by_binding(sources: Sequence[MonitoringSource], binding: Binding) -> List[MonitoringSource]:
    return [s for s in sources if s.binding == binding]


def list_custom(sources: Sequence[MonitoringSource]) -> List[MonitoringSource]:
    return list_by_binding(sources, "none")


def resolve(
    sources: Sequence[MonitoringSource],
    *,
    source_id: Optional[str] = None,
    module: Optional[str] = None,
) -> Optional[MonitoringSource]:
    """source_id öncelikli; yoksa module/binding’in ilk kaynağı; default linux."""
    if source_id:
        sid = source_id
        if sid.startswith("custom:"):
            sid = sid.split(":", 1)[1]
        for s in sources:
            if s.id == sid:
                return s
        return None
    mod = (module or "linux").strip().lower()
    if mod in ("openshift", "ocp"):
        binding: Binding = "openshift"
    elif mod in ("virtualization", "virt", "vmware"):
        binding = "virtualization"
    elif mod in ("none", "other", "custom"):
        binding = "none"
    else:
        binding = "linux"
    matched = list_by_binding(sources, binding)
    if matched:
        return matched[0]
    if binding == "linux":
        return _linux_seed_from_settings()
    return None


def is_prometheus_configured(sources: Sequence[MonitoringSource], binding: Binding) -> bool:
    if binding == "none":
        return bool(list_custom(sources))
    return bool(list_by_binding(sources, binding))


def default_ui_mode(sources: Sequence[MonitoringSource], binding: Binding) -> Literal["api", "prometheus"]:
    if binding == "linux":
        return "prometheus"
    if is_prometheus_configured(sources, binding):
        return "prometheus"
    return "api"


def match_custom_label(message: str, sources: Sequence[MonitoringSource]) -> List[MonitoringSource]:
    """Mesajda kayıtlı Other label’ının normalize tam ifadesi geçiyorsa eşleşenler."""
    msg_norm = normalize_label(message or "")
    if not msg_norm:
        return []
    hits: List[MonitoringSource] = []
    for s in list_custom(sources):
        lab = normalize_label(s.label)
        if not lab:
            continue
        if lab in msg_norm:
            hits.append(s)
    return hits


def sources_to_storage(sources: Sequence[MonitoringSource], *, keep_tokens: Optional[Dict[str, str]] = None) -> str:
    """DB’ye yazılacak JSON. Token/password şifreli."""
    keep = keep_tokens or {}
    rows = []
    for s in sources:
        token_plain = s.token if s.token else keep.get(s.id, "")
        password_plain = s.password or ""
        rows.append(
            {
                "id": s.id,
                "label": s.label.strip(),
                "url": s.url.strip().rstrip("/"),
                "binding": s.binding,
                "collector_type": normalize_collector_type(s.collector_type, s.binding),
                "token": _encrypt(token_plain) if token_plain else "",
                "username": (s.username or "").strip(),
                "password": _encrypt(password_plain) if password_plain else "",
                "verify_ssl": bool(s.verify_ssl),
                "jobs": list(s.jobs or []),
                "extra_selectors": (s.extra_selectors or "").strip(),
            }
        )
    return json.dumps(rows, ensure_ascii=False)


def validate_sources_payload(items: Sequence[Dict[str, Any]]) -> Tuple[List[MonitoringSource], List[str]]:
    """PUT body doğrula. Dönüş: (kaynaklar, uyarılar). Hata → ValueError."""
    warnings: List[str] = []
    out: List[MonitoringSource] = []
    norms: Dict[str, str] = {}
    urls_seen: Dict[str, str] = {}

    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Her kaynak bir nesne olmalı")
        label = str(item.get("label") or "").strip()
        err = validate_label(label)
        if err:
            raise ValueError(f"{label or '?'}: {err}")
        url = str(item.get("url") or "").strip().rstrip("/")
        err_u = validate_url(url)
        if err_u:
            raise ValueError(f"{label}: {err_u}")
        binding = str(item.get("binding") or "none").strip().lower()
        if binding not in VALID_BINDINGS:
            raise ValueError(f"{label}: geçersiz binding")
        collector_type = normalize_collector_type(item.get("collector_type"), binding)
        if binding == "none" and collector_type == "zabbix":
            pass
        sid = str(item.get("id") or "").strip() or str(uuid.uuid4())
        norm = normalize_label(label)
        if norm in norms:
            raise ValueError(f"Label çakışması: '{label}' ≈ '{norms[norm]}'")
        norms[norm] = label
        if url in urls_seen:
            warnings.append(f"Aynı URL birden fazla kayıtta: {url} ({urls_seen[url]} ve {label})")
        else:
            urls_seen[url] = label
        token = str(item.get("token") or "")
        username = str(item.get("username") or "").strip()
        password = str(item.get("password") or "")
        verify_ssl = item.get("verify_ssl")
        if verify_ssl is None:
            verify_ssl = True
        jobs = normalize_jobs(item.get("jobs"))
        extra = str(item.get("extra_selectors") or "").strip()
        err_x = validate_extra_selectors(extra)
        if err_x:
            raise ValueError(f"{label}: {err_x}")
        # Zabbix'te job/extra anlamsız — yok say
        if collector_type == "zabbix":
            jobs = []
            extra = ""
        out.append(
            MonitoringSource(
                id=sid,
                label=label,
                url=url,
                binding=binding,  # type: ignore[arg-type]
                token=token,
                token_set=bool(token),
                collector_type=collector_type,
                username=username,
                password=password,
                password_set=bool(password),
                verify_ssl=bool(verify_ssl),
                jobs=jobs,
                extra_selectors=extra,
            )
        )
    return out, warnings


def sync_linux_url_to_settings(db, sources: Sequence[MonitoringSource]) -> None:
    """İlk linux binding URL’sini prometheus_url anahtarına yazar."""
    from app.models.app_settings import AppSettings
    from app.core.config import settings

    linux = list_by_binding(sources, "linux")
    if not linux:
        return
    url = linux[0].url
    row = db.query(AppSettings).filter(AppSettings.key == "prometheus_url").first()
    if row:
        row.value = url
    else:
        db.add(AppSettings(key="prometheus_url", value=url))
    settings.PROMETHEUS_URL = url


def save_sources(db, sources: Sequence[MonitoringSource], *, previous: Optional[Sequence[MonitoringSource]] = None) -> List[str]:
    """Registry kaydet; linux URL senkron; uyarı listesi döner."""
    from app.models.app_settings import AppSettings

    prev = {s.id: s for s in (previous or [])}
    merged: List[MonitoringSource] = []
    for s in sources:
        token = s.token
        password = s.password
        old = prev.get(s.id)
        if not token and old and old.token:
            token = old.token
        if not password and old and old.password:
            password = old.password
        merged.append(
            MonitoringSource(
                id=s.id,
                label=s.label,
                url=s.url,
                binding=s.binding,
                token=token,
                token_set=bool(token),
                collector_type=normalize_collector_type(s.collector_type, s.binding),
                username=s.username,
                password=password,
                password_set=bool(password),
                verify_ssl=s.verify_ssl,
                jobs=list(s.jobs or []),
                extra_selectors=(s.extra_selectors or "").strip(),
            )
        )

    payload = sources_to_storage(merged)
    row = db.query(AppSettings).filter(AppSettings.key == SETTINGS_KEY).first()
    if row:
        row.value = payload
    else:
        db.add(AppSettings(key=SETTINGS_KEY, value=payload))
    sync_linux_url_to_settings(db, merged)

    _, warnings = validate_sources_payload(
        [
            {
                "id": s.id,
                "label": s.label,
                "url": s.url,
                "binding": s.binding,
                "collector_type": s.collector_type,
                "token": "",
            }
            for s in merged
        ]
    )
    return warnings


def prom_headers(source: Optional[MonitoringSource]) -> Dict[str, str]:
    if source and source.token:
        return {"Authorization": f"Bearer {source.token}"}
    return {}


def prom_base_url(source: Optional[MonitoringSource]) -> str:
    if source and source.url:
        return source.url.rstrip("/")
    from app.core.config import settings
    return (settings.PROMETHEUS_URL or "http://prometheus:9090").rstrip("/")


def zabbix_api_url(source: MonitoringSource) -> str:
    """Zabbix JSON-RPC uç noktası."""
    base = (source.url or "").rstrip("/")
    if base.endswith("api_jsonrpc.php"):
        return base
    return f"{base}/api_jsonrpc.php"
