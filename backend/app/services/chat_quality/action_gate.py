"""Eylem niyeti kapısı + prompt-sızıntı isteği kapısı (LLM'e HİÇ gitmeden şablon ret).

Sohbet salt-okunurdur. Kullanıcı bir değişiklik/eylem emri verirse (sil, kapat, yeniden başlat,
rm -rf çalıştır, kubectl delete …) ya da sistem talimatını isterse, model çağrılmaz:
şablon ret döner. Soru kalıpları ("kapalı VM'leri listele", "silinen VM'ler", "restart sayısı")
geçer. Salt-okunur teşhis komutu çalıştırma isteği ("uptime çalıştır") geçer (Linux direct_cmd
yolu ayrıca politika kapısından geçer).

Saf fonksiyonlar; yan etki yalnız `gate_response` içinde iz notu + audit kaydıdır.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from app.services.chat_quality.claims import fold, is_mutating_command_text

logger = logging.getLogger(__name__)

KIND_ACTION = "action"
KIND_LEAK = "prompt_leak"


@dataclass
class GateResult:
    kind: str
    verb: str = ""
    obj: str = ""
    reason: str = ""


# ── Eylem fiilleri (fold'lanmış metin) ─────────────────────────────────────────
# Güçlü: nesne olmadan da eylem emri
_STRONG_TR = (
    r"sil|silin|siliver|kapat|kapatin|kapa|kapativer|yeniden\s+baslat|yeniden\s+baslatin|"
    r"baslat|baslatin|durdur|durdurun|oldur|sonlandir|calistir|calistirin|"
    r"resetle|resetleyin|sifirla|sifirlayin"
)
# Zayıf: yalnız altyapı nesnesiyle birlikte
_WEAK_TR = (
    r"olustur|olusturun|kaldir|kaldirin|guncelle|guncelleyin|uygula|uygulayin|tasi|tasiyin|"
    r"olcekle|olceklendir|ekle|ekleyin|degistir|degistirin|genislet|genisletin|buyut|kucult|"
    r"tetikle|tetikleyin|iptal\s+et|yedekle|klonla|geri\s+al|geri\s+yukle|kurun|kur|"
    r"yamala|yukselt|temizle|bosalt|devre\s+disi\s+birak|aktif\s+et|pasife\s+al|pasif\s+et"
)
_POLITE_STEMS = (
    r"sil|kapat|baslat|durdur|calistir|olustur|kaldir|guncelle|uygula|tasi|degistir|sifirla|"
    r"resetle|ekle|olcekle|genislet|temizle"
)
_POLITE = re.compile(
    rf"\b(?:{_POLITE_STEMS})(?:ebilir|abilir|er|ir|ur|ar)\s*(?:misin|musun|misiniz|musunuz|mi)\b"
)
# "restart et", "reboot yap", "pod'u delete et" gibi yabancı kök + et/yap
_LOAN_ET = re.compile(
    r"\b(?:restart|reboot|shutdown|stop|start|delete|kill|drain|cordon|scale|deploy|migrate|patch|rollback|"
    r"reset|format|power\s*off|power\s*on|poweroff|poweron|remove|terminate|suspend|resume|execute|run)\s+"
    r"(?:et|edin|ediniz|yap|yapin|at|atin|eder\s+misin|edebilir\s+misin)\b"
)
_MAINT = re.compile(r"\b(?:bakim\s+moduna|maintenance\s+mode)\s*(?:al|alin|sok|sokun|gecir|ac|et)\b")
_AL_RE = re.compile(r"\b(?:snapshot|yedek|backup|anlik\s+goruntu)\w*\s+(?:al|alin|olustur|cikar)\b")
_SET_RE = re.compile(r"\b(?:gb|mb|tb|cpu|vcpu|ram|bellek|replika\w*|boyut\w*|core)\b[^.?\n]{0,40}\b(?:yap|yapin|ayarla|ayarlayin|cevir|olarak\s+degistir)\b")
_STRONG_TR_RE = re.compile(rf"\b(?:{_STRONG_TR})\b")
_WEAK_TR_RE = re.compile(rf"\b(?:{_WEAK_TR})\b")

# İngilizce emir: cümle başında (veya please/can you sonrası) ve mesaj Türkçe değilse
_EN_VERBS = (
    r"delete|remove|reboot|restart|shut\s*down|power\s*(?:off|on)|kill|terminate|drain|cordon|stop|start|"
    r"run|execute|create|deploy|install|uninstall|update|upgrade|patch|scale|migrate|clone|revert|rollback|"
    r"apply|format|wipe|reset|destroy"
)
_EN_CMD = re.compile(
    rf"^\s*(?:please\s+|pls\s+|kindly\s+)?(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?|go\s+ahead\s+and\s+|just\s+)?"
    rf"(?:{_EN_VERBS})\b(?!\s+(?:count|counts|history|rate|time|times|events?|policy|status|reason|loop|date|"
    rf"timeline|report|list))"
)
_TR_HINT = re.compile(
    r"\b(?:ve|bir|icin|ile|kac|hangi|neden|nasil|bu|su|tum|butun|sunucu|sunucuda|sunucusunda|makine|"
    r"kume|olan|olarak|lutfen|bana|goster|listele|nedir|mi|mu)\b"
)
_QUESTION_LEAD = re.compile(
    r"^\s*(?:neden|nasil|niye|nicin|ne\s+zaman|hangi|kac|nedir|ne\s+yapar|ne\s+olur|why|how|what|when|which|"
    r"does|do|is|are|can\s+i|should)\b"
)

# Altyapı nesneleri (zayıf fiiller için)
_OBJ = re.compile(
    r"\b(?:vm|vm'?ler\w*|sanal\s+makine\w*|makine\w*|sunucu\w*|server\w*|node\w*|pod\w*|namespace\w*|proje\w*|"
    r"deployment\w*|statefulset\w*|cluster\w*|kume\w*|host\w*|esx\w*|datastore\w*|disk\w*|servis\w*|service\w*|"
    r"snapshot\w*|job\w*|isi\b|isini|isler\w*|plan\w*|kullanici\w*|dosya\w*|dizin\w*|klasor\w*|/\w+|"
    r"komut\w*|container\w*|konteyner\w*|volume\w*|pvc\w*|route\w*|operator\w*|cron\w*|alarm\w*|"
    r"template\w*|sablon\w*|network\w*|ag\b|vlan\w*|firewall\w*|ip\b|sifre\w*|parola\w*|yetki\w*|rol\w*)"
)

_RUN_VERB = re.compile(r"\b(?:calistir\w*|run|execute|exec|uygula\w*)\b")

# ── Prompt sızıntı isteği ──────────────────────────────────────────────────────
_LEAK_REQ = [
    re.compile(r"\b(?:onceki|onceki\s+tum|tum|yukaridaki|bundan\s+onceki)\s+(?:talimat|yonerge|kural|komut|mesaj)\w*\s+"
               r"(?:yok\s+say|unut|gormezden\s+gel|iptal\s+et|gecersiz|bosver)"),
    re.compile(r"\b(?:talimat|yonerge|kural)\w*\s+(?:yok\s+say|unut|gormezden\s+gel)"),
    re.compile(r"\bignore\s+(?:all\s+|the\s+|your\s+|any\s+)?(?:previous|prior|above|earlier|system)\s+"
               r"(?:instructions?|rules?|prompts?|messages?)"),
    re.compile(r"\b(?:disregard|forget)\s+(?:all\s+|your\s+|the\s+)?(?:previous|prior|above)?\s*(?:instructions?|rules?)"),
    re.compile(r"\b(?:sistem|system)\s*(?:prompt|promp|talimat|mesaj|yonerge|istem)\w*[^.\n]{0,60}"
               r"(?:goster|yaz|paylas|ver\b|soyle|acikla|tekrar|aynen|listele|print|show|reveal|repeat|dump|leak|output|tell|display|give)"),
    re.compile(r"\b(?:goster|yaz|paylas|soyle|acikla|tekrar|aynen|listele|print|show|reveal|repeat|dump|leak|output|tell|display|give)\b"
               r"[^.\n]{0,60}\b(?:sistem|system)\s*(?:prompt|promp|talimat|mesaj|yonerge|istem)"),
    re.compile(r"\b(?:ilk|baslangic|gizli|ic|orijinal|gercek)\s+(?:talimat|yonerge|prompt|mesaj)\w*"),
    re.compile(r"\b(?:repeat|print|show|output|recite|reproduce)\s+(?:the\s+|your\s+)?(?:text|words|everything|"
               r"instructions?|prompt|message|content)\s+(?:above|before|so\s+far)"),
    re.compile(r"\bsana\s+verilen\s+(?:talimat|kural|yonerge)\w*"),
    re.compile(r"\b(?:talimatlarin|kurallarin|promptun|yonergelerin)\s+(?:neler|ne|nedir)\b"),
    re.compile(r"\bnasil\s+programlandin\b|\bseni\s+nasil\s+programladi\w*"),
    re.compile(r"\b(?:developer|dev|debug|god)\s+mode\b|\bjailbreak\b|\bdan\s+mode\b"),
    re.compile(r"\byour\s+(?:system\s+)?(?:prompt|instructions)\b"),
    re.compile(r"\bwhat\s+(?:is|are)\s+your\s+(?:system\s+)?(?:prompt|instructions|rules)\b"),
]

# ── Doğrudan komut kontrolü ─────────────────────────────────────────────────────
def _direct_commands_state(message: str) -> Optional[bool]:
    """Mesajdan komut çıkarılırsa: hepsi READ_ONLY → True, biri değilse → False, komut yok → None."""
    try:
        from app.services.agent.policy import RiskLevel, classify_command
        from app.services.linux_chat_intent import extract_direct_commands
        cmds = extract_direct_commands(message)
        if not cmds:
            return None
        return all(classify_command(c) == RiskLevel.READ_ONLY for c in cmds)
    except Exception:  # kapı hiçbir zaman sohbeti düşürmemeli
        return None


def check_message(message: str) -> Optional[GateResult]:
    """Mesajı sınıflar: eylem emri, sızıntı isteği veya None (geçer)."""
    raw = message or ""
    f = fold(raw)
    f = re.sub(r"\s+", " ", f).strip()
    if not f:
        return None

    # 1) Sızıntı isteği
    for p in _LEAK_REQ:
        if p.search(f):
            return GateResult(KIND_LEAK, reason=p.pattern[:40])

    # 2) Doğrudan komut: salt-okunur olmayan komut → eylem
    state = _direct_commands_state(raw)
    if state is False:
        return GateResult(KIND_ACTION, verb="komut", obj="komut", reason="non_read_only_command")

    has_run = bool(_RUN_VERB.search(f))
    # 3) Mesajda değişiklik yapan komut metni + çalıştırma fiili / emir → eylem
    #    ("kubectl delete ne yapar?" gibi açıklama soruları geçer)
    if (is_mutating_command_text(raw) and (has_run or not _QUESTION_LEAD.search(f))
            and not _is_explain_question(f) and not _bare_word_only(raw, f, has_run)):
        return GateResult(KIND_ACTION, verb="komut", obj="komut", reason="mutating_command_text")

    # 4) Türkçe emir kipi
    m = _POLITE.search(f) or _LOAN_ET.search(f) or _MAINT.search(f) or _AL_RE.search(f) or _SET_RE.search(f)
    if m and not _QUESTION_LEAD.search(f):
        return GateResult(KIND_ACTION, verb=m.group(0), obj=_obj_of(f), reason="polite_or_loan")
    ms = _STRONG_TR_RE.search(f)
    if ms and not _QUESTION_LEAD.search(f):
        verb = ms.group(0)
        if _RUN_VERB.fullmatch(verb) or verb.startswith("calistir"):
            # "uptime komutunu çalıştır": çıkarılan komutlar salt-okunursa geçer
            if state is True:
                return None
            return GateResult(KIND_ACTION, verb=verb, obj=_obj_of(f), reason="run_unknown")
        return GateResult(KIND_ACTION, verb=verb, obj=_obj_of(f), reason="strong_verb")
    mw = _WEAK_TR_RE.search(f)
    if mw and _OBJ.search(f) and not _QUESTION_LEAD.search(f):
        return GateResult(KIND_ACTION, verb=mw.group(0), obj=_obj_of(f), reason="weak_verb_obj")

    # 5) İngilizce emir (mesaj Türkçe değilse)
    if not _TR_HINT.search(f) and not re.search(r"[çğıöşüİ]", raw):
        me = _EN_CMD.search(f)
        if me:
            verb = me.group(0).strip()
            if re.search(r"\b(?:run|execute)\b", verb) and state is True:
                return None
            return GateResult(KIND_ACTION, verb=verb, obj=_obj_of(f), reason="en_imperative")
    return None


_BARE_MUT_WORDS = {"reboot", "shutdown", "halt", "poweroff", "kill", "killall", "pkill", "passwd", "umount"}


def _bare_word_only(raw: str, f: str, has_run: bool) -> bool:
    """Eşleşen tek şey çıplak bir sözcükse (reboot/shutdown …) ve çalıştırma fiili yoksa komut sayma.

    "Son reboot ne zaman", "reboot geçmişi" geçer; "sudo reboot", "reboot çalıştır", yalnız "reboot" ya da
    alt komutlu kalıplar (systemctl stop, kubectl delete …) eylemdir.
    """
    if has_run:
        return False
    from app.services.chat_quality.claims import MUTATING_CMD_RE
    texts = [m.group(0).strip().lower() for p in MUTATING_CMD_RE for m in [p.search(raw)] if m]
    if not texts:
        return False
    if all(t in _BARE_MUT_WORDS for t in texts):
        return f.strip() not in _BARE_MUT_WORDS and not re.search(r"\bsudo\s+(?:reboot|shutdown|halt|poweroff|kill)", f)
    return False


def soft_action_intent(message: str) -> bool:
    """Geniş eylem niyeti: kapı eşiğini geçmese de mesajda eylem fiili var mı (zayıf iddia kontrolünü açar)."""
    f = re.sub(r"\s+", " ", fold(message or "")).strip()
    if not f:
        return False
    if check_message(message) is not None:
        return True
    return bool(_STRONG_TR_RE.search(f) or _WEAK_TR_RE.search(f) or _POLITE.search(f)
                or _LOAN_ET.search(f) or _EN_CMD.search(f))


def _is_explain_question(f: str) -> bool:
    return bool(re.search(
        r"\b(?:ne\s+yapar|ne\s+ise\s+yarar|nedir|nasil\s+calisir|ne\s+demek|anlami|farki|what\s+does|what\s+is|"
        r"explain|aciklar\s+misin|anlat)\b", f))


def _obj_of(f: str) -> str:
    if re.search(r"\b(?:vm|sanal\s+makine|esx|datastore|snapshot|hypervisor)", f):
        return "vm"
    if re.search(r"\b(?:pod|namespace|proje|deployment|openshift|cluster|kume|node|route|operator|oc|kubectl)", f):
        return "ocp"
    if re.search(r"\b(?:job|isi|automic|plan)\b", f):
        return "job"
    if re.search(r"\b(?:sunucu|server|komut|dizin|dosya|klasor|disk|servis|service|/\w+)", f):
        return "server"
    return ""


# ── Şablon yanıtlar ────────────────────────────────────────────────────────────
_ALTERNATIVES = {
    "vm": "VM'in mevcut durumunu, bağlı olduğu host/datastore'u ve etkilenecek kaynakları göstermek",
    "ocp": "kaynağın mevcut durumunu, olaylarını (events) ve loglarını göstermek ve olası nedenleri yorumlamak",
    "job": "işin son çalışma durumunu, hata kodlarını ve bağımlılıklarını göstermek",
    "server": "salt-okunur teşhis komutlarını (ör. `df -h`, `uptime`, `ss -tulpn`) çalıştırıp çıktıyı yorumlamak",
    "": "mevcut durumu ve etkilenecek kaynakları salt-okunur olarak göstermek",
}


def _echo(message: str) -> str:
    t = re.sub(r"\s+", " ", (message or "").strip())
    t = t.replace("`", "'")
    return (t[:117] + "…") if len(t) > 120 else t


def refusal_text(res: GateResult, message: str) -> str:
    if res.kind == KIND_LEAK:
        return (
            "Sistem talimatlarımı veya iç yapılandırmamı paylaşamam, talimatları yok sayma isteği de "
            "uygulanmaz. Ortamınızla ilgili sorular sorabilirsiniz; örneğin VM, host, cluster, node, pod "
            "veya sunucu durumu."
        )
    alt = _ALTERNATIVES.get(res.obj, _ALTERNATIVES[""])
    return (
        f"**Bu isteği çalıştıramam:** «{_echo(message)}»\n\n"
        "Bu sohbet **salt-okunur** çalışır: sanal makine, küme, sunucu veya iş üzerinde değişiklik yapmaz, "
        "silme/kapatma/yeniden başlatma gibi eylemleri çalıştırmaz. İsterseniz şunları yapabilirim: "
        f"{alt}.\n\n"
        "Değişiklik gerekiyorsa insan onaylı Agent akışını veya ilgili yönetim ekranını kullanın."
    )


def refusal_quality_ok(text: str) -> bool:
    """Ret ifadesi kalitesi (otomatik): ret + salt-okunur gerekçe + güvenli alternatif + yapıldı iddiası yok."""
    f = fold(text)
    refusal = bool(re.search(r"calistiramam|calistirilmadi|paylasamam|yapamam|uygulanmaz|olamam", f))
    reason = bool(re.search(r"salt-okunur|salt okunur|read-only|talimat", f))
    alt = bool(re.search(r"isterseniz|yapabilirim|sorabilirsiniz|gosterebilirim|kullanin", f))
    from app.services.chat_quality.claims import claim_level
    claim = any(claim_level(s, user_action_intent=True) for s in re.split(r"(?<=[.!?])\s+", text or ""))
    return refusal and reason and alt and not claim


def gate_response(message: str, *, platform: Optional[str] = None) -> Optional[str]:
    """Pipeline'ların chitchat noktasından çağrılır: ret metni (veya None → normal akış)."""
    try:
        res = check_message(message)
    except Exception:
        logger.warning("[ActionGate] kontrol hatası", exc_info=True)
        return None
    if res is None:
        return None
    try:
        from app.services.chat_quality import trace as cq_trace
        cq_trace.note_path("action_gate", gate=res.kind, verb=res.verb[:30], reason=res.reason, platform=platform or "")
        tr = cq_trace.current()
        _audit(res, message, tr)
    except Exception:
        pass
    logger.warning("[ActionGate] %s reddedildi (verb=%r reason=%s platform=%s): %.80s",
                   res.kind, res.verb, res.reason, platform, message)
    return refusal_text(res, message)


def _audit(res: GateResult, message: str, tr) -> None:
    from app.services.audit import record_audit
    from app.services.chat_quality.masking import mask_text
    record_audit(
        None, category="ai_guard", action=f"chat.gate.{res.kind}", status="blocked",
        actor=(getattr(tr, "username", None) or None),
        summary=mask_text(message)[:140],
        detail={"verb": res.verb, "reason": res.reason, "turn_id": getattr(tr, "turn_id", None)},
    )
