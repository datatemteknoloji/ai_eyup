"""monitoring_sources registry + label match tests."""
from app.services.monitoring_sources import (
    normalize_label,
    validate_label,
    validate_url,
    match_custom_label,
    MonitoringSource,
    validate_sources_payload,
    resolve,
    default_ui_mode,
    LINUX_SEED_ID,
)


def test_normalize_label():
    assert normalize_label("DC GPU Lab") == "dc gpu lab"
    assert normalize_label("dc-gpu-lab") == "dc gpu lab"
    assert normalize_label("  DC_GPU__Lab ") == "dc gpu lab"


def test_validate_label_rejects_short():
    assert validate_label("gpu") is not None
    assert validate_label("prod") is not None
    assert validate_label("DC GPU Lab") is None
    assert validate_label("abcdef") is None  # 6 chars


def test_validate_url():
    assert validate_url("http://prom:9090") is None
    assert validate_url("ftp://x") is not None
    assert validate_url("") is not None


def test_match_custom_label_full_only():
    sources = [
        MonitoringSource(id="1", label="DC GPU Lab", url="http://a", binding="none"),
        MonitoringSource(id="2", label="Linux Prometheus", url="http://b", binding="linux"),
    ]
    assert match_custom_label("gpu sıcaklığı", sources) == []
    hits = match_custom_label("DC GPU Lab sıcaklıkları nedir?", sources)
    assert len(hits) == 1 and hits[0].id == "1"
    hits2 = match_custom_label("dc-gpu-lab util", sources)
    assert len(hits2) == 1


def test_match_custom_label_collision():
    sources = [
        MonitoringSource(id="1", label="DC GPU Lab", url="http://a", binding="none"),
        MonitoringSource(id="2", label="DC GPU Lab East", url="http://b", binding="none"),
    ]
    # "dc gpu lab" is substring of both normalize strings
    hits = match_custom_label("check DC GPU Lab East please", sources)
    assert len(hits) >= 1
    # shorter label also matches if contained
    hits2 = match_custom_label("DC GPU Lab only", sources)
    assert any(h.id == "1" for h in hits2)


def test_validate_sources_unique_label():
    try:
        validate_sources_payload([
            {"label": "DC GPU Lab", "url": "http://a:9090", "binding": "none"},
            {"label": "dc-gpu-lab", "url": "http://b:9090", "binding": "none"},
        ])
        assert False, "expected ValueError"
    except ValueError as e:
        assert "çakışma" in str(e).lower() or "Label" in str(e)


def test_resolve_windows_binding():
    sources = [
        MonitoringSource(id="w1", label="Windows Fleet Prom", url="http://win:9090", binding="windows"),
    ]
    assert resolve(sources, module="windows").id == "w1"
    assert default_ui_mode(sources, "windows") == "prometheus"
    assert default_ui_mode([], "windows") == "api"


def test_collector_type_defaults_and_prom_compat():
    from app.services.monitoring_sources import is_prom_compatible, normalize_collector_type
    assert normalize_collector_type("telegraf", "none") == "telegraf"
    assert normalize_collector_type("zabbix", "openshift") == "prometheus"  # module forced
    assert normalize_collector_type(None, "none") == "prometheus"
    s = MonitoringSource(
        id="1", label="Lab Telegraf East", url="http://a", binding="none", collector_type="telegraf",
    )
    assert is_prom_compatible(s)
    z = MonitoringSource(
        id="2", label="Lab Zabbix East", url="http://b", binding="none", collector_type="zabbix",
    )
    assert not is_prom_compatible(z)
    pub = z.public_dict()
    assert pub["collector_type"] == "zabbix"
    assert pub["prom_compatible"] is False


def test_validate_sources_accepts_zabbix_other():
    sources, _ = validate_sources_payload([
        {
            "label": "Lab Zabbix East",
            "url": "http://zabbix.example/api_jsonrpc.php",
            "binding": "none",
            "collector_type": "zabbix",
            "username": "Admin",
        },
    ])
    assert sources[0].collector_type == "zabbix"
    assert sources[0].username == "Admin"


def test_jobs_and_extra_selectors():
    from app.services.monitoring_sources import (
        job_matcher, source_label_matchers, apply_source_matchers, validate_extra_selectors,
    )
    assert job_matcher(["node-exporter"]) == 'job="node-exporter"'
    assert 'job=~"' in job_matcher(["a", "b"])
    assert validate_extra_selectors('cluster="prod"') is None
    assert validate_extra_selectors('{bad}') is not None
    s = MonitoringSource(
        id="1",
        label="Lab Telegraf East",
        url="http://a",
        binding="none",
        collector_type="telegraf",
        jobs=["telegraf"],
        extra_selectors='dc="lab"',
    )
    assert source_label_matchers(s) == 'job="telegraf",dc="lab"'
    assert apply_source_matchers("up", s) == 'up{job="telegraf",dc="lab"}'
    assert apply_source_matchers('up{instance="x"}', s) == 'up{instance="x",job="telegraf",dc="lab"}'


# ── TLS doğrulama (verify_ssl) ──────────────────────────────────────────────

def test_default_verify_ssl_by_binding():
    from app.services.monitoring_sources import default_verify_ssl
    assert default_verify_ssl("openshift") is False
    assert default_verify_ssl("virtualization") is False
    assert default_verify_ssl("none") is True
    assert default_verify_ssl("windows") is True


def test_prom_verify_honors_flag_and_legacy_bindings():
    from app.services.monitoring_sources import prom_verify
    ocp_strict = MonitoringSource(id="o", label="OCP Thanos", url="https://t", binding="openshift", verify_ssl=True)
    ocp_lax = MonitoringSource(id="o", label="OCP Thanos", url="https://t", binding="openshift", verify_ssl=False)
    other = MonitoringSource(id="x", label="Other Prom", url="https://t", binding="none", verify_ssl=True)
    linux = MonitoringSource(id="l", label="Linux", url="https://t", binding="linux", verify_ssl=True)
    assert prom_verify(ocp_strict) is True
    assert prom_verify(ocp_lax) is False
    assert prom_verify(other) is True
    assert prom_verify(linux) is False  # UI anahtarı yok → eski lenient davranış
    assert prom_verify(None) is False


def test_legacy_openshift_source_without_explicit_marker_is_lenient():
    from app.services.monitoring_sources import _from_item
    legacy = {"id": "o", "label": "OCP Thanos", "url": "https://t", "binding": "openshift", "verify_ssl": True}
    assert _from_item(legacy).verify_ssl is False
    missing = {"id": "o", "label": "OCP Thanos", "url": "https://t", "binding": "openshift"}
    assert _from_item(missing).verify_ssl is False
    # Kullanıcı bilerek açtıysa (UI kaydı) aynen uygulanır
    explicit = dict(legacy, verify_ssl_explicit=True)
    assert _from_item(explicit).verify_ssl is True
    # Diğer bağlamalar etkilenmez
    other = {"id": "x", "label": "Other Prom", "url": "https://t", "binding": "none", "verify_ssl": True}
    assert _from_item(other).verify_ssl is True


def test_verify_ssl_roundtrip_storage_and_payload_default():
    import json
    from app.services.monitoring_sources import sources_to_storage, _from_item
    srcs, _ = validate_sources_payload([
        {"label": "OCP Thanos", "url": "https://t", "binding": "openshift"},
        {"label": "OCP Strict", "url": "https://s", "binding": "openshift", "verify_ssl": True},
    ])
    assert [s.verify_ssl for s in srcs] == [False, True]
    rows = json.loads(sources_to_storage(srcs))
    assert all(r["verify_ssl_explicit"] for r in rows)
    assert [_from_item(r).verify_ssl for r in rows] == [False, True]


def test_ocp_prom_queries_use_source_verify(monkeypatch):
    """Runtime sorguları kaynağın verify_ssl değerini httpx'e geçirmeli."""
    from app.services.openshift import ocp_prom_monitoring as m
    seen = []

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"status": "success", "data": []}

    class _Client:
        def __init__(self, *a, **kw): seen.append(kw.get("verify"))
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **kw): return _Resp()

    monkeypatch.setattr(m.httpx, "Client", _Client)
    for flag in (False, True):
        src = MonitoringSource(id="o", label="OCP Thanos", url="https://t", binding="openshift", verify_ssl=flag)
        m._query_prom(src, "up")
        m._query_range(src, "up", 0, 1)
        m._label_values(src, "namespace")
    assert seen == [False] * 3 + [True] * 3
