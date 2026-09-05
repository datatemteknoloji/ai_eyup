"""chat_intent unit tests."""
from app.services.chat_intent import (
    classify_chat_intent,
    ChatIntentKind,
    should_skip_inventory_prefetch,
)
from app.services.virt_inventory_contract import detect_virt_inventory_kind


def test_datastore_nedir_is_conceptual():
    intent = classify_chat_intent("datastore nedir?")
    assert intent.kind == ChatIntentKind.CONCEPTUAL
    assert should_skip_inventory_prefetch("datastore nedir?")
    assert detect_virt_inventory_kind("datastore nedir?") is None


def test_datastore_list_is_inventory():
    intent = classify_chat_intent("datastore doluluk listesi göster")
    assert intent.kind == ChatIntentKind.INVENTORY
    assert detect_virt_inventory_kind("datastore doluluk listesi göster") == "datastore"


def test_vm_disk_in_datastore_inventory():
    q = "PMAX_LINUX_TST_003 bu datastore içerisinde hangi vmlere ait diskler var?"
    intent = classify_chat_intent(q)
    assert intent.kind == ChatIntentKind.INVENTORY
    assert not should_skip_inventory_prefetch(q)
    assert detect_virt_inventory_kind(q) == "vm_disk"


def test_soap_live():
    intent = classify_chat_intent("vcenter soap kullanarak snapshot listele")
    assert intent.kind in (ChatIntentKind.LIVE, ChatIntentKind.INVENTORY, ChatIntentKind.MIXED)


def test_troubleshooting_hangi_metrik_is_conceptual():
    q = (
        "Bir VM'de uygulama zaman zaman yavaşlıyor. CPU %30, RAM %50, disk latency 5 ms. "
        "Ancak kullanıcılar 10–20 saniyelik gecikmeler yaşıyor. "
        "Hangi metrikleri ve hangi katmanları incelersin?"
    )
    intent = classify_chat_intent(q)
    assert intent.kind == ChatIntentKind.CONCEPTUAL
    assert should_skip_inventory_prefetch(q)
    assert detect_virt_inventory_kind(q) is None


def test_hangi_alone_not_inventory():
    """'hangi' tek başına envanter tetiklemez."""
    intent = classify_chat_intent("Hangi katmanlara bakmak gerekir?")
    assert intent.kind == ChatIntentKind.CONCEPTUAL
    assert should_skip_inventory_prefetch("Hangi katmanlara bakmak gerekir?")
    assert detect_virt_inventory_kind("Hangi katmanlara bakmak gerekir?") is None


def test_hangi_vm_is_inventory():
    intent = classify_chat_intent("hangi vm'ler powered on?")
    assert intent.kind == ChatIntentKind.INVENTORY


def test_sorgula_host_vm_question_is_not_general():
    # Gerçek regresyon: bu ifade önceden GENERAL'e düşüyor, deterministik
    # katman hiç devreye girmiyordu (bkz. detect_virt_inventory_kind testi).
    q = "isthol5esxia03.kscloud.local bu esxi host üzerindeki vmleri canlı sorgula"
    intent = classify_chat_intent(q)
    assert intent.kind in (ChatIntentKind.LIVE, ChatIntentKind.INVENTORY, ChatIntentKind.MIXED)
    assert intent.kind != ChatIntentKind.GENERAL
