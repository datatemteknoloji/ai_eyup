"""
vSphere sensör adı sadeleştirme.

numericSensorInfo.name donanım etiketini tekrar edebiliyor ("Power Supply 2
Power Supply 2 --- Normal"); tabloya olduğu gibi yazılınca okunmaz oluyordu.
"""
import pytest

from app.services.vmware.vcenter_client import VCenterClient

clean = VCenterClient._clean_sensor_name


@pytest.mark.parametrize("raw,expected", [
    ("Power Supply 2 Power Supply 2", "Power Supply 2"),
    ("Power Supply 2 Power Supply 2 --- Normal", "Power Supply 2"),
    ("System Board 1 System Board 1 Temp", "System Board 1 Temp"),
    ("CPU1 Temp", "CPU1 Temp"),
    ("  Fan   Block  1  ", "Fan Block 1"),
])
def test_repeated_labels_are_collapsed(raw, expected):
    assert clean(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_empty_names_become_none(raw):
    assert clean(raw) is None


def test_distinct_words_are_preserved():
    assert clean("Power Supply 1 Power Supply 2") == "Power Supply 1 Power Supply 2"
