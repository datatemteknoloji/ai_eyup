"""Kurumsal kimlik: şirket adı / alt başlık / alt bilgi metni (giriş ekranı)."""
import asyncio

import pytest
from fastapi import HTTPException

from app.api import public
from app.api.settings import BrandingRequest, set_branding


def _put(db, **kw):
    return asyncio.run(set_branding(BrandingRequest(**kw), db=db, _admin=None))


def test_defaults_are_empty_so_ui_uses_its_own(isolated_db):
    body = asyncio.run(public.get_branding(db=isolated_db))
    assert body["app_name"] == "ainew"
    assert body["company_name"] == "" and body["tagline"] == "" and body["footer_text"] == ""
    assert body["hero_title"] == "" and body["hero_text"] == ""


def test_save_and_read_back(isolated_db):
    _put(isolated_db, app_name=" Acme  Ops ", company_name="Acme Bilişim", tagline="Konsol", footer_text="© 2026 Acme A.Ş.")
    body = asyncio.run(public.get_branding(db=isolated_db))
    assert body["app_name"] == "Acme  Ops"
    assert body["company_name"] == "Acme Bilişim" and body["footer_text"] == "© 2026 Acme A.Ş."


def test_old_clients_sending_only_app_name_keep_other_fields(isolated_db):
    _put(isolated_db, app_name="A", company_name="Co")
    _put(isolated_db, app_name="B")
    body = asyncio.run(public.get_branding(db=isolated_db))
    assert body["app_name"] == "B" and body["company_name"] == "Co"


def test_empty_string_resets_to_default(isolated_db):
    _put(isolated_db, app_name="A", company_name="Co")
    _put(isolated_db, app_name="A", company_name="")
    assert asyncio.run(public.get_branding(db=isolated_db))["company_name"] == ""


@pytest.mark.parametrize("field,n", [("company_name", 65), ("tagline", 81), ("footer_text", 161), ("hero_title", 121), ("hero_text", 321)])
def test_length_limits(isolated_db, field, n):
    with pytest.raises(HTTPException) as e:
        _put(isolated_db, app_name="A", **{field: "x" * n})
    assert e.value.status_code == 400


def test_newlines_collapsed(isolated_db):
    _put(isolated_db, app_name="A", footer_text="a\n\n  b")
    assert asyncio.run(public.get_branding(db=isolated_db))["footer_text"] == "a b"


def test_hero_title_and_text_editable_and_resettable(isolated_db):
    _put(isolated_db, app_name="A", hero_title="Acme altyapı konsolu", hero_text="Tüm ortamlarınızı\n  tek yerden izleyin.")
    body = asyncio.run(public.get_branding(db=isolated_db))
    assert body["hero_title"] == "Acme altyapı konsolu" and body["hero_text"] == "Tüm ortamlarınızı tek yerden izleyin."
    _put(isolated_db, app_name="A", company_name="Co")                 # eski istemci: hero alanlarına dokunmaz
    assert asyncio.run(public.get_branding(db=isolated_db))["hero_title"] == "Acme altyapı konsolu"
    _put(isolated_db, app_name="A", hero_title="", hero_text="")        # boş = varsayılana dön
    body = asyncio.run(public.get_branding(db=isolated_db))
    assert body["hero_title"] == "" and body["hero_text"] == ""
