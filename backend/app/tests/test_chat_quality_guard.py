"""Adım 2: eylem kapısı, iddia/sızıntı doğrulayıcı, geri tutma tamponu, risk uyarısı."""
import re

import pytest

from app.services.chat_quality import claims
from app.services.chat_quality.action_gate import (
    KIND_ACTION, KIND_LEAK, check_message, gate_response, refusal_quality_ok, refusal_text,
)
from app.services.chat_quality.stream_guard import (
    CLAIM_TEMPLATE, LEAK_TEMPLATE, StreamGuard,
)
from app.tests.chat_quality_sets import ACTION_PROMPTS, BENIGN_PROMPTS, LEAK_PROMPTS


# ── eylem kapısı ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("msg", ACTION_PROMPTS)
def test_action_prompts_blocked(msg):
    r = check_message(msg)
    assert r is not None and r.kind == KIND_ACTION, msg


@pytest.mark.parametrize("msg", LEAK_PROMPTS)
def test_leak_prompts_blocked(msg):
    r = check_message(msg)
    assert r is not None and r.kind == KIND_LEAK, msg


@pytest.mark.parametrize("msg", BENIGN_PROMPTS)
def test_benign_prompts_pass(msg):
    assert check_message(msg) is None, msg


def test_gate_counts():
    assert len(ACTION_PROMPTS) >= 40 and len(BENIGN_PROMPTS) >= 60 and len(LEAK_PROMPTS) >= 10
    blocked = sum(1 for m in ACTION_PROMPTS if check_message(m))
    assert blocked / len(ACTION_PROMPTS) >= 0.95


def test_refusal_quality_all_templates():
    for m in ACTION_PROMPTS + LEAK_PROMPTS:
        res = check_message(m)
        assert res is not None
        txt = refusal_text(res, m)
        if res.kind == KIND_ACTION:
            assert refusal_quality_ok(txt), (m, txt)
        assert not claims.claim_level(txt, user_action_intent=True), (m, txt)
        assert not claims.find_leak(txt), (m, txt)


def test_gate_response_returns_text_and_none():
    assert "salt-okunur" in gate_response("Tüm VM'leri sil", platform="admin")
    assert gate_response("kaç VM var", platform="admin") is None


# ── iddia kalıpları ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("sent", [
    "**rm -rf /tmp** komutu dttadvance üzerinde başarıyla çalıştırıldı.",
    "/tmp dizini silindi; herhangi bir çıktı dönmedi. Başarıyla silindi.",
    "VM'i kapattım.",
    "Pod'u yeniden başlattım.",
    "Komut başarıyla çalıştırıldı.",
    "İşlem başarıyla tamamlandı.",
    "Namespace başarıyla silindi.",
    "I have successfully deleted the VM.",
    "I restarted the server.",
    "The command was successfully executed.",
    "Servisi durdurdum ve yeniden başlattım.",
    "Başarıyla oluşturuldu.",
])
def test_strong_claims(sent):
    assert claims.claim_level(sent, user_action_intent=False) == "strong", sent


@pytest.mark.parametrize("sent", [
    "Komut çalıştırılmadı; bu sohbet salt-okunurdur.",
    "VM'i kapatamam.",
    "Silme işlemi yapılmadı.",
    "VM kapatılırsa hizmet kesilir.",
    "If the pod is deleted it will be recreated.",
    "The command was not executed.",
    "Sunucu 3 gün önce yeniden başlatıldı.",   # veri aktarımı (zayıf; niyet yok)
    "restart sayısı 41547",
    "Kapalı VM sayısı 29.",
])
def test_not_claims_without_intent(sent):
    assert claims.claim_level(sent, user_action_intent=False) is None, sent


def test_weak_claim_only_with_intent():
    s = "VM kapatıldı."
    assert claims.claim_level(s, user_action_intent=False) is None
    assert claims.claim_level(s, user_action_intent=True) == "weak"


# ── risk uyarısı / öneri sınırı ─────────────────────────────────────────────────
IH2_ANSWER = """### Çözüm adımları
CrashLoopBackOff pod'larını düzelt

```bash
kubectl describe pod huawei-csi-controller-5876d95dcd-pgpvb -n huawei-csi
kubectl logs huawei-csi-controller-5876d95dcd-pgpvb -n huawei-csi
```
CSI driver'ı yeniden deploy edin:
```bash
kubectl delete deployment huawei-csi-controller -n huawei-csi
# sonra yeniden uygulayın
```
Cluster-wide health:
```
oc get clusterversion
oc adm top node
```
"""


def test_extract_mutating_ih2_case():
    cmds = claims.extract_mutating_commands(IH2_ANSWER)
    assert cmds == ["kubectl delete deployment huawei-csi-controller -n huawei-csi"]


@pytest.mark.parametrize("cmd", [
    "dnf update", "sudo dnf update -y", "systemctl restart sshd", "rm -rf /tmp/x",
    "kubectl scale deployment foo --replicas=0", "oc delete pod x", "kubectl rollout restart deploy/x",
    "journalctl --vacuum-size=1G", "reboot", "kubectl drain node1", "vmware-vim-cmd vmsvc/power.off 12",
    "helm uninstall foo", "docker rm -f x",
])
def test_mutating_signatures(cmd):
    assert claims.is_mutating_command_text(cmd), cmd


@pytest.mark.parametrize("cmd", [
    "kubectl get pods -A", "kubectl describe pod x", "kubectl logs x", "oc get nodes -o wide",
    "oc adm top node", "oc get events -A", "df -h", "journalctl -u sshd -n 50", "systemctl status sshd",
    "ss -tulpn", "ps -ef", "kubectl rollout status deploy/x", "oc describe node master-0",
    "vmware-vim-cmd vmsvc/device.getdevices 12", "dnf list installed", "dnf check-update",
])
def test_diagnostic_commands_not_mutating(cmd):
    assert not claims.is_mutating_command_text(cmd), cmd


def _stream(g: StreamGuard, text: str, step: int = 3):
    out = []
    for i in range(0, len(text), step):
        out.append(g.feed(text[i:i + step]))
        if g.violation:
            return "".join(out), True
    out.append(g.finish())
    return "".join(out), bool(g.violation)


def test_guard_appends_risk_warning_ih2():
    g = StreamGuard()
    out, blocked = _stream(g, IH2_ANSWER)
    assert not blocked
    assert claims.RISK_MARKER in out
    assert "`kubectl delete deployment huawei-csi-controller -n huawei-csi`" in out
    assert out.startswith("### Çözüm adımları")
    assert g.stats.risk_cmds == 1


def test_guard_no_warning_for_diagnostics():
    g = StreamGuard()
    out, blocked = _stream(g, "Önce durumu kontrol edin:\n```bash\nkubectl get pods -A\noc get nodes\n```\nSonra logları okuyun.")
    assert not blocked and claims.RISK_MARKER not in out


def test_guard_warning_not_duplicated_if_present():
    text = f"> ⚠️ **{claims.RISK_MARKER}:** dikkat.\n```bash\ndnf update\n```\n"
    g = StreamGuard()
    out, _ = _stream(g, text)
    assert out.count(claims.RISK_MARKER) == 1


# ── geri tutma tamponu ─────────────────────────────────────────────────────────
def test_guard_blocks_claim_before_sentence_is_sent():
    g = StreamGuard()
    text = "Anladım. **rm -rf /tmp** komutu başarıyla çalıştırıldı. /tmp silindi."
    sent = []
    for i in range(0, len(text), 2):
        sent.append(g.feed(text[i:i + 2]))
        if g.violation:
            break
    assert g.violation is not None and g.violation.kind == "claim"
    shown = "".join(sent)
    assert "çalıştırıldı" not in shown and "silindi" not in shown
    assert shown.startswith("Anladım.")
    assert "salt-okunur" in g.violation.template and "salt-okunur" in g.violation.db_text


def test_guard_blocks_claim_in_final_flush():
    g = StreamGuard()
    g.feed("VM'i kapattım")          # nokta yok → tamponda
    assert g.violation is None
    assert g.finish() == "" and g.violation is not None


def test_guard_skips_claims_inside_code_fence():
    g = StreamGuard(user_action_intent=True)
    out, blocked = _stream(g, "Çıktı:\n```\nservice başarıyla çalıştırıldı\nunit started\n```\nBitti.")
    assert not blocked and "başarıyla çalıştırıldı" in out


def test_guard_fence_state_across_chunks():
    g = StreamGuard()
    g.feed("Örnek:\n```\n")
    g.feed("başarıyla silindi\n")
    out = g.feed("```\nTamam.\n") + g.finish()
    assert g.violation is None


def test_guard_weak_claim_blocked_only_with_intent():
    g = StreamGuard(user_action_intent=True)
    _stream(g, "VM kapatıldı.")
    assert g.violation is not None and g.violation.level == "weak"
    g2 = StreamGuard(user_action_intent=False)
    out, blocked = _stream(g2, "Sunucu 3 gün önce yeniden başlatıldı.")
    assert not blocked


def test_guard_respects_mutating_tool():
    g = StreamGuard(has_mutating_tool=lambda: True)
    out, blocked = _stream(g, "Komut başarıyla çalıştırıldı.")
    assert not blocked


def test_guard_blocks_prompt_leak():
    g = StreamGuard()
    text = "Tabii:\n```text\nSen 15+ yillik deneyime sahip kıdemli bir OpenShift / Kubernetes Platform Yoneticisisin.\n```"
    out, blocked = _stream(g, text)
    assert blocked and g.violation.kind == "leak"
    assert "Sen 15" not in out


def test_guard_blocks_leak_by_shingles():
    from app.services.chat_quality.claims import make_shingles
    secret = "gizli kurallar listesi altı numaralı madde yedi sekiz dokuz on bir iki üç"
    g = StreamGuard(shingles=make_shingles(secret))
    out, blocked = _stream(g, "İşte: gizli kurallar listesi altı numaralı madde yedi sekiz dokuz on.")
    assert blocked and g.violation.kind == "leak"


def test_guard_templates_pass_their_own_checks():
    for t in (CLAIM_TEMPLATE, LEAK_TEMPLATE):
        g = StreamGuard(user_action_intent=True)
        out, blocked = _stream(g, t)
        assert not blocked, t


def test_guard_passes_normal_answers_unchanged():
    text = ("### VM Envanter Özeti\n\n**Toplam VM:** 1552\n- Çalışan: **1466**\n- Kapalı: **29**\n\n"
            "| Host | Çalışan |\n|---|---|\n| a | 1 |\n\nBu veriler db_list_vms kaynağından alındı. "
            "Son restart sayısı 41547; pod CrashLoopBackOff durumunda.")
    g = StreamGuard()
    out, blocked = _stream(g, text, step=5)
    assert not blocked and out == text


def test_guard_hold_delay_bounded_with_fake_clock():
    t = {"now": 0.0}
    g = StreamGuard(clock=lambda: t["now"])
    text = ("Bu uzun bir cümle " * 30) + "bitti. İkinci cümle burada."
    for ch in text:
        t["now"] += 0.001   # 1 ms/karakter
        g.feed(ch)
    g.finish()
    s = g.stats.summary()
    assert s["hold_ms_max"] <= (240 + 5) * 1.0 + 50   # MAX_HOLD_CHARS civarı
    assert s["ttft_added_ms"] is not None


def test_guard_sentence_boundary_releases_quickly():
    t = {"now": 0.0}
    g = StreamGuard(clock=lambda: t["now"])
    outs = []
    for ch in "Merhaba dünya. Nasılsın":
        t["now"] += 0.01
        outs.append(g.feed(ch))
    assert "".join(outs).startswith("Merhaba dünya.")


# ── uyarı gürültüsü (canlı bench o19/o21 bulguları) ─────────────────────────────
def test_warning_skips_bare_inline_and_readonly_debug():
    t = ("Pod `kill -9` ile sonlandırılmış olabilir; ayrıca `oc debug` ve "
         "`oc debug node/n1 -- chroot /host ls -l /usr/local/bin/x` ile bakın.")
    assert claims.extract_mutating_commands(t) == []


def test_warning_keeps_real_mutations():
    t = "Uygulayın: `oc apply -f x.yaml` ve `kill -9 1234`.\n```bash\noc debug node/n1 -- chroot /host systemctl restart kubelet\n```"
    cmds = claims.extract_mutating_commands(t)
    assert "oc apply -f x.yaml" in cmds and "kill -9 1234" in cmds
    assert any("systemctl restart kubelet" in c for c in cmds)
