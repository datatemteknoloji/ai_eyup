"""KubeVirt CD-ROM / ISO yükleme servisi — sahte (in-memory) API ile."""
from __future__ import annotations

import asyncio
import copy
import json

import pytest

from app.services.openshift import kubevirt_media as m
from app.services.openshift import kubevirt_ops as ops


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.reason = "x"
        self.text = json.dumps(self._body)
        self.content = b"1"

    def json(self):
        return copy.deepcopy(self._body)


class _Session:
    def __init__(self, store):
        self.store = store
        self.headers = {"Authorization": "Bearer t"}
        self.patches = []
        self.posts = []

    def get(self, url, params=None, timeout=None):
        for suffix, handler in self.store["get"]:
            if url.endswith(suffix):
                return handler()
        return _Resp(404, {"message": "nf"})

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        h = self.store.get("post", {})
        for suffix, handler in h.items():
            if url.endswith(suffix):
                return handler(json)
        return _Resp(201, json or {})

    def patch(self, url, data=None, headers=None, timeout=None, json=None):
        self.patches.append((url, data, headers))
        body = __import__("json").loads(data)
        vm = self.store["vm"]
        assert body["metadata"]["resourceVersion"] == vm["metadata"]["resourceVersion"]
        vm["spec"]["template"] = body["spec"]["template"]
        return _Resp(200, vm)


class _Client:
    api_url = "https://api"
    timeout = 5

    def __init__(self, store):
        self.session = _Session(store)


def _vm(running=False):
    return {
        "metadata": {"name": "v1", "namespace": "ns1", "resourceVersion": "42"},
        "spec": {"template": {"spec": {
            "domain": {"devices": {"disks": [{"name": "root", "disk": {"bus": "virtio"}, "bootOrder": 1}]}},
            "volumes": [{"name": "root", "dataVolume": {"name": "root"}}],
        }}},
        "status": {"printableStatus": "Running" if running else "Stopped"},
    }


def _client(running=False, pvcs=None):
    vm = _vm(running)
    pvc = {
        "metadata": {"name": "win-iso", "namespace": "iso-lib"},
        "spec": {"accessModes": ["ReadWriteMany"], "resources": {"requests": {"storage": "6Gi"}},
                 "storageClassName": "ocs"},
        "status": {"capacity": {"storage": "6Gi"}, "phase": "Bound"},
    }
    store = {
        "vm": vm,
        "get": [
            ("/virtualmachines/v1", lambda: _Resp(200, store["vm"])),
            ("/persistentvolumeclaims/win-iso", lambda: _Resp(200, pvc)),
            ("/persistentvolumeclaims/local-iso", lambda: _Resp(200, {"metadata": {"name": "local-iso"}})),
        ],
    }
    return _Client(store), store


def test_attach_same_namespace_pvc():
    c, store = _client()
    r = m.attach_cdrom(c, "ns1", "v1", "ns1", "local-iso")
    assert r["mode"] == "attach" and r["restart_required"] is False
    spec = store["vm"]["spec"]["template"]["spec"]
    cd = [d for d in spec["domain"]["devices"]["disks"] if "cdrom" in d]
    assert cd and cd[0]["cdrom"]["bus"] == "sata"
    vol = [v for v in spec["volumes"] if v["name"] == cd[0]["name"]][0]
    assert vol["persistentVolumeClaim"] == {"claimName": "local-iso", "readOnly": True}
    # merge-patch ve eşzamanlılık kontrolü kullanıldı
    assert c.session.patches[0][2]["Content-Type"] == "application/merge-patch+json"


def test_attach_cross_namespace_creates_clone_datavolume():
    c, store = _client(running=True)
    r = m.attach_cdrom(c, "ns1", "v1", "iso-lib", "win-iso", boot_first=True)
    assert r["mode"] == "clone" and r["restart_required"] is True
    url, body = c.session.posts[0]
    assert url.endswith("/namespaces/ns1/datavolumes")
    assert body["spec"]["source"]["pvc"] == {"namespace": "iso-lib", "name": "win-iso"}
    assert body["spec"]["pvc"]["resources"]["requests"]["storage"] == "6Gi"
    assert body["spec"]["pvc"]["storageClassName"] == "ocs"
    spec = store["vm"]["spec"]["template"]["spec"]
    disks = {d["name"]: d for d in spec["domain"]["devices"]["disks"]}
    assert disks["root"]["bootOrder"] == 2  # mevcut disk kaydırıldı
    cd = [d for d in disks.values() if "cdrom" in d][0]
    assert cd["bootOrder"] == 1
    vol = [v for v in spec["volumes"] if v["name"] == cd["name"]][0]
    assert vol["dataVolume"]["name"] == body["metadata"]["name"]


def test_attach_duplicate_rejected():
    c, _ = _client()
    m.attach_cdrom(c, "ns1", "v1", "ns1", "local-iso")
    with pytest.raises(ops.KubeVirtOpError) as ei:
        m.attach_cdrom(c, "ns1", "v1", "ns1", "local-iso")
    assert ei.value.status_code == 409


def test_list_and_eject_cdrom():
    c, store = _client()
    r = m.attach_cdrom(c, "ns1", "v1", "ns1", "local-iso")
    lst = m.list_vm_cdroms(c, "ns1", "v1")
    assert lst == [{"disk": r["disk"], "source_kind": "pvc", "source": "local-iso", "boot_order": None}]
    e = m.eject_cdrom(c, "ns1", "v1", r["disk"])
    assert e["ok"]
    assert m.list_vm_cdroms(c, "ns1", "v1") == []
    spec = store["vm"]["spec"]["template"]["spec"]
    assert [d["name"] for d in spec["domain"]["devices"]["disks"]] == ["root"]
    assert [v["name"] for v in spec["volumes"]] == ["root"]


def test_eject_root_disk_refused_and_missing_404():
    c, store = _client()
    with pytest.raises(ops.KubeVirtOpError) as ei:
        m.eject_cdrom(c, "ns1", "v1", "root")  # cdrom değil
    assert ei.value.status_code == 404
    assert len(store["vm"]["spec"]["template"]["spec"]["volumes"]) == 1
    assert not c.session.patches


def test_add_disk_and_network_use_merge_patch():
    c, store = _client()
    ops.add_disk_datavolume(c, "ns1", "v1", "data1", "10Gi")
    ops.set_multus_network(c, "ns1", "v1", "br-vlan10", "net1")
    spec = store["vm"]["spec"]["template"]["spec"]
    assert {d["name"] for d in spec["domain"]["devices"]["disks"]} == {"root", "data1"}
    nets = {n["name"]: n for n in spec["networks"]}
    assert nets["net1"]["multus"]["networkName"] == "br-vlan10" and "default" in nets
    assert all(p[2]["Content-Type"] == "application/merge-patch+json" for p in c.session.patches)


def test_suggest_size():
    gi = 1024 ** 3
    assert m.suggest_upload_size_gi(1) == 1
    assert m.suggest_upload_size_gi(4 * gi) == 5
    assert m.suggest_upload_size_gi(5 * gi) == 6


def test_wait_dv_phase_ready_and_failed():
    phases = iter(["Pending", "UploadReady"])
    store = {"get": [("/datavolumes/d", lambda: _Resp(200, {"status": {"phase": next(phases)}}))]}
    c = _Client(store)
    assert m.wait_dv_phase(c, "ns1", "d", sleep=lambda s: None) == "UploadReady"
    store2 = {"get": [("/datavolumes/d", lambda: _Resp(200, {"status": {"phase": "Failed"}}))]}
    with pytest.raises(ops.KubeVirtOpError):
        m.wait_dv_phase(_Client(store2), "ns1", "d", sleep=lambda s: None)


def test_discover_proxy_from_cdiconfig_and_missing():
    c = _Client({"get": [("/cdiconfigs/config", lambda: _Resp(200, {"status": {"uploadProxyURL": "up.apps.x"}}))]})
    assert m.discover_upload_proxy(c) == "https://up.apps.x"
    with pytest.raises(ops.KubeVirtOpError):
        m.discover_upload_proxy(_Client({"get": []}))


def test_stream_upload_forwards_content_length_and_body():
    import httpx

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["cl"] = request.headers.get("content-length")
        seen["te"] = request.headers.get("transfer-encoding")
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.read()
        return httpx.Response(200)

    async def gen():
        for part in (b"abc", b"defg", b"h"):
            yield part

    r = asyncio.run(m.stream_upload(
        "https://proxy.example", "tok", gen(), 8, transport=httpx.MockTransport(handler),
    ))
    assert r["ok"] and seen["body"] == b"abcdefgh"
    assert seen["url"].endswith("/v1beta1/upload")
    assert seen["cl"] == "8" and seen["te"] is None
    assert seen["auth"] == "Bearer tok"


def test_stream_upload_proxy_error_maps_to_op_error():
    import httpx

    async def gen():
        yield b"x"

    with pytest.raises(ops.KubeVirtOpError):
        asyncio.run(m.stream_upload(
            "https://proxy.example", "tok", gen(), 1,
            transport=httpx.MockTransport(lambda r: httpx.Response(400, text="bad")),
        ))
