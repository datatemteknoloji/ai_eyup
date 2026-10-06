"""Salt-okunur yapılandırma toplayıcıları.

Hepsi yönetim düzlemi API'sini kullanır (vCenter SOAP/REST, OLVM Manager REST,
kube API). ESXi / OLVM host / OCP node'a doğrudan bağlantı YOKTUR.

Ortak dönüş şekli:
    {"ok": bool, "error": str|None, "clusters": [...], "hosts": [...],
     "datastores": [...], "vms": [...], "platform": {...}, "files": [...]|None,
     "not_measurable": [..], "unsupported_paths": [...]}
"""


def as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def as_bool(v):
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "on", "enabled"):
        return True
    if s in ("false", "0", "no", "off", "disabled"):
        return False
    return None
