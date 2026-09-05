"""
Sohbet niyet sınıflandırması — keyword prefetch / deterministik katman için kapı.

Dinamik: kural tabanlı (hızlı, LLM'siz).
Kavramsal / eğitim / troubleshooting sorularında envanter prefetch atlanır.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ChatIntentKind(str, Enum):
    CONCEPTUAL = "conceptual"      # nedir, açıkla, teşhis rehberi, senaryo
    INVENTORY = "inventory"        # listele, doluluk, hangi VM'ler
    LIVE = "live"                  # canlı, anlık, soap
    MIXED = "mixed"                # kavram + veri
    GENERAL = "general"            # belirsiz — LLM karar versin


@dataclass
class ChatIntent:
    kind: ChatIntentKind
    confidence: float  # 0..1
    reason: str


# Eğitim / teşhis / senaryo — envanter değil
_EDUCATIONAL_RE = re.compile(
    r"("
    r"\b("
    r"nedir|ne demek|ne anlama|tanım|tanımla|açıkla|acikla|explain|what is|what are|"
    r"farkı ne|farki ne|fark nedir|nasıl çalış|nasil calis|örnek ver|ornek ver|"
    r"anlatır mısın|anlatir misin|kavram|teorik|basitçe|basitce|"
    r"incelersin|inceler misin|ne bakarsın|ne bakmali|nasıl teşhis|nasil teshis|"
    r"teşhis|teshis|troubleshoot|troubleshooting|kök neden|kok neden|kök sebep|"
    r"yavaşlıyor|yavasliyor|gecikme|latency|senaryo|hipotetik|varsayalım|varsayalim|"
    r"hangi metrik|hangi katman|metrikleri|katmanları|katmanlari|"
    r"nasıl yaklaşırsın|nasil yaklasirsin|ne önerirsin|ne onerirsin"
    r")\b"
    r"|hangi\s+metrik"
    r"|hangi\s+katman"
    r")",
    re.I,
)

# Açık envanter / operasyonel liste isteği
#
# NOT (fiil kapsamı): Türkçe'de aynı isteği ifade eden fiil sayısı pratikte
# sonsuzdur (listele/getir/çek/sorgula/göster/ver/bul/ilet/çıkar/kontrol et/
# incele/bak/...). Bu regex'in kaçırdığı yeni bir fiil çıkması KAÇINILMAZ —
# bu yüzden bu liste TEK savunma katmanı değildir; asıl güvenlik ağı
# unified_tool_chat.py::_finalize()'daki decouple mekanizmasıdır: regex hiçbir
# şey yakalamasa bile, model kendi kararıyla db_list_vms/db_list_datastores/
# db_list_esx_hosts çağırırsa deterministik render yine denenir (bkz.
# virt_inventory_contract.infer_kind_from_tool_call). Buradaki liste yalnızca
# PROAKTİF prefetch'i (LLM'e sormadan önce DB'yi çekmek) tetikler — eksik
# olması yanlış cevaba değil, en fazla bir adım daha yavaş (ama yine doğru)
# bir cevaba yol açar.
_INVENTORY_STRONG_RE = re.compile(
    r"("
    r"\b("
    r"listele|liste|göster|goster|kaç|kac|say|toplam|doluluk|kapasite|"
    r"boş\s*(gb|alan|yer)?|bos\s*(gb|alan|yer)?|envanter|inventory|"
    r"içerisinde|icerisinde|barındır|barindir|powered\s*on|powered\s*off|"
    r"table|/table|tablo|sırala|sirala|filtre|"
    r"sorgula|getir|çek|cek|ilet|çıkar|cikar|"
    r"kontrol\s*et|incele|teyit\s*et|doğrula|dogrula"
    r")\b"
    r"|hangi\s+(vm|vms|host|esxi|datastore|datastores|cluster|snapshot|alarm)"
    r"|hangi\s+vm.?ler"
    r"|vm.?lere?\s+ait"
    r"|disk\s*(adet|sayısı|sayisi|boyut|listesi)"
    r"|snapshot.?ı?\s*olan"
    r")",
    re.I,
)

_LIVE_RE = re.compile(
    r"\b("
    r"canlı|canli|live|soap|anlık|anlik|gerçek zaman|gercek zaman|"
    r"vcenter.?dan|vCenter API"
    r")\b",
    re.I,
)

_ENTITY_RE = re.compile(
    # Sağ tarafta \b YOK: Türkçe ekler kelime köküne bitişik gelir
    # (ör. "snapshotların", "datastore'daki") — yine de varlık say.
    r"\b(datastore|vm|esxi|host|cluster|snapshot|alarm|disk|sanal|"
    r"vcenter|hypervisor|ortam|altyapı|altyapi)",
    re.I,
)

# Bu ORTAMIN o anki durumunu soran ifadeler. Tek başına "nedir" gramerine
# bakıp bunları kavramsal saymak, "vCenter'ın sağlık durumu nedir?" gibi
# soruların envanter/araç kanıtı olmadan yanıtlanmasına yol açıyordu.
_STATE_RE = re.compile(
    r"\b("
    r"sağlık|saglik|sağlıklı|saglikli|durum|durumu|durumda|"
    r"sorun|problem|risk|arıza|ariza|hata|uyarı|uyari|alarm|"
    r"performans|yoğunluk|yogunluk|darboğaz|darbogaz|"
    r"health|status|issue"
    r")",
    re.I,
)

# Somut, ÖLÇÜLEBİLİR bir değer isteyen ifadeler — "X nedir?" kalıbı bunlarla
# birlikte geçtiğinde artık bir TANIM sorusu değil, gerçek bir VERİ sorusudur.
# Örn. "snapshotların boyutları nedir?" bir tanım istemiyor, gerçek bir sayı
# istiyor — CONCEPTUAL değil, canlı/envanter sorgusu olarak ele alınmalı.
_MEASURABLE_ATTR_RE = re.compile(
    r"("
    r"\b("
    r"boyut|büyüklük|buyukluk|"  # ekler bitişik gelebilir (boyutu/boyutları/boyutlarının...)
    r"kapasite|alan|miktar|oran|yüzde|yuzde|"
    r"sayı|sayi|adedi|kaç|kac|"
    r"ne\s*kadar"
    r")"
    r"|\d+\s*(gb|mb|tb)\b"
    r")",
    re.I,
)


def classify_chat_intent(message: str) -> ChatIntent:
    """Tur başına niyet — envanter prefetch kapısı."""
    m = (message or "").strip()
    if not m:
        return ChatIntent(ChatIntentKind.GENERAL, 0.0, "empty")

    educational = bool(_EDUCATIONAL_RE.search(m))
    inventory = bool(_INVENTORY_STRONG_RE.search(m))
    live = bool(_LIVE_RE.search(m))
    has_entity = bool(_ENTITY_RE.search(m))
    measurable = bool(_MEASURABLE_ATTR_RE.search(m))

    # "X boyutu/büyüklüğü/ne kadar ... nedir?" — gramer olarak "nedir" içerse de
    # bu bir TANIM sorusu değil, somut bir DEĞER isteğidir (ör. "snapshotların
    # boyutları nedir?"). Somut bir varlık (VM/snapshot/disk/datastore/...) ile
    # birlikte geçiyorsa CONCEPTUAL'a düşürmeden envanter/canlı sorgusu say —
    # sistem tarif vermek yerine gerçekten sorgulasın.
    if educational and measurable and has_entity:
        inventory = True
        educational = False

    # "<varlık> sağlıklı mı / durumu nedir / sorun var mı" — tanım değil, BU
    # ortamın o anki durumu soruluyor. Kavramsal sayılırsa boru hattı envanteri
    # ve araç kanıtını atıyor, model de "canlı veri dönmedi" diyordu.
    if has_entity and _STATE_RE.search(m):
        educational = False
        inventory = True

    # Eğitim/teşhis senaryosu: "hangi metrik" envanter değil
    if educational and not inventory:
        return ChatIntent(ChatIntentKind.CONCEPTUAL, 0.93, "educational_or_troubleshooting")

    # Hem eğitim hem liste: örn. "datastore nedir ve listele"
    if educational and inventory:
        return ChatIntent(ChatIntentKind.MIXED, 0.7, "educational_and_inventory")

    if live and inventory:
        return ChatIntent(ChatIntentKind.LIVE, 0.85, "live_inventory")

    if live and not educational:
        return ChatIntent(ChatIntentKind.LIVE, 0.8, "live_keywords")

    if inventory:
        return ChatIntent(ChatIntentKind.INVENTORY, 0.85, "inventory_action")

    # Entity tek başına uzun metinde envanter sayılmaz (yanlış pozitif)
    if has_entity and len(m.split()) <= 8 and not educational:
        return ChatIntent(ChatIntentKind.INVENTORY, 0.5, "short_entity_query")

    if educational:
        return ChatIntent(ChatIntentKind.CONCEPTUAL, 0.7, "educational_fallback")

    return ChatIntent(ChatIntentKind.GENERAL, 0.4, "general")


def should_skip_inventory_prefetch(message: str) -> bool:
    """virt_inventory_contract prefetch + early_stop atlanmalı mı?"""
    intent = classify_chat_intent(message)
    return intent.kind in (
        ChatIntentKind.CONCEPTUAL,
        ChatIntentKind.GENERAL,
        ChatIntentKind.MIXED,  # MIXED: LLM karar versin; zorunlu prefetch yok
    )


def should_skip_deterministic(message: str) -> bool:
    """Saf kavramsal / eğitim sorusunda QA_RULES atlanır."""
    intent = classify_chat_intent(message)
    return intent.kind == ChatIntentKind.CONCEPTUAL
