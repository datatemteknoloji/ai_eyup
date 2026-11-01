"""IH5 bulgusu: db_list_vms kesilince «Toplam: 500 VM» yerine gerçek toplam + dağılım yazılmalı."""
from app.services import virt_inventory_contract as vic


def _vms(n):
    return [{"name": f"vm-{i:04d}", "hypervisor": "office"} for i in range(n)]


def _payload(shown, total, truncated=True, bd=None):
    return {"ok": True, "vms": _vms(shown), "count": shown, "total_matching": total, "truncated": truncated,
            "hypervisor_breakdown": bd or [{"hypervisor": "ZZ-FAKE-vCenter", "count": 1000}, {"hypervisor": "office", "count": 29}],
            "as_of": "2026-10-15T00:00:00+03:00"}


def _render(payload):
    return vic.materialize_from_tool_results(
        vic.KIND_VM_LIST, [{"tool": "db_list_vms", "result": payload}], fields=["name"],
    )


def test_truncated_list_states_real_total_and_breakdown():
    out = _render(_payload(500, 1552))
    assert "**Toplam:** 500 VM" not in out
    assert "**Gösterilen:** 500 VM" in out and "**Kapsamdaki toplam:** 1552 VM" in out and "KESİLDİ" in out
    assert "ZZ-FAKE-vCenter: 1000" in out and "office: 29" in out
    assert "daraltın" in out


def test_not_truncated_keeps_old_total_line():
    out = _render(_payload(29, 29, truncated=False, bd=[]))
    assert "**Toplam:** 29 VM" in out and "KESİLDİ" not in out


def test_old_payload_without_new_keys_unchanged():
    p = {"ok": True, "vms": _vms(3), "count": 3, "as_of": None}
    out = _render(p)
    assert "**Toplam:** 3 VM" in out
