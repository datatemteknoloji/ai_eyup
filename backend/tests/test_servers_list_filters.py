"""GET /servers/ — os=linux|other filtresi ve sort_by/sort_dir beyaz listesi.

* Regex testleri DB gerektirmez (aynı kalıp PostgreSQL `~*` ve Python `re.I` ile eşdeğer).
* SQL testleri bir PostgreSQL bağlantısı gerektirir; veri **TEMP tablo** üzerinde, işlem
  sonunda ROLLBACK ile atılır — gerçek `servers` tablosu okunmaz/yazılmaz.
  Veritabanına erişilemezse atlanır.
"""
import re

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import servers as api
from app.models.server import Server

LINUX_RE = re.compile(api.KNOWN_LINUX_OS_TYPE_RE, re.IGNORECASE)

# (os_release_id, os_type) — gerçek envanterden örnekler
KNOWN_LINUX = [
    ("rhel", "Red Hat Enterprise Linux 9.4 (Plow)"),
    ("", "Red Hat Enterprise Linux 9.8 (Plow)"),
    ("", "rhel"),
    ("", "Rocky Linux 9.3 (Blue Onyx)"),
    ("", "AlmaLinux 9.3 (Shamrock Pampas Cat)"),
    ("", "CentOS Stream 9"),
    ("", "Oracle Linux Server 8.9"),
    ("", "ol_8x64"),
    ("", "sles_11"),
    ("", "SUSE Linux Enterprise Server 15 SP5"),
    ("", "Ubuntu 24.04 LTS"),
    ("", "Debian GNU/Linux 12 (bookworm)"),
    ("", "Fedora Linux 40 (Cloud Edition)"),
    ("", "Linux 9.6 CoreOS"),
    ("", "linuxGuest"),
    ("", "LINUX"),
    ("", "VMware Photon OS 5.0"),
    # Kısa ID'ler — os_release_id boş
    ("", "debian"),
    ("", "fedora"),
    ("", "almalinux"),
    ("", "amzn"),
    ("", "opensuse"),
    ("", "photon"),
    ("", "ubuntu"),
    ("", "ol"),
    ("", "opensuse-leap"),
    # os_type anlamsız ama release id dolu
    ("rhel", "sles_11"),
    ("ol", "something-odd"),
    ("almalinux", ""),
]

NOT_LINUX = [
    ("", ""),
    ("", "other"),
    ("", "unknown"),
    ("", "Dropt"),            # serbest metin
    ("", "Solaris 11"),
    ("", "FreeBSD 14"),
    ("", "Olympus 3"),        # %ol% kalıbının yakaladığı yanlış pozitif
    ("", "Protocol Gateway"), # içinde "ol" geçer
    ("", "Microsoft Windows Server 2022 Standard"),
    ("", "windows_2019x64"),
]


def _py_known_linux(release_id: str, os_type: str) -> bool:
    if "windows" in (os_type or "").lower():
        return False
    return bool((release_id or "").strip()) or bool(LINUX_RE.search(os_type or ""))


@pytest.mark.parametrize("release_id,os_type", KNOWN_LINUX)
def test_regex_known_linux(release_id, os_type):
    assert _py_known_linux(release_id, os_type)


@pytest.mark.parametrize("release_id,os_type", NOT_LINUX)
def test_regex_not_linux(release_id, os_type):
    assert not _py_known_linux(release_id, os_type)


def test_no_loose_ol_pattern_in_sql():
    sql = str(api._known_linux_condition().compile(compile_kwargs={"literal_binds": True}))
    assert "%ol%" not in sql.lower()
    assert "isnot" not in sql.lower()


# ── sort_by / sort_dir beyaz liste (DB'siz) ───────────────────────────────────

def test_sort_default_is_hostname_name_then_id():
    order = api._server_list_order_by(None, None)
    rendered = [str(o) for o in order]
    assert "coalesce(servers.hostname, servers.name) ASC" in rendered[0].replace("\n", " ")
    assert "servers.id" in rendered[1]


@pytest.mark.parametrize("col", sorted(api._LIST_SORT_COLUMNS))
def test_sort_whitelist_accepts(col):
    assert api._server_list_order_by(col, "desc")
    assert api._server_list_order_by(col, None)


@pytest.mark.parametrize("bad", ["password", "id; drop table servers", "connection_config", "hostname"])
def test_sort_by_rejects_unknown(bad):
    with pytest.raises(HTTPException) as ei:
        api._server_list_order_by(bad, "asc")
    assert ei.value.status_code == 422


def test_sort_dir_rejects_unknown():
    with pytest.raises(HTTPException) as ei:
        api._server_list_order_by("name", "sideways")
    assert ei.value.status_code == 422


# ── PostgreSQL (TEMP tablo) ───────────────────────────────────────────────────

@pytest.fixture()
def db():
    try:
        from app.core.database import engine

        conn = engine.connect()
    except Exception as exc:  # pragma: no cover - ortam bağımlı
        pytest.skip(f"PostgreSQL erişilemiyor: {exc}")
    trans = conn.begin()
    try:
        # TEMP tablo public.servers'ı gölgeler (pg_temp arama yolunda önce gelir).
        conn.execute(text("CREATE TEMP TABLE servers (LIKE public.servers) ON COMMIT DROP"))
        session = Session(bind=conn)
        yield session
        session.close()
    finally:
        trans.rollback()
        conn.close()


def _add(db: Session, sid: int, name: str, **kw) -> Server:
    s = Server(id=sid, name=name, **kw)
    db.add(s)
    db.flush()
    return s


def _ids(db: Session, os_filter: str) -> set[str]:
    q = api._apply_server_list_filters(db.query(Server), os_filter=os_filter)
    return {s.name for s in q.all()}


def test_sql_os_linux_and_other_partition(db):
    rows = KNOWN_LINUX + NOT_LINUX
    for i, (rid, ot) in enumerate(rows, start=1):
        _add(db, i, f"n{i}", os_release_id=rid or None, os_type=ot or None)
    _add(db, 900, "null-os")  # os_type NULL / release NULL
    _add(db, 901, "ws", os_type="Microsoft Windows Server 2019 Datacenter", os_release_id=None)

    expected_linux = {f"n{i}" for i, (rid, ot) in enumerate(rows, start=1) if _py_known_linux(rid, ot)}
    expected_other = {
        f"n{i}" for i, (rid, ot) in enumerate(rows, start=1)
        if not _py_known_linux(rid, ot) and "windows" not in ot.lower()
    } | {"null-os"}

    linux = _ids(db, "linux")
    other = _ids(db, "other")
    assert linux == expected_linux
    assert other == expected_other
    assert not (linux & other)
    assert "ws" not in linux and "ws" not in other


def test_sql_release_id_empty_string_is_not_known(db):
    _add(db, 1, "empty-rid", os_type="other", os_release_id="")
    _add(db, 2, "blank-rid", os_type="other", os_release_id="  ")
    assert _ids(db, "linux") == set()
    assert _ids(db, "other") == {"empty-rid", "blank-rid"}


def _ordered(db: Session, sort_by, sort_dir):
    q = db.query(Server).order_by(*api._server_list_order_by(sort_by, sort_dir))
    return [s.name for s in q.all()]


def test_sql_sort_ip_numeric_and_nonipv4_last(db):
    _add(db, 1, "a", ip_address="10.0.0.10")
    _add(db, 2, "b", ip_address="10.0.0.9")
    _add(db, 3, "c", ip_address="192.168.1.1")
    _add(db, 4, "d", ip_address="host-without-ip")
    _add(db, 5, "e", ip_address=None)
    asc = _ordered(db, "ip_address", "asc")
    assert asc[:3] == ["b", "a", "c"]
    assert set(asc[3:]) == {"d", "e"}
    desc = _ordered(db, "ip_address", "desc")
    assert desc[:3] == ["c", "a", "b"]
    assert set(desc[3:]) == {"d", "e"}


@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_sql_sort_ip_invalid_values_do_not_error_and_go_last(db, direction):
    # 300.1.1.1 / 999.0.0.1 ::inet cast'inde hata verirdi (500); artık IPv4 sayılmaz, sona gider.
    _add(db, 1, "ok-b", ip_address="10.0.0.2")
    _add(db, 2, "ok-a", ip_address="10.0.0.1")
    _add(db, 3, "bad-300", ip_address="300.1.1.1")
    _add(db, 4, "bad-999", ip_address="999.0.0.1")
    _add(db, 5, "bad-abc", ip_address="abc")
    _add(db, 6, "bad-256", ip_address="1.2.3.256")
    _add(db, 7, "empty", ip_address="")
    _add(db, 8, "null", ip_address=None)
    order = _ordered(db, "ip_address", direction)  # hata fırlatmamalı
    valid = order[:2]
    assert valid == (["ok-a", "ok-b"] if direction == "asc" else ["ok-b", "ok-a"])
    assert set(order[2:]) == {"bad-300", "bad-999", "bad-abc", "bad-256", "empty", "null"}


@pytest.mark.parametrize("ip,ok", [
    ("0.0.0.0", True), ("10.128.0.25", True), ("255.255.255.255", True), ("192.168.1.1", True),
    ("256.1.1.1", False), ("300.1.1.1", False), ("999.0.0.1", False), ("1.2.3", False),
    ("1.2.3.4.5", False), ("abc", False), ("", False), ("01.2.3.4", False),
])
def test_ipv4_regex(ip, ok):
    assert bool(re.match(api._IPV4_RE, ip)) is ok


def test_sql_sort_status_severity_order(db):
    for i, st in enumerate(["OFFLINE", "CRITICAL", "ONLINE", "WARNING", "UNKNOWN"], start=1):
        _add(db, i, st.lower(), status=st)
    assert _ordered(db, "status", "asc") == ["online", "warning", "critical", "offline", "unknown"]
    assert _ordered(db, "status", "desc") == ["unknown", "offline", "critical", "warning", "online"]


def test_sql_sort_numeric_columns_and_name(db):
    _add(db, 1, "b-host", hostname="b-host", cpu_cores=8, memory_gb=16)
    _add(db, 2, "a-host", hostname="A-Host", cpu_cores=2, memory_gb=64)
    _add(db, 3, "c-host", hostname=None, cpu_cores=None, memory_gb=None)
    assert _ordered(db, "cpu_cores", "desc")[:2] == ["b-host", "a-host"]
    assert _ordered(db, "memory_gb", "asc")[-1] == "a-host"
    assert _ordered(db, "name", "asc") == ["a-host", "b-host", "c-host"]
    assert _ordered(db, "name", "desc") == ["c-host", "b-host", "a-host"]


def test_sql_default_order_unchanged(db):
    _add(db, 1, "zeta", hostname="beta")
    _add(db, 2, "alpha", hostname=None)
    _add(db, 3, "gamma", hostname="gamma")
    # COALESCE(hostname, name): alpha, beta(zeta), gamma
    assert _ordered(db, None, None) == ["alpha", "zeta", "gamma"]
