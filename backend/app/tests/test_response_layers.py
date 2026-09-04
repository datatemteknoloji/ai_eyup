"""response_layers — katman etiketleme yardımcıları geriye dönük uyumluluk testleri.

Üretilen metinler chat.py / windows_chat.py / unified_chat.py'de daha önce elle
yazılmış başlıklarla BİREBİR aynı olmalı (persona addendum'lar bu başlıkları
tırnak içinde alıntılıyor, bkz. unified_chat.py:233,236).
"""
from app.services.response_layers import layer_header, wrap_layer


def test_layer_header_matches_legacy_strings():
    assert layer_header("linux_ssh") == "LINUX SUNUCULARDAN ALINAN GERCEK VERILER (SSH)"
    assert layer_header("windows_winrm") == "WINDOWS SUNUCULARDAN ALINAN GERCEK VERILER (WinRM)"
    assert layer_header("prometheus") == "PROMETHEUS CANLI METRIKLER"
    assert layer_header("ssh") == "SUNUCULARDAN ALINAN GERCEK VERILER (SSH)"
    assert layer_header("winrm") == "SUNUCULARDAN ALINAN GERCEK VERILER (WinRM)"


def test_wrap_layer_produces_legacy_format():
    out = wrap_layer("linux_ssh", "web01: uptime 10 gün")
    assert out == "LINUX SUNUCULARDAN ALINAN GERCEK VERILER (SSH):\nweb01: uptime 10 gün"


def test_wrap_layer_empty_body_returns_empty():
    assert wrap_layer("linux_ssh", "") == ""
    assert wrap_layer("linux_ssh", "   ") == ""


def test_wrap_layer_unknown_key_uses_upper_fallback():
    out = wrap_layer("mystery_source", "veri")
    assert out == "MYSTERY_SOURCE:\nveri"
