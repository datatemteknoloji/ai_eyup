"""
RHSM Senkronizasyon Servisi
subscription-manager + reposync tabanlı RPM mirror.

Akış:
  1. SSH ile mirror host'a bağlan (varsayılan: 127.0.0.1 = yönetim sunucusu)
  2. subscription-manager durumunu kontrol et
  3. Gerekiyorsa register et + subscription attach et
  4. repo'yu enable et
  5. reposync ile paketleri host'taki dizine indir
  6. İndirilen paket sayısını DB'ye yaz
"""
import io
import os
import time
import logging
import paramiko
from datetime import datetime, timezone
from typing import Optional

from app.services.ssh_connect import connect_ssh

logger = logging.getLogger(__name__)

# repo_sync_service'teki aynı iptal setini import et
from app.services.repo_sync_service import cancel_job, _is_cancelled


# ─── SSH helper ───────────────────────────────────────────────────────────────

def _connect(host: str, port: int, username: str,
             password: Optional[str], private_key: Optional[str]) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    pkey = None
    if private_key:
        for cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                pkey = cls.from_private_key(io.StringIO(private_key))
                break
            except Exception:
                pass

    connect_ssh(
        client,
        hostname=host, username=username, port=port,
        password=password, pkey=pkey, timeout=15,
    )

    return client


def _run(client: paramiko.SSHClient, cmd: str,
         sudo_pass: Optional[str] = None, timeout: int = 600) -> tuple[int, str, str]:
    """Komutu çalıştırır. (exit_code, stdout, stderr) döner.
    Şifre komut dizisine gömülmez; stdin üzerinden gönderilir.
    """
    actual_cmd = f"sudo -S sh -c {_q(cmd)}" if sudo_pass else cmd
    stdin, stdout, stderr = client.exec_command(actual_cmd, timeout=timeout, get_pty=False)
    if sudo_pass:
        stdin.write(sudo_pass + "\n")
        stdin.flush()
        stdin.close()
    out  = stdout.read().decode("utf-8", errors="replace")
    err  = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def _q(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


# ─── Main sync function ───────────────────────────────────────────────────────

def run_rhsm_sync(repo_id: int, job_id: int) -> None:
    """
    Background thread'de çalışır.
    SSH ile mirror host'a bağlanır, subscription-manager + reposync çalıştırır.
    """
    from app.core.database import ThreadSessionLocal as SessionLocal
    from app.models.repository import RepoSource, RepoSyncJob

    db = SessionLocal()
    log_lines: list[str] = []

    def log(msg: str, level: str = "INFO"):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        log_lines.append(line)
        getattr(logger, level.lower(), logger.info)(f"RHSM#{repo_id} {msg}")
        try:
            j = db.query(RepoSyncJob).filter_by(id=job_id).first()
            if j:
                j.log = "\n".join(log_lines[-100:])
                db.commit()
        except Exception:
            pass

    try:
        repo: RepoSource = db.query(RepoSource).filter_by(id=repo_id).first()
        job: RepoSyncJob  = db.query(RepoSyncJob).filter_by(id=job_id).first()
        if not repo or not job:
            return

        job.status       = "running"
        job.started_at   = datetime.now(timezone.utc)
        repo.sync_status = "syncing"
        db.commit()

        if not repo.rhsm_repo_id:
            raise ValueError("rhsm_repo_id tanımlı değil")

        # ── SSH bağlantısı ─────────────────────────────────────────────────
        host     = repo.mirror_host or "127.0.0.1"
        port     = repo.mirror_port or 22
        user     = repo.mirror_username or "root"
        passwd   = repo.mirror_password
        key      = repo.mirror_key

        log(f"SSH bağlanılıyor: {user}@{host}:{port}")
        client = _connect(host, port, user, passwd, key)
        log("SSH bağlantısı kuruldu")

        sudo = passwd  # sudo için şifreyi kullan

        # ── 1. subscription-manager kurulu mu? ────────────────────────────
        code, _, _ = _run(client, "command -v subscription-manager", timeout=10)
        if code != 0:
            log("subscription-manager bulunamadı, yükleniyor...")
            code, out, err = _run(client,
                "dnf install -y subscription-manager 2>&1 || "
                "yum install -y subscription-manager 2>&1",
                sudo_pass=sudo, timeout=120)
            if code != 0:
                raise RuntimeError(f"subscription-manager yüklenemedi: {err}")
            log("subscription-manager yüklendi")

        # ── 2. dnf-utils (reposync) kurulu mu? ────────────────────────────
        code, _, _ = _run(client, "command -v reposync || dnf reposync --help", timeout=10)
        if code != 0:
            log("dnf-utils yükleniyor (reposync için)...")
            _run(client,
                "dnf install -y dnf-utils 2>&1 || yum install -y yum-utils 2>&1",
                sudo_pass=sudo, timeout=120)
            log("dnf-utils yüklendi")

        # ── 3. Subscription durumunu kontrol et ───────────────────────────
        code, out, _ = _run(client, "subscription-manager status 2>&1", sudo_pass=sudo, timeout=30)
        already_registered = "Current" in out or "Simple Content Access" in out

        if not already_registered:
            if not repo.username or not repo.password:
                raise ValueError(
                    "Red Hat kullanıcı adı/şifresi gerekli (repo'da kayıtlı olmalı). "
                    "Lütfen repo ayarlarında username/password girin."
                )
            log("Red Hat aboneliğine kayıt olunuyor...")
            code, out, err = _run(client,
                f"subscription-manager register --username={_q(repo.username)} "
                f"--password={_q(repo.password)} --auto-attach --force 2>&1",
                sudo_pass=sudo, timeout=120)
            if code != 0 and "already registered" not in out.lower():
                raise RuntimeError(f"subscription-manager register başarısız: {out} {err}")
            log("Kayıt başarılı")

            log("Subscription ekleniyor...")
            code, out, err = _run(client,
                "subscription-manager attach --auto 2>&1",
                sudo_pass=sudo, timeout=60)
            log(f"Attach: {out.strip()[:200]}")
        else:
            log("Abonelik zaten aktif")

        # ── 4. Repo'yu enable et ──────────────────────────────────────────
        log(f"Repo aktifleştiriliyor: {repo.rhsm_repo_id}")
        code, out, err = _run(client,
            f"subscription-manager repos --enable={repo.rhsm_repo_id} 2>&1",
            sudo_pass=sudo, timeout=30)
        if code != 0:
            # Simple Content Access modunda --enable gerekmeyebilir
            if "not found" in out.lower() or "not found" in err.lower():
                raise RuntimeError(
                    f"Repo ID bulunamadı: {repo.rhsm_repo_id}. "
                    f"Mevcut repolar için: subscription-manager repos --list"
                )
            log(f"Repo enable uyarısı (devam ediliyor): {out[:200]}", "warning")
        else:
            log(f"Repo aktif: {repo.rhsm_repo_id}")

        # ── İptal kontrolü ────────────────────────────────────────────────
        if _is_cancelled(job_id):
            client.close()
            log("İptal edildi — kullanıcı tarafından durduruldu")
            job.status = "cancelled"; repo.sync_status = "cancelled"
            job.completed_at = datetime.now(timezone.utc)
            job.log = "\n".join(log_lines); db.commit()
            from app.services.repo_sync_service import _cancelled_jobs
            _cancelled_jobs.discard(job_id)
            return

        # ── 5. İndirme dizini hazırla ─────────────────────────────────────
        download_base = repo.mirror_download_path or "/var/lib/server_management/repos"
        repo_download_path = os.path.join(download_base, repo.name)
        _run(client, f"mkdir -p {repo_download_path}", sudo_pass=sudo, timeout=15)

        # ── 6. reposync ───────────────────────────────────────────────────
        log(f"reposync başlatılıyor → {repo_download_path}")
        log("Bu işlem büyük repolar için uzun sürebilir (GB'larca veri)...")

        # --newest-only: sadece en güncel versiyonu al
        # --delete: yerel'de olmayan eski paketleri sil
        reposync_cmd = (
            f"reposync --repoid={repo.rhsm_repo_id} "
            f"--download-path={repo_download_path} "
            f"--newest-only --delete 2>&1 || "
            f"dnf reposync --repoid={repo.rhsm_repo_id} "
            f"--download-path={repo_download_path} "
            f"--newest-only --delete 2>&1"
        )

        # reposync uzun sürebilir — 6 saat timeout
        code, out, err = _run(client, reposync_cmd, sudo_pass=sudo, timeout=21600)

        if code != 0:
            log(f"reposync hata kodu: {code}", "warning")
            log(f"Çıktı: {out[-1000:]}", "warning")

        # İndirilen paket sayısını say
        count_code, count_out, _ = _run(client,
            f"find {repo_download_path} -name '*.rpm' | wc -l", timeout=30)
        try:
            pkg_count = int(count_out.strip())
        except ValueError:
            pkg_count = 0

        # Disk kullanımı
        _, du_out, _ = _run(client,
            f"du -sm {repo_download_path} 2>/dev/null | awk '{{print $1}}'", timeout=30)
        try:
            size_mb = int(du_out.strip())
        except ValueError:
            size_mb = 0

        client.close()

        log(f"Tamamlandı: {pkg_count} RPM, {size_mb} MB")

        job.synced_packages  = pkg_count
        job.total_packages   = pkg_count
        job.status           = "completed" if code == 0 else "partial"
        job.completed_at     = datetime.now(timezone.utc)

        repo.package_count   = pkg_count
        repo.total_size_mb   = size_mb
        repo.sync_status     = "synced" if code == 0 else "partial"
        repo.last_sync       = datetime.now(timezone.utc)
        repo.local_path      = f"/app/repos/{repo.name}"

        job.log = "\n".join(log_lines)
        db.commit()

    except Exception as exc:
        logger.error(f"RHSM sync #{repo_id}: {exc}", exc_info=True)
        log_lines.append(f"HATA: {exc}")
        try:
            repo = db.query(RepoSource).filter_by(id=repo_id).first()
            job  = db.query(RepoSyncJob).filter_by(id=job_id).first()
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


# ─── Subscription-manager bilgi sorguları ─────────────────────────────────────

def list_available_repos(host: str, port: int, username: str,
                         password: Optional[str], key: Optional[str],
                         sudo_pass: Optional[str] = None) -> list[dict]:
    """
    Mirror host'taki aktif abonelikte mevcut repo'ları listeler.
    subscription-manager repos --list çıktısını parse eder.
    """
    try:
        client = _connect(host, port, username, password, key)
        code, out, err = _run(client,
            "subscription-manager repos --list 2>&1",
            sudo_pass=sudo_pass or password, timeout=60)
        client.close()

        repos = []
        current: dict = {}
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Repo ID:"):
                if current:
                    repos.append(current)
                current = {"id": line.split(":", 1)[1].strip()}
            elif line.startswith("Repo Name:") and current:
                current["name"] = line.split(":", 1)[1].strip()
            elif line.startswith("Enabled:") and current:
                current["enabled"] = line.split(":", 1)[1].strip() == "1"
        if current:
            repos.append(current)

        return repos
    except Exception as e:
        logger.warning(f"list_available_repos: {e}")
        return []


def check_subscription_status(host: str, port: int, username: str,
                               password: Optional[str], key: Optional[str],
                               sudo_pass: Optional[str] = None) -> dict:
    """Mirror host'taki abonelik durumunu döner."""
    try:
        client = _connect(host, port, username, password, key)
        code, out, _ = _run(client, "subscription-manager status 2>&1",
                            sudo_pass=sudo_pass or password, timeout=30)
        _, identity_out, _ = _run(client, "subscription-manager identity 2>&1",
                                  sudo_pass=sudo_pass or password, timeout=15)
        client.close()
        return {
            "registered": code == 0 and "Current" in out,
            "status":     out.strip()[:500],
            "identity":   identity_out.strip()[:200],
        }
    except Exception as e:
        return {"registered": False, "status": str(e), "identity": ""}
