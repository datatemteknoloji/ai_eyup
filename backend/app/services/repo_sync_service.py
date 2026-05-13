"""
Local Repository Senkronizasyon Servisi
RPM/DEB repomd.xml tabanlı mirror sistemi.
  - repomd.xml çek → primary.xml parse et → paket listesi al
  - RPM dosyalarını parallel indir
  - repodata'yı mirror'la (istemciler doğrudan kullanabilir)
  - FastAPI StaticFiles üzerinden serve et
"""
import os
import gzip
import lzma
import time
import shutil
import hashlib
import logging
import uuid as _uuid
import requests
import xml.etree.ElementTree as ET
from typing import Optional, List, Tuple, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

REPOS_BASE = "/app/repos"

# İptal edilen job ID'leri — thread'ler bu seti periyodik olarak kontrol eder
_cancelled_jobs: set[int] = set()


def cancel_job(job_id: int) -> None:
    """Bir sync job'ını iptal et (thread bir sonraki kontrol noktasında durur)."""
    _cancelled_jobs.add(job_id)


def _is_cancelled(job_id: int) -> bool:
    return job_id in _cancelled_jobs
DOWNLOAD_WORKERS = 4
CHUNK_SIZE = 1 * 1024 * 1024  # 1 MB

# XML namespaces
NS_COMMON  = "http://linux.duke.edu/metadata/common"
NS_RPM     = "http://linux.duke.edu/metadata/rpm"
NS_REPO    = "http://linux.duke.edu/metadata/repo"


# ─── Auth helpers ─────────────────────────────────────────────────────────────

RHSM_API = "https://subscription.rhsm.redhat.com/subscription"


def fetch_rhsm_certs(username: str, password: str) -> dict:
    """
    Red Hat RHSM API üzerinden kullanıcı adı/şifre ile sertifika alır.
    SCA (Simple Content Access) ve klasik subscription modlarını destekler.

    SCA modu: attach gerekmez, consumers/{uuid}/certificates endpoint'i
              büyük bir SCA sertifikası döner (CDN erişimi için yeterli).
    Klasik  : attach → entitlements endpoint'inden sertifika alır.

    Döner: {"cert": "...", "key": "...", "consumer_uuid": "..."}
    """
    import urllib3
    urllib3.disable_warnings()

    sess = requests.Session()
    sess.verify  = False
    sess.auth    = (username, password)
    sess.headers.update({
        "Content-Type": "application/json",
        "Accept":        "application/json",
    })

    # 1. Consumer kaydet
    consumer_name = f"datatem-repo-mgr-{_uuid.uuid4().hex[:8]}"
    r = sess.post(
        f"{RHSM_API}/consumers",
        json={
            "name": consumer_name,
            "type": {"id": "1", "label": "system", "manifest": False},
            "facts": {"system.certificate_version": "3.3", "uname.machine": "x86_64"},
        },
        timeout=30,
    )
    if r.status_code == 401:
        raise ValueError("Kullanıcı adı veya şifre hatalı")
    if r.status_code == 403:
        raise ValueError("Bu hesabın RHSM erişim yetkisi yok")
    r.raise_for_status()

    consumer_uuid = r.json()["uuid"]
    logger.info(f"RHSM consumer oluşturuldu: {consumer_uuid}")

    # 2. Klasik modda entitlement attach dene
    cert_text = None
    key_text  = None

    r2 = sess.post(
        f"{RHSM_API}/consumers/{consumer_uuid}/entitlements?auto=true",
        timeout=30,
    )
    if r2.status_code == 200:
        entitlements = r2.json()
        if entitlements:
            cert_info = entitlements[0]["certificates"][0]
            cert_text = cert_info["cert"]
            key_text  = cert_info["key"]
            logger.info("RHSM klasik mod: entitlement sertifikası alındı")

    # 3. SCA modu — attach başarısızsa veya boşsa consumers/{uuid}/certificates dene
    if not cert_text:
        logger.info("RHSM SCA modu deneniyor...")
        r3 = sess.get(
            f"{RHSM_API}/consumers/{consumer_uuid}/certificates",
            timeout=30,
        )
        if r3.status_code == 200:
            certs = r3.json()
            if certs:
                # En büyük sertifikayı seç (SCA cert genellikle çok büyüktür)
                certs_sorted = sorted(certs, key=lambda c: len(c.get("cert", "")), reverse=True)
                cert_text = certs_sorted[0]["cert"]
                key_text  = certs_sorted[0]["key"]
                logger.info(f"RHSM SCA sertifikası alındı: {len(cert_text)} byte")

    if not cert_text:
        raise ValueError(
            "RHSM sertifikası alınamadı. "
            "Red Hat hesabınızda aktif RHEL aboneliği olduğundan emin olun: "
            "https://access.redhat.com/management/subscriptions"
        )

    return {
        "cert":          cert_text,
        "key":           key_text,
        "consumer_uuid": consumer_uuid,
    }


def _build_session(repo) -> requests.Session:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    sess = requests.Session()
    sess.headers["User-Agent"] = "datatem-repo-manager/1.0"
    # Varsayılan olarak SSL doğrulamasını kapat:
    # Kurumsal proxy veya container CA trust store eksikliğinde hata çıkmasın.
    sess.verify = False

    if repo.auth_type == "basic" and repo.username:
        sess.auth = (repo.username, repo.password or "")

    elif repo.auth_type == "ssl_cert" and repo.ssl_cert and repo.ssl_key:
        import tempfile
        cert_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem", mode="w")
        key_file  = tempfile.NamedTemporaryFile(delete=False, suffix=".key", mode="w")
        cert_file.write(repo.ssl_cert); cert_file.close()
        key_file.write(repo.ssl_key);   key_file.close()
        sess.cert = (cert_file.name, key_file.name)

        if repo.ssl_ca:
            ca_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem", mode="w")
            ca_file.write(repo.ssl_ca); ca_file.close()
            sess.verify = ca_file.name
        # ssl_ca yoksa verify=False kalır (zaten üstte set edildi)

    return sess


def _decompress(data: bytes, filename: str) -> bytes:
    """gz / xz / zst / raw formatlarını aç."""
    if filename.endswith(".gz"):
        return gzip.decompress(data)
    if filename.endswith(".xz"):
        return lzma.decompress(data)
    if filename.endswith(".zst"):
        try:
            import zstandard as zstd
            return zstd.ZstdDecompressor().decompress(data, max_output_size=500_000_000)
        except ImportError:
            raise RuntimeError("zstandard paketi yok; pip install zstandard")
    return data  # uncompressed


# ─── Metadata parsing ─────────────────────────────────────────────────────────

def _fetch_repomd(sess: requests.Session, base_url: str) -> ET.Element:
    url = base_url.rstrip("/") + "/repodata/repomd.xml"
    r = sess.get(url, timeout=30)
    r.raise_for_status()
    return ET.fromstring(r.content)


def _find_primary_location(repomd_root: ET.Element) -> Optional[str]:
    """repomd.xml'den primary veritabanının göreli URL'sini döner."""
    for data in repomd_root.findall(f"{{{NS_REPO}}}data"):
        if data.get("type") == "primary":
            loc = data.find(f"{{{NS_REPO}}}location")
            if loc is not None:
                return loc.get("href")
    # Namespace'siz fallback
    for data in repomd_root.findall("data"):
        if data.get("type") == "primary":
            loc = data.find("location")
            if loc is not None:
                return loc.get("href")
    return None


def _parse_primary(xml_bytes: bytes) -> List[Dict]:
    """primary.xml içeriğini parse ederek paket listesi döner."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        # Bazen UTF-8 BOM veya encoding sorunu olabilir
        root = ET.fromstring(xml_bytes.decode("utf-8", errors="replace").encode("utf-8"))

    packages = []
    ns = f"{{{NS_COMMON}}}"

    for pkg in root.iter(f"{ns}package"):
        if pkg.get("type") != "rpm":
            continue

        name_el    = pkg.find(f"{ns}name")
        arch_el    = pkg.find(f"{ns}arch")
        ver_el     = pkg.find(f"{ns}version")
        sum_el     = pkg.find(f"{ns}summary")
        size_el    = pkg.find(f"{ns}size")
        loc_el     = pkg.find(f"{ns}location")
        chk_el     = pkg.find(f"{ns}checksum")

        if name_el is None or ver_el is None or loc_el is None:
            continue

        packages.append({
            "name":         name_el.text or "",
            "arch":         arch_el.text  if arch_el  is not None else "noarch",
            "epoch":        ver_el.get("epoch", "0"),
            "version":      ver_el.get("ver", ""),
            "release":      ver_el.get("rel", ""),
            "summary":      (sum_el.text or "")[:500] if sum_el is not None else "",
            "size_bytes":   int(size_el.get("package", 0)) if size_el is not None else 0,
            "location":     loc_el.get("href", ""),
            "checksum":     chk_el.text or "" if chk_el is not None else "",
            "checksum_type": chk_el.get("type", "sha256") if chk_el is not None else "sha256",
        })
    return packages


# ─── Download helpers ─────────────────────────────────────────────────────────

def _verify_checksum(path: str, expected: str, ctype: str) -> bool:
    if not expected:
        return True
    algo = hashlib.new(ctype) if ctype in hashlib.algorithms_available else hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            algo.update(chunk)
    return algo.hexdigest() == expected


def _download_file(sess: requests.Session, url: str, dest: str) -> bool:
    """Tek dosyayı indir. Başarı durumunda True döner."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        with sess.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(dest + ".part", "wb") as fh:
                for chunk in r.iter_content(CHUNK_SIZE):
                    fh.write(chunk)
        os.replace(dest + ".part", dest)
        return True
    except Exception as exc:
        logger.debug(f"Download failed {url}: {exc}")
        if os.path.exists(dest + ".part"):
            os.remove(dest + ".part")
        return False


def _copy_repodata(sess: requests.Session, base_url: str,
                   repomd_root: ET.Element, local_path: str) -> None:
    """repomd.xml ve tüm metadata dosyalarını local'e kopyala."""
    repodata_dir = os.path.join(local_path, "repodata")
    os.makedirs(repodata_dir, exist_ok=True)

    # repomd.xml kaydet
    url = base_url.rstrip("/") + "/repodata/repomd.xml"
    _download_file(sess, url, os.path.join(repodata_dir, "repomd.xml"))

    # Tüm data elementlerinin href'lerini indir
    hrefs = set()
    for data in list(repomd_root.iter()):
        if data.tag.endswith("}location") or data.tag == "location":
            href = data.get("href", "")
            if href:
                hrefs.add(href)

    for href in hrefs:
        url  = base_url.rstrip("/") + "/" + href.lstrip("/")
        dest = os.path.join(local_path, href.lstrip("/"))
        if not os.path.exists(dest):
            _download_file(sess, url, dest)


# ─── Main sync function (runs in thread) ──────────────────────────────────────

def run_repo_sync(repo_id: int, job_id: int,
                  sync_metadata_only: bool = False) -> None:
    """
    Background thread'de çalışır.
    sync_metadata_only=True → sadece package listesini DB'ye yazar, RPM indirmez.
    """
    from app.core.database import SessionLocal
    from app.models.repository import RepoSource, RepoSyncJob, RepoPackage

    db = SessionLocal()
    log_lines: List[str] = []

    def log(msg: str):
        log_lines.append(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}")
        logger.info(f"REPO#{repo_id} {msg}")

    try:
        repo: RepoSource = db.query(RepoSource).filter_by(id=repo_id).first()
        job: RepoSyncJob  = db.query(RepoSyncJob).filter_by(id=job_id).first()
        if not repo or not job:
            return

        job.status     = "running"
        job.started_at = datetime.now(timezone.utc)
        repo.sync_status = "syncing"
        db.commit()

        local_path = os.path.join(REPOS_BASE, repo.name)
        os.makedirs(local_path, exist_ok=True)
        repo.local_path = local_path

        log(f"Senkronizasyon başlatıldı: {repo.display_name}")
        log(f"Kaynak: {repo.base_url}")

        # ── RHEL: basic auth varsa RHSM sertifikası otomatik al ────────────
        if (
            repo.repo_type == "rhel"
            and repo.auth_type == "basic"
            and repo.username
            and not repo.ssl_cert
        ):
            log("RHEL repo — RHSM API ile sertifika alınıyor...")
            try:
                certs = fetch_rhsm_certs(repo.username, repo.password or "")
                repo.ssl_cert  = certs["cert"]
                repo.ssl_key   = certs["key"]
                repo.auth_type = "ssl_cert"
                db.commit()
                log("RHSM sertifikası başarıyla alındı ve kaydedildi")
            except Exception as cert_exc:
                raise RuntimeError(f"RHSM sertifikası alınamadı: {cert_exc}")

        sess = _build_session(repo)

        # ── 1. repomd.xml ──────────────────────────────────────────────────
        log("repomd.xml indiriliyor...")
        try:
            repomd_root = _fetch_repomd(sess, repo.base_url)
        except Exception as exc:
            raise RuntimeError(f"repomd.xml alınamadı: {exc}")

        # ── 2. primary.xml bul ve parse et ─────────────────────────────────
        primary_href = _find_primary_location(repomd_root)
        if not primary_href:
            raise RuntimeError("primary veritabanı repomd.xml'de bulunamadı")

        primary_url = repo.base_url.rstrip("/") + "/" + primary_href.lstrip("/")
        log(f"Paket kataloğu indiriliyor: {primary_href}")
        r = sess.get(primary_url, timeout=120)
        r.raise_for_status()
        raw_xml = _decompress(r.content, primary_href)

        log("Paket listesi parse ediliyor...")
        pkg_dicts = _parse_primary(raw_xml)
        log(f"{len(pkg_dicts)} paket bulundu")

        job.total_packages = len(pkg_dicts)
        db.commit()

        # ── 3. Eski paket kayıtlarını temizle, yenilerini ekle ─────────────
        db.query(RepoPackage).filter_by(repo_id=repo_id).delete()
        db.commit()

        existing_local = set()
        for pd in pkg_dicts:
            dest = os.path.join(local_path, pd["location"].lstrip("/"))
            downloaded = os.path.exists(dest)
            if downloaded:
                existing_local.add(pd["location"])
            pkg = RepoPackage(
                repo_id=repo_id,
                name=pd["name"], epoch=pd["epoch"],
                version=pd["version"], release=pd["release"],
                arch=pd["arch"], summary=pd["summary"],
                size_bytes=pd["size_bytes"], location=pd["location"],
                checksum=pd["checksum"], checksum_type=pd["checksum_type"],
                downloaded=downloaded,
                local_path=dest if downloaded else None,
            )
            db.add(pkg)

        db.commit()
        log(f"{len(existing_local)} paket zaten mevcut (indirilmeyecek)")

        repo.package_count = len(pkg_dicts)
        job.skipped_packages = len(existing_local)

        if sync_metadata_only:
            log("Yalnızca metadata modu — RPM indirilmeyecek")
            _copy_repodata(sess, repo.base_url, repomd_root, local_path)
            job.synced_packages = len(existing_local)
            job.status     = "completed"
            job.completed_at = datetime.now(timezone.utc)
            repo.sync_status = "synced"
            repo.last_sync   = datetime.now(timezone.utc)
            job.log = "\n".join(log_lines)
            db.commit()
            return

        # ── 4. RPM'leri parallel indir ─────────────────────────────────────
        to_download = [pd for pd in pkg_dicts if pd["location"] not in existing_local]
        log(f"{len(to_download)} yeni paket indirilecek...")

        synced = len(existing_local)
        failed = 0

        def _dl(pd: dict) -> Tuple[bool, str]:
            url  = repo.base_url.rstrip("/") + "/" + pd["location"].lstrip("/")
            dest = os.path.join(local_path, pd["location"].lstrip("/"))
            ok   = _download_file(sess, url, dest)
            if ok and pd.get("checksum"):
                ok = _verify_checksum(dest, pd["checksum"], pd.get("checksum_type","sha256"))
            return ok, pd["location"]

        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
            futures = {pool.submit(_dl, pd): pd for pd in to_download}
            for future in as_completed(futures):
                # ── İptal kontrolü ────────────────────────────────────────
                if _is_cancelled(job_id):
                    pool.shutdown(wait=False, cancel_futures=True)
                    log("İptal edildi — kullanıcı tarafından durduruldu")
                    job.status       = "cancelled"
                    job.completed_at = datetime.now(timezone.utc)
                    job.synced_packages = synced
                    job.log          = "\n".join(log_lines)
                    repo.sync_status = "cancelled"
                    repo.last_sync   = datetime.now(timezone.utc)
                    db.commit()
                    _cancelled_jobs.discard(job_id)
                    return
                # ─────────────────────────────────────────────────────────
                ok, loc = future.result()
                if ok:
                    synced += 1
                    db.query(RepoPackage).filter_by(
                        repo_id=repo_id, location=loc
                    ).update({"downloaded": True, "local_path": os.path.join(local_path, loc.lstrip("/"))})
                    if synced % 5 == 0:
                        job.synced_packages = synced
                        db.commit()
                    if synced % 100 == 0:
                        log(f"İlerleme: {synced}/{len(pkg_dicts)}")
                else:
                    failed += 1
                    log(f"HATA: {loc}")

        db.commit()

        # ── 5. repodata kopyala ────────────────────────────────────────────
        log("Metadata kopyalanıyor...")
        _copy_repodata(sess, repo.base_url, repomd_root, local_path)

        # ── 6. Disk kullanımı hesapla ──────────────────────────────────────
        total_bytes = sum(
            os.path.getsize(os.path.join(dp, f))
            for dp, _, filenames in os.walk(local_path)
            for f in filenames
        )
        repo.total_size_mb = total_bytes // (1024 * 1024)

        log(f"Tamamlandı — {synced} başarılı, {failed} hatalı, "
            f"toplam disk: {repo.total_size_mb} MB")

        job.synced_packages  = synced
        job.failed_packages  = failed
        job.status           = "completed" if failed == 0 else "partial"
        job.completed_at     = datetime.now(timezone.utc)
        repo.sync_status     = "synced" if failed == 0 else "partial"
        repo.last_sync       = datetime.now(timezone.utc)
        job.log              = "\n".join(log_lines)
        db.commit()

    except Exception as exc:
        logger.error(f"RepoSync #{repo_id}: {exc}", exc_info=True)
        log_lines.append(f"HATA: {exc}")
        try:
            job  = db.query(RepoSyncJob).filter_by(id=job_id).first()
            repo = db.query(RepoSource).filter_by(id=repo_id).first()
            if job:
                job.status       = "failed"
                job.completed_at = datetime.now(timezone.utc)
                job.log          = "\n".join(log_lines)
            if repo:
                repo.sync_status = "failed"
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


# ─── Client .repo file generator ──────────────────────────────────────────────

def generate_repo_file(repo, server_ip: str, port: int = 8000) -> str:
    """Sunuculara eklenecek .repo dosyası içeriğini üretir."""
    base = f"http://{server_ip}:{port}/repos/{repo.name}"
    lines = [
        f"[{repo.name}]",
        f"name={repo.display_name}",
        f"baseurl={base}/",
        "enabled=1",
        "gpgcheck=0",
        "sslverify=0",
        "",
    ]
    return "\n".join(lines)


def push_repo_file_to_server(server, repo_file_content: str,
                              repo_name: str, global_cred=None) -> dict:
    """
    .repo dosyasını SSH ile sunucuya yaz.
    /etc/yum.repos.d/{repo_name}.repo
    """
    from app.services.package_service import _resolve_creds, _make_client, _run_cmd
    t0 = time.time()
    creds = _resolve_creds(server, global_cred)
    dest  = f"/etc/yum.repos.d/{repo_name}.repo"
    try:
        client = _make_client(creds)
        sudo   = creds.get("sudo_password")
        escaped = repo_file_content.replace("'", "'\\''")
        code, out, err = _run_cmd(
            client,
            f"echo '{escaped}' | tee {dest} > /dev/null && echo OK",
            sudo_pass=sudo, timeout=15,
        )
        client.close()
        return {
            "status":   "success" if code == 0 else "failed",
            "message":  f"{dest} oluşturuldu" if code == 0 else err,
            "duration": round(time.time() - t0, 1),
        }
    except Exception as exc:
        return {"status": "failed", "message": str(exc), "duration": round(time.time() - t0, 1)}
