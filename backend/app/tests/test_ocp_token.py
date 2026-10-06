from app.services.monitoring_sources import MonitoringSource, prom_headers
from app.services.openshift import ocp_token as ot


def _src(token, binding="openshift"):
    return MonitoringSource(id="s", label="s", url="https://thanos-querier.apps.ocp.x.local",
                            binding=binding, token=token, collector_type="prometheus", verify_ssl=False)


def setup_function(_):
    ot.invalidate_cache()


def test_non_expirable_token_untouched(monkeypatch):
    monkeypatch.setattr(ot, "_load_clusters", lambda: (_ for _ in ()).throw(AssertionError("no db")))
    assert ot.resolve_token("eyJabc", "https://x") == "eyJabc"


def test_expired_token_replaced_and_cached(monkeypatch):
    calls = {"mint": 0}
    monkeypatch.setattr(ot, "_load_clusters", lambda: [(1, "https://api.ocp.x.local:6443", {"username": "u", "password": "p"})])
    monkeypatch.setattr(ot, "_probe", lambda api, tok, verify: tok == "sha256~good")
    def mint(api, cfg):
        calls["mint"] += 1
        return "sha256~fresh"
    monkeypatch.setattr(ot, "_mint", mint)
    assert ot.resolve_token("sha256~old", "https://thanos.apps.ocp.x.local") == "sha256~fresh"
    assert ot.resolve_token("sha256~old", "https://thanos.apps.ocp.x.local") == "sha256~fresh"
    assert calls["mint"] == 1


def test_valid_token_kept(monkeypatch):
    monkeypatch.setattr(ot, "_load_clusters", lambda: [(1, "https://api.ocp.x.local:6443", {})])
    monkeypatch.setattr(ot, "_probe", lambda *a: True)
    assert ot.resolve_token("sha256~good", "https://t") == "sha256~good"


def test_probe_unknown_or_mint_fail_falls_back(monkeypatch):
    monkeypatch.setattr(ot, "_load_clusters", lambda: [(1, "https://api.ocp.x.local:6443", {})])
    monkeypatch.setattr(ot, "_probe", lambda *a: None)
    assert ot.resolve_token("sha256~old", "https://t") == "sha256~old"
    ot.invalidate_cache()
    monkeypatch.setattr(ot, "_probe", lambda *a: False)
    monkeypatch.setattr(ot, "_mint", lambda *a: None)
    assert ot.resolve_token("sha256~old", "https://t") == "sha256~old"


def test_prom_headers_only_openshift(monkeypatch):
    monkeypatch.setattr(ot, "resolve_token", lambda t, u: "sha256~fresh")
    assert prom_headers(_src("sha256~old"))["Authorization"] == "Bearer sha256~fresh"
    assert prom_headers(_src("sha256~old"), auto_refresh=False)["Authorization"] == "Bearer sha256~old"
    assert prom_headers(_src("sha256~old", binding="linux"))["Authorization"] == "Bearer sha256~old"
