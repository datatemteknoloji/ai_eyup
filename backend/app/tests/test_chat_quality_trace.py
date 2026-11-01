"""chat_quality: maskeleme, iz, bayrak yetkilendirme, saat, TracedResults."""
import json
from datetime import datetime

import pytest

from app.services.chat_quality import clock, trace
from app.services.chat_quality.masking import MASK, mask_obj, mask_text

JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk123"


# ── maskeleme ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,leak", [
    (f"Authorization: Bearer {JWT}", JWT),
    (f"token {JWT}", JWT),
    ("Bearer abcdefghijklmnop1234567890", "abcdefghijklmnop1234567890"),
    ("-----BEGIN RSA PRIVATE KEY-----\nMIIEabc\n-----END RSA PRIVATE KEY-----", "MIIEabc"),
    ("-----BEGIN PRIVATE KEY-----\nMIIEtruncated-no-end", "MIIEtruncated"),
    ("postgres://admin:S3cretPw@db:5432/x", "S3cretPw"),
    ("password=hunter2 ok", "hunter2"),
    ("api_key: abc123def456", "abc123def456"),
    ("key sk-abcdefghijklmnopqrstuvwx", "sk-abcdefghijklmnopqrstuvwx"),
    ("AKIAABCDEFGHIJKLMNOP", "AKIAABCDEFGHIJKLMNOP"),
])
def test_mask_text_patterns(text, leak):
    assert leak not in mask_text(text)


def test_mask_text_keeps_normal_prose():
    s = "3 küme, 18 node; tokens kullanımı normal; secret sayısı 4"
    assert mask_text(s) == s


def test_mask_keys_and_nested():
    obj = {
        "name": "vm1",
        "password": "p1",
        "api_key": "k1",
        "nested": {"access_token": "t1", "ok": 1},
        "secret_name": "my-secret",  # ad alanı sır değil
        "token_count": 5,
        "items": [{"client_secret": "cs"}],
    }
    out = mask_obj(obj)
    assert out["password"] == MASK and out["api_key"] == MASK
    assert out["nested"]["access_token"] == MASK and out["nested"]["ok"] == 1
    assert out["secret_name"] == "my-secret" and out["token_count"] == 5
    assert out["items"][0]["client_secret"] == MASK
    assert obj["password"] == "p1"  # girdi değişmez


def test_mask_k8s_secret_data_and_noise():
    sec = {
        "kind": "Secret",
        "metadata": {
            "name": "s", "managedFields": [{"x": 1}],
            "annotations": {"kubectl.kubernetes.io/last-applied-configuration": "{...}", "a": "b"},
        },
        "data": {"tls.key": "QUJD", "user": "YWRtaW4="},
        "stringData": {"p": "plain"},
    }
    out = mask_obj(sec)
    assert out["data"] == {"tls.key": MASK, "user": MASK}
    assert out["stringData"] == {"p": MASK}
    assert "managedFields" not in out["metadata"]
    assert out["metadata"]["annotations"] == {"a": "b"}


def test_mask_kubeconfig_data_keys_and_dockerconfig():
    out = mask_obj({
        "client-key-data": "AAA", "certificate-authority-data": "BBB",
        ".dockerconfigjson": "CCC", "server": "https://x:6443",
    })
    assert out["client-key-data"] == MASK
    assert out["certificate-authority-data"] == MASK
    assert out[".dockerconfigjson"] == MASK
    assert out["server"] == "https://x:6443"


def test_mask_env_list_by_name():
    out = mask_obj([{"name": "DB_PASSWORD", "value": "x"}, {"name": "REGION", "value": "eu"}])
    assert out[0]["value"] == MASK and out[1]["value"] == "eu"


# ── bayrak yetkilendirme ───────────────────────────────────────────────────
def test_flags_default_off():
    assert trace.resolve_flags({}, "admin") == (False, None, [])


@pytest.mark.parametrize("role", ["admin", "superadmin"])
def test_flags_admin_enabled(role):
    dbg, now, ign = trace.resolve_flags(
        {"debug_trace": True, "now_override": "2026-10-14T10:00:00"}, role)
    assert dbg and now == datetime(2026, 10, 14, 10, 0, 0) and ign == []


@pytest.mark.parametrize("role", ["operator", "viewer", None, ""])
def test_flags_non_admin_ignored(role):
    dbg, now, ign = trace.resolve_flags(
        {"debug_trace": True, "now_override": "2026-10-14T10:00:00"}, role)
    assert not dbg and now is None
    assert set(ign) == {"debug_trace", "now_override"}


def test_now_override_requires_debug_flag():
    dbg, now, ign = trace.resolve_flags({"now_override": "2026-10-14T10:00:00"}, "admin")
    assert not dbg and now is None and ign == ["now_override"]


def test_now_override_invalid():
    dbg, now, ign = trace.resolve_flags({"debug_trace": True, "now_override": "yarın"}, "admin")
    assert dbg and now is None and ign == ["now_override_invalid"]


def test_now_override_tz_aware_becomes_naive():
    assert trace.parse_now_override("2026-10-14T10:00:00Z").tzinfo is None


# ── iz + saat ───────────────────────────────────────────────────────────
def test_noop_when_unbound():
    assert trace.current() is None
    trace.note_tool("x", {}, {})
    trace.note_path("p")
    assert isinstance(clock.now(), datetime)


def test_traced_results_records_when_bound_and_acts_like_list():
    t = trace.TurnTrace(turn_id="t1", platform="admin", debug_enabled=True)
    tok = trace.bind(t)
    try:
        res = trace.TracedResults()
        res.append({"tool": "vm_count", "args": {"a": 1}, "result": {"n": 3}})
        res.append({"foo": "bar"})
        assert len(res) == 2 and list(res)[0]["tool"] == "vm_count"
    finally:
        trace.unbind(tok)
    assert t.tool_names() == ["vm_count"]
    assert trace.current() is None


def test_traced_results_unbound_does_not_fail():
    res = trace.TracedResults()
    res.append({"tool": "x", "args": {}, "result": 1})
    assert len(res) == 1


def test_clock_uses_override_only_when_bound():
    t = trace.TurnTrace(now_override=datetime(2026, 1, 2, 3, 4, 5))
    tok = trace.bind(t)
    try:
        assert clock.now() == datetime(2026, 1, 2, 3, 4, 5)
    finally:
        trace.unbind(tok)
    assert clock.now().year >= 2026 and clock.now() != datetime(2026, 1, 2, 3, 4, 5)


def test_note_chunk_ignores_tokens_and_records_flags():
    t = trace.TurnTrace()
    t.note_chunk({"token": "abc"})
    t.note_chunk({"phase": "collecting"})
    t.note_chunk({"type": "tool_call", "tool": "x"})
    t.note_chunk({"done": True, "from_cache": True})
    assert t.event_types == {"collecting": 1, "tool_call": 1}
    assert t.flags == {"from_cache": True}


def test_debug_dict_masks_results_and_answer():
    t = trace.TurnTrace(turn_id="t", platform="openshift", debug_enabled=True)
    t.note_tool("get_secret", {"password": "x"}, {"kind": "Secret", "data": {"k": "QUJD"}})
    t.note_path("qa_rule", handler="h")
    d = t.to_debug_dict(answer=f"token {JWT}")
    raw = json.dumps(d, ensure_ascii=False)
    assert "QUJD" not in raw and JWT not in raw
    assert d["tools"][0]["args"]["password"] == MASK
    assert d["paths"][0]["handler"] == "h" and d["answer_chars"] > 0


def test_debug_dict_size_capped():
    t = trace.TurnTrace()
    for i in range(trace.MAX_TOOLS + 20):
        t.note_tool(f"t{i}", {}, {"rows": ["x" * 50] * 5000})
    d = t.to_debug_dict()
    assert len(t.tools) == trace.MAX_TOOLS
    assert len(json.dumps(d, ensure_ascii=False).encode()) <= trace.MAX_EVENT_BYTES
    assert d["truncated"] is True
