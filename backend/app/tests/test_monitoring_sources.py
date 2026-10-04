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
