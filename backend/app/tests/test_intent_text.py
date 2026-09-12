"""intent_text — olumsuzluk penceresi ve karışık kavram+ops."""
from app.services.intent_text import (
    any_keyword_hit,
    keyword_hit,
    mixed_operational_after_sonra,
    regex_hit,
)


def test_keyword_hit_plain():
    assert keyword_hit("canlı CPU top 20", "canlı") is True
    assert keyword_hit("şu an ready nedir", "şu an") is True


def test_negation_after_demiyorum():
    q = "Filodaki VM CPU; anlık demiyorum, son sync yeterli."
    assert keyword_hit(q, "anlık") is False
    assert any_keyword_hit(q, ("anlık", "canlı", "şimdi")) is False


def test_negation_vcenter_dusme():
    q = "olvm manager canlı SSH; vCenter event listesine düşme."
    assert keyword_hit(q, "vcenter") is False
    assert keyword_hit(q, "ssh") is True


def test_negation_datastore_sapmadan():
    q = "minio1 iowait — vCenter datastore'una sapmadan guest OS kanıtla."
    assert keyword_hit(q, "datastore") is False
    assert keyword_hit(q, "vcenter") is False


def test_first_snapshot_not_negated_second_is():
    q = (
        "Snapshot'lar şişmiş ama asıl sorum OpenShift CrashLoop — "
        "vCenter snapshot tablosuna sapıp pod olaylarını atlama."
    )
    assert keyword_hit(q, "snapshot") is True
    assert keyword_hit(q, "openshift") is True


def test_vm_regex_negated_kaydirma():
    q = "minio1 ile Winserver01 karşılaştır; VM QueryPerf'e kaydırma."
    assert regex_hit(
        q,
        r"(?<![a-z0-9_])vm(?:s|ler|leri)?(?![a-z0-9_])",
    ) is False


def test_mixed_operational_after_sonra():
    assert mixed_operational_after_sonra(
        "RAID5 ile RAID10 farkını anlat, sonra minio1'de mdstat/mdadm ayrı tut"
    ) is True
    assert mixed_operational_after_sonra("RAID5 ile RAID10 farkı nedir?") is False
