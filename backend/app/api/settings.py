"""
Settings API - Global Credentials CRUD + Apply to Servers
"""
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from app.core.database import get_db, ThreadSessionLocal
from app.core.auth import get_current_user, require_role
from app.models.credential import GlobalCredential
from app.models.server import Server
from app.models.app_settings import AppSettings
from app.models.user import User
from app.core.encryption import encrypt_secret, decrypt_secret

logger = logging.getLogger(__name__)
router = APIRouter()

# SSH Test & Update — arka plan job + progress (poll). Wave 6: Redis + bellek fallback.
_ssh_test_jobs: Dict[str, Dict[str, Any]] = {}
_ssh_test_lock = threading.Lock()
_SSH_TEST_JOB_TTL_SEC = 3600
_SSH_TEST_REDIS_PREFIX = "ainew:ssh_test:"


def _ssh_job_save(job_id: str, job: Dict[str, Any]) -> None:
    with _ssh_test_lock:
        _ssh_test_jobs[job_id] = job
    try:
        from app.core.redis_client import get_redis
        import json as _json

        r = get_redis()
        if r is not None:
            r.setex(
                f"{_SSH_TEST_REDIS_PREFIX}{job_id}",
                _SSH_TEST_JOB_TTL_SEC,
                _json.dumps(job, ensure_ascii=False, default=str),
            )
    except Exception:
        pass


def _ssh_job_get(job_id: str) -> Optional[Dict[str, Any]]:
    try:
        from app.core.redis_client import get_redis
        import json as _json

        r = get_redis()
        if r is not None:
            raw = r.get(f"{_SSH_TEST_REDIS_PREFIX}{job_id}")
            if raw:
                data = _json.loads(raw)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    with _ssh_test_lock:
        j = _ssh_test_jobs.get(job_id)
        return dict(j) if j else None


def _ssh_job_update(job_id: str, mutator) -> None:
    job = _ssh_job_get(job_id)
    if not job:
        return
    mutator(job)
    _ssh_job_save(job_id, job)


# ─── Schemas ──────────────────────────────────────────

class CredentialCreate(BaseModel):
    name: str
    username: str
    password: str = ""
    private_key: str = ""
    sudo_password: str = ""
    port: int = 22

class CredentialUpdate(BaseModel):
    name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    private_key: Optional[str] = None
    sudo_password: Optional[str] = None
    port: Optional[int] = None

class CredentialResponse(BaseModel):
    id: int
    name: str
    username: str
    port: int
    has_password: bool
    has_private_key: bool
    is_default: bool

class ApplyCredentialRequest(BaseModel):
    server_ids: Optional[List[int]] = None
    set_ai_ready: bool = True


def _cred_to_response(c: GlobalCredential) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "username": c.username,
        "port": c.port,
        "has_password": bool(c.password),
        "has_private_key": bool(c.private_key),
        "is_default": c.is_default
    }


# ─── CRUD ─────────────────────────────────────────────

@router.get("/credentials/", response_model=List[CredentialResponse])
async def list_credentials(db: Session = Depends(get_db)):
    """Tüm global credential'ları listele"""
    creds = db.query(GlobalCredential).order_by(GlobalCredential.is_default.desc(), GlobalCredential.name).all()
    return [_cred_to_response(c) for c in creds]


@router.post("/credentials/", response_model=CredentialResponse, status_code=201)
async def create_credential(data: CredentialCreate, db: Session = Depends(get_db)):
    """Yeni global credential oluştur"""
    existing = db.query(GlobalCredential).filter(GlobalCredential.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"'{data.name}' adında credential zaten var")

    is_first = db.query(GlobalCredential).count() == 0
    cred = GlobalCredential(
        name=data.name,
        username=data.username,
        password=encrypt_secret(data.password) or None,
        private_key=encrypt_secret(data.private_key) or None,
        sudo_password=encrypt_secret(data.sudo_password) or None,
        port=data.port,
        is_default=is_first
    )
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return _cred_to_response(cred)


@router.get("/credentials/{credential_id}", response_model=CredentialResponse)
async def get_credential(credential_id: int, db: Session = Depends(get_db)):
    """Tek credential getir"""
    cred = db.query(GlobalCredential).filter(GlobalCredential.id == credential_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential bulunamadı")
    return _cred_to_response(cred)


@router.put("/credentials/{credential_id}", response_model=CredentialResponse)
async def update_credential(credential_id: int, data: CredentialUpdate, db: Session = Depends(get_db)):
    """Global credential güncelle"""
    cred = db.query(GlobalCredential).filter(GlobalCredential.id == credential_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential bulunamadı")

    if data.name is not None:
        cred.name = data.name
    if data.username is not None:
        cred.username = data.username
    if data.password is not None and data.password != "":
        cred.password = encrypt_secret(data.password)
    if data.private_key is not None:
        cred.private_key = encrypt_secret(data.private_key)
    if data.sudo_password is not None:
        cred.sudo_password = encrypt_secret(data.sudo_password)
    if data.port is not None:
        cred.port = data.port

    db.commit()
    db.refresh(cred)
    return _cred_to_response(cred)


@router.delete("/credentials/{credential_id}", status_code=204)
async def delete_credential(credential_id: int, db: Session = Depends(get_db)):
    """Global credential sil"""
    cred = db.query(GlobalCredential).filter(GlobalCredential.id == credential_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential bulunamadı")
    db.delete(cred)
    db.commit()


@router.post("/credentials/{credential_id}/set-default")
async def set_default_credential(credential_id: int, db: Session = Depends(get_db)):
    """Bir credential'ı varsayılan olarak ayarla"""
    cred = db.query(GlobalCredential).filter(GlobalCredential.id == credential_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential bulunamadı")
    db.query(GlobalCredential).update({GlobalCredential.is_default: False})
    cred.is_default = True
    db.commit()
    return {"success": True, "message": f"'{cred.name}' varsayılan credential olarak ayarlandı"}


@router.post("/credentials/{credential_id}/apply")
async def apply_credential_to_servers(credential_id: int, request: ApplyCredentialRequest, db: Session = Depends(get_db)):
    """Linux SSH credential — yalnızca Linux sunuculara.

    Credential yazımı anında biter; AI Ready SSH testleri arka planda çalışır
    (nginx HTML timeout / Unexpected token '<' sorununu önler).
    """
    import threading
    from app.core.database import ThreadSessionLocal as SessionLocal
    from app.services.bulk_concurrency import bulk_ssh_workers
    from app.services.platform_scope import is_linux_server, is_windows_server

    cred = db.query(GlobalCredential).filter(GlobalCredential.id == credential_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential bulunamadı")

    if request.server_ids:
        candidates = db.query(Server).filter(Server.id.in_(request.server_ids)).all()
    else:
        candidates = db.query(Server).all()

    skipped_windows = sum(1 for s in candidates if is_windows_server(s))
    servers = [s for s in candidates if is_linux_server(s)]

    if not servers:
        raise HTTPException(
            status_code=404,
            detail=(
                "Uygulanacak Linux sunucu bulunamadı. "
                "SSH credential yalnızca Linux sunuculara uygulanır; "
                "Windows için Ayarlar → Windows (WinRM) kullanın."
            ),
        )

    plain_password = decrypt_secret(cred.password) if cred.password else None
    plain_key = decrypt_secret(cred.private_key) if cred.private_key else None
    plain_sudo = decrypt_secret(cred.sudo_password) if cred.sudo_password else None
    username = cred.username
    port = cred.port or 22
    cred_name = cred.name

    applied = 0
    no_ip = 0
    test_targets = []
    for server in servers:
        if not server.connection_config:
            server.connection_config = {}
        server.connection_config["username"] = username
        if plain_password:
            server.connection_config["password"] = encrypt_secret(plain_password)
        if plain_key:
            server.connection_config["private_key"] = encrypt_secret(plain_key)
        if plain_sudo:
            server.connection_config["sudo_password"] = encrypt_secret(plain_sudo)
        server.connection_config["port"] = port
        flag_modified(server, "connection_config")
        applied += 1

        if request.set_ai_ready:
            ip = (server.ip_address or "").strip()
            if not ip:
                server.ai_ready = False
                no_ip += 1
            else:
                test_targets.append({"id": server.id, "name": server.name, "ip": ip})

    db.commit()

    ssh_started = False
    if request.set_ai_ready and test_targets:
        ssh_started = True
        targets_snap = list(test_targets)
        workers = bulk_ssh_workers()

        def _bg_ssh_ai_ready() -> None:
            from app.services.ai_ready_probe import probe_linux_snapshots

            snaps = [
                {
                    "id": t["id"],
                    "ip": t["ip"],
                    "username": username,
                    "password": plain_password,
                    "private_key": plain_key,
                    "port": port,
                }
                for t in targets_snap
            ]
            logger.info(
                "Credential apply SSH (arka plan): %s sunucu (TCP ön tarama + SSH)",
                len(snaps),
            )

            def _on_progress(done: int, total: int, ok: bool, message: str) -> None:
                if done % 100 == 0 or done == total:
                    logger.info("Credential SSH (arka plan) %s/%s (%s)", done, total, message)

            results = probe_linux_snapshots(snaps, on_progress=_on_progress)

            bg = SessionLocal()
            try:
                from datetime import datetime, timezone
                from app.services.ai_ready_guard import clear_auth_fail_backoff, set_auth_fail_backoff
                from app.services.runtime_settings import get_int

                checked_at = datetime.now(timezone.utc)
                backoff_sec = get_int("ai_ready_auth_fail_backoff_sec")
                ok_n = fail_n = 0
                for sid, ok in results.items():
                    row = bg.query(Server).filter(Server.id == sid).first()
                    if row is None:
                        continue
                    row.ai_ready = ok
                    row.ai_ready_last_check = checked_at
                    if ok:
                        clear_auth_fail_backoff(row)
                        ok_n += 1
                    else:
                        set_auth_fail_backoff(row, backoff_sec=backoff_sec, now=checked_at)
                        fail_n += 1
                bg.commit()
                logger.info(
                    "Credential '%s' AI Ready tamamlandı: ok=%s fail=%s (auth_backoff=%ss)",
                    cred_name, ok_n, fail_n, backoff_sec,
                )
            except Exception:
                logger.exception("Credential apply AI Ready arka plan DB hatası")
                bg.rollback()
            finally:
                bg.close()

        threading.Thread(
            target=_bg_ssh_ai_ready,
            daemon=True,
            name=f"cred-apply-{credential_id}",
        ).start()

    msg = f"'{cred_name}' credential {applied} Linux sunucuya uygulandı"
    if skipped_windows:
        msg += f" ({skipped_windows} Windows atlandı)"
    if ssh_started:
        msg += (
            f". AI Ready SSH testi arka planda başladı ({len(test_targets)} sunucu) — "
            "birkaç dakika içinde ai_ready güncellenir."
        )
    elif no_ip:
        msg += f". {no_ip} sunucuda IP yok, AI Ready işaretlenmedi."

    return {
        "success": True,
        "message": msg,
        "applied_count": applied,
        "skipped_windows": skipped_windows,
        "ssh_test_queued": ssh_started,
        "ssh_test_count": len(test_targets),
        "ai_ready_count": None,
        "failed_ssh": [],
        "workers": bulk_ssh_workers() if ssh_started else 0,
    }


def _ssh_test_job_snapshot(job: Dict[str, Any]) -> Dict[str, Any]:
    total = int(job.get("total") or 0)
    done = int(job.get("done") or 0)
    pct = int(round((done / total) * 100)) if total > 0 else (100 if job.get("status") == "done" else 0)
    out = {
        "job_id": job["job_id"],
        "status": job["status"],
        "done": done,
        "total": total,
        "percent": pct,
        "successful": job.get("successful", 0),
        "failed": job.get("failed", 0),
        "skipped": job.get("skipped", 0),
        "key_deployed": job.get("key_deployed", 0),
        "workers": job.get("workers", 0),
        "current_server": job.get("current_server"),
        "message": job.get("message") or "",
        "error": job.get("error"),
    }
    if job.get("status") == "done" and job.get("result"):
        out["result"] = job["result"]
    return out


def _run_ssh_test_job(job_id: str, test_targets: List[dict], skipped: List[str], workers: int) -> None:
    """Arka planda SSH test; ilerlemeyi _ssh_test_jobs'a yazar."""
    from app.services.ssh_manager import SSHManager

    successful: List[str] = []
    failed: List[str] = []
    key_deployed: List[str] = []
    done = 0
    total = len(test_targets)

    def _test_one(snap: dict) -> dict:
        try:
            ssh = SSHManager(
                host=snap["ip"],
                username=snap["username"],
                password=snap["password"],
                private_key=snap["private_key"],
                port=snap["port"] or 22,
            )
            if not ssh.connect():
                return {"id": snap["id"], "name": snap["name"], "ok": False, "key_ok": False}
            key_ok = False
            try:
                if snap.get("enc_private_key"):
                    from app.services.ssh_key_deployer import SSHKeyDeployer
                    deployer = SSHKeyDeployer()
                    deploy_result = deployer.deploy_public_key(
                        ssh_manager=ssh,
                        private_key=snap["enc_private_key"],
                    )
                    key_ok = bool(deploy_result.get("success"))
            except Exception as key_error:
                logger.warning("SSH key deployment failed for %s: %s", snap["name"], key_error)
            ssh.close()
            return {"id": snap["id"], "name": snap["name"], "ok": True, "key_ok": key_ok}
        except Exception as e:
            logger.debug("SSH test failed for %s: %s", snap["name"], e)
            return {"id": snap["id"], "name": snap["name"], "ok": False, "key_ok": False}

    db = ThreadSessionLocal()
    try:
        by_id = {
            s.id: s
            for s in db.query(Server).filter(Server.id.in_([t["id"] for t in test_targets] or [-1])).all()
        }
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="test-all-ssh") as pool:
            futures = {pool.submit(_test_one, t): t for t in test_targets}
            from datetime import datetime, timezone
            checked_at = datetime.now(timezone.utc)
            for fut in as_completed(futures):
                row = fut.result()
                srv = by_id.get(row["id"])
                if srv is not None:
                    srv.ai_ready = row["ok"]
                    srv.ai_ready_last_check = checked_at
                if row["ok"]:
                    successful.append(row["name"])
                    if row.get("key_ok"):
                        key_deployed.append(row["name"])
                else:
                    failed.append(row["name"])
                done += 1
                def _mut(j, _done=done, _row=row):
                    j["done"] = _done
                    j["successful"] = len(successful)
                    j["failed"] = len(failed)
                    j["key_deployed"] = len(key_deployed)
                    j["current_server"] = _row["name"]
                    j["message"] = f"{_done}/{total} sunucu test edildi"
                _ssh_job_update(job_id, _mut)
                if done % 25 == 0 or done == total:
                    logger.info("test-all-ssh[%s] ilerlemesi %s/%s", job_id[:8], done, total)

        db.commit()

        msg = (
            f"SSH Test tamamlandı. Başarılı: {len(successful)}, "
            f"Başarısız: {len(failed)}, Atlandı: {len(skipped)}"
        )
        if key_deployed:
            msg += f"\n\n🔑 SSH Key dağıtıldı ({len(key_deployed)}): {', '.join(key_deployed[:10])}"
            if len(key_deployed) > 10:
                msg += f" ve {len(key_deployed)-10} diğer"
        if failed:
            msg += f"\n\nBaşarısız: {', '.join(failed[:10])}"
            if len(failed) > 10:
                msg += f" ve {len(failed)-10} diğer"
        if skipped:
            msg += f"\n\nAtlandı (IP/credential yok): {', '.join(skipped[:10])}"
            if len(skipped) > 10:
                msg += f" ve {len(skipped)-10} diğer"

        result = {
            "success": True,
            "message": msg,
            "successful": len(successful),
            "failed": len(failed),
            "skipped": len(skipped),
            "key_deployed": len(key_deployed),
            "workers": workers,
            "successful_servers": successful[:20],
            "failed_servers": failed[:20],
            "skipped_servers": skipped[:20],
            "key_deployed_servers": key_deployed[:20],
        }
        def _done_mut(j):
            j["status"] = "done"
            j["done"] = total
            j["successful"] = len(successful)
            j["failed"] = len(failed)
            j["key_deployed"] = len(key_deployed)
            j["current_server"] = None
            j["message"] = msg
            j["result"] = result
        _ssh_job_update(job_id, _done_mut)
    except Exception as e:
        logger.exception("test-all-ssh[%s] failed: %s", job_id[:8], e)
        try:
            db.rollback()
        except Exception:
            pass
        def _err_mut(j, _e=e):
            j["status"] = "error"
            j["error"] = str(_e)
            j["message"] = f"SSH Test hatası: {_e}"
        _ssh_job_update(job_id, _err_mut)
    finally:
        db.close()


@router.post("/credentials/test-all-ssh")
async def test_all_servers_ssh(db: Session = Depends(get_db)):
    """Linux sunucularda SSH test başlat (Windows hariç). Progress için job_id poll edilir."""
    from app.services.bulk_concurrency import bulk_ssh_workers
    from app.services.ssh_credentials import resolve_ssh_creds
    from app.services.platform_scope import is_linux_server

    all_servers = db.query(Server).all()
    servers = [s for s in all_servers if is_linux_server(s)]
    if not servers:
        raise HTTPException(status_code=404, detail="Hiç Linux sunucu bulunamadı")

    global_cred = (
        db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()  # noqa: E712
        or db.query(GlobalCredential).first()
    )

    skipped: List[str] = []
    test_targets: List[dict] = []
    for server in servers:
        if not server.ip_address or not server.ip_address.strip():
            server.ai_ready = False
            skipped.append(server.name)
            continue
        creds = resolve_ssh_creds(server, global_cred=global_cred)
        if not creds.get("username") or not creds.get("has_secret"):
            server.ai_ready = False
            skipped.append(server.name)
            continue
        cfg = server.connection_config or {}
        test_targets.append({
            "id": server.id,
            "name": server.name,
            "ip": creds["host"],
            "username": creds["username"],
            "password": creds["password"],
            "private_key": creds["private_key"],
            "port": creds["port"],
            "enc_private_key": cfg.get("private_key") or (
                getattr(global_cred, "private_key", None) if global_cred else None
            ),
        })

    # Atlananlar için ai_ready güncellemesini hemen kaydet
    db.commit()

    workers = bulk_ssh_workers()
    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "status": "running",
        "done": 0,
        "total": len(test_targets),
        "successful": 0,
        "failed": 0,
        "skipped": len(skipped),
        "key_deployed": 0,
        "workers": workers,
        "current_server": None,
        "message": f"0/{len(test_targets)} sunucu test edildi" if test_targets else "Test edilecek sunucu yok",
        "error": None,
        "result": None,
    }
    job["started_at"] = time.time()
    _ssh_job_save(job_id, job)

    logger.info("test-all-ssh started job=%s targets=%s workers=%s skipped=%s", job_id[:8], len(test_targets), workers, len(skipped))

    if not test_targets:
        msg = f"SSH Test tamamlandı. Başarılı: 0, Başarısız: 0, Atlandı: {len(skipped)}"
        result = {
            "success": True,
            "message": msg,
            "successful": 0,
            "failed": 0,
            "skipped": len(skipped),
            "key_deployed": 0,
            "workers": workers,
            "successful_servers": [],
            "failed_servers": [],
            "skipped_servers": skipped[:20],
            "key_deployed_servers": [],
        }
        job["status"] = "done"
        job["message"] = msg
        job["result"] = result
        _ssh_job_save(job_id, job)
        return _ssh_test_job_snapshot(job)

    t = threading.Thread(
        target=_run_ssh_test_job,
        args=(job_id, test_targets, skipped, workers),
        name=f"test-all-ssh-{job_id[:8]}",
        daemon=True,
    )
    t.start()
    return _ssh_test_job_snapshot(job)


@router.get("/credentials/test-all-ssh/{job_id}")
async def test_all_servers_ssh_status(job_id: str):
    """SSH Test & Update progress."""
    job = _ssh_job_get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job bulunamadı veya süresi doldu")
    return _ssh_test_job_snapshot(job)


# ─── Gelişmiş ayarlar (timeout / interval / worker) ───

@router.get("/advanced")
async def get_advanced_settings(db: Session = Depends(get_db)):
    """Timeout, checker aralığı ve worker ayarlarını gruplu listele."""
    from app.services.runtime_settings import list_advanced_settings, GROUP_LABELS
    items = list_advanced_settings()
    groups = []
    seen = []
    for it in items:
        g = it["group"]
        if g not in seen:
            seen.append(g)
            groups.append({
                "id": g,
                "label": GROUP_LABELS.get(g, g),
                "settings": [x for x in items if x["group"] == g],
            })
    return {"groups": groups, "settings": items}


class AdvancedSettingsUpdate(BaseModel):
    settings: dict  # key -> value


@router.put("/advanced")
async def put_advanced_settings(
    body: AdvancedSettingsUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    """Gelişmiş ayarları kaydet. Çoğu restart gerektirmez; process worker ayarları recreate ister."""
    from app.services.runtime_settings import save_advanced_settings, ADVANCED_SCHEMA
    if not isinstance(body.settings, dict) or not body.settings:
        raise HTTPException(status_code=400, detail="settings sözlüğü gerekli")
    unknown = [k for k in body.settings if k not in ADVANCED_SCHEMA]
    saved = save_advanced_settings(body.settings, db)
    restart_needed = [
        {
            "key": k,
            "target": ADVANCED_SCHEMA[k].get("restart_target") or "container",
            "label": ADVANCED_SCHEMA[k].get("label") or k,
        }
        for k in saved
        if ADVANCED_SCHEMA.get(k, {}).get("requires_restart")
    ]
    if restart_needed:
        targets = sorted({x["target"] for x in restart_needed})
        msg = (
            f"{len(saved)} ayar kaydedildi. Process worker değerleri dosyaya yazıldı — "
            f"uygulamak için recreate: {', '.join(targets)} "
            f"(örn. docker compose up -d --force-recreate {' '.join(targets)})."
        )
    else:
        msg = (
            f"{len(saved)} ayar kaydedildi. "
            "Arka plan görevleri bir sonraki döngüde yeni aralığı kullanır."
        )
    return {
        "success": True,
        "saved": saved,
        "unknown_keys": unknown,
        "restart_needed": restart_needed,
        "message": msg,
    }


# ─── General Settings ────────────────────────────────

@router.get("/")
async def get_settings(db: Session = Depends(get_db)):
    """Genel ayarları getir"""
    from app.core.config import settings
    from app.core.version import get_app_version
    default_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()
    # DB'den aktif model oku, yoksa config default'u kullan
    model_row = db.query(AppSettings).filter(AppSettings.key == "ollama_active_model").first()
    active_model = model_row.value if model_row and model_row.value else settings.OLLAMA_DEFAULT_MODEL
    metric_retention_row = db.query(AppSettings).filter(AppSettings.key == "metric_retention_days").first()
    try:
        metric_retention_days = int(metric_retention_row.value) if metric_retention_row and metric_retention_row.value else 30
    except ValueError:
        metric_retention_days = 30
    # Yönetim sunucusu IP'si (DB'den al, yoksa otomatik tespit)
    mgmt_ip_row = db.query(AppSettings).filter(AppSettings.key == "management_server_ip").first()
    from app.services.system_update_service import _get_management_ip
    detected_ip = _get_management_ip()
    management_server_ip = mgmt_ip_row.value if mgmt_ip_row and mgmt_ip_row.value else detected_ip

    def _mask_key(k: str) -> str:
        if not k:
            return ""
        return (k[:6] + "…" + k[-4:]) if len(k) > 12 else "•" * len(k)

    return {
        "ollama_url": settings.OLLAMA_URL,
        "ollama_model": active_model,
        "prometheus_url": settings.PROMETHEUS_URL,
        "pushgateway_url": settings.PUSHGATEWAY_URL,
        "prometheus_linux_jobs": list(settings.PROMETHEUS_LINUX_JOBS) or ["node-exporter"],
        "prometheus_windows_jobs": list(settings.PROMETHEUS_WINDOWS_JOBS) or ["windows-exporter"],
        "metric_retention_days": metric_retention_days,
        "management_server_ip": management_server_ip,
        "detected_management_ip": detected_ip,
        "default_credential": _cred_to_response(default_cred) if default_cred else None,
        "remote_llm": {
            "enabled": settings.REMOTE_LLM_ENABLED,
            "url": settings.REMOTE_LLM_URL,
            "model": settings.REMOTE_LLM_MODEL,
            "api_key_set": bool(settings.REMOTE_LLM_API_KEY),
            "api_key_masked": _mask_key(settings.REMOTE_LLM_API_KEY),
            "virtual_key_set": bool(getattr(settings, "REMOTE_LLM_VIRTUAL_KEY", "") or ""),
            "virtual_key_masked": _mask_key(getattr(settings, "REMOTE_LLM_VIRTUAL_KEY", "") or ""),
            "verify_ssl": settings.REMOTE_LLM_VERIFY_SSL,
            "ca_bundle": settings.REMOTE_LLM_CA_BUNDLE,
        },
        "app_version": get_app_version(),
    }


@router.put("/management-server-ip")
async def set_management_server_ip(payload: dict, db: Session = Depends(get_db)):
    """Yönetim sunucusunun client'lardan erişilebilir IP adresini kaydet."""
    ip = (payload.get("ip") or "").strip()
    if not ip:
        raise HTTPException(status_code=400, detail="IP adresi boş olamaz")
    row = db.query(AppSettings).filter(AppSettings.key == "management_server_ip").first()
    if row:
        row.value = ip
    else:
        db.add(AppSettings(key="management_server_ip", value=ip))
    db.commit()
    # Config'e de yaz (runtime)
    from app.core.config import settings
    settings.MANAGEMENT_SERVER_IP = ip
    logger.info(f"Yönetim sunucu IP güncellendi: {ip}")
    return {"success": True, "ip": ip}


@router.put("/prometheus")
async def set_prometheus_urls(payload: dict, db: Session = Depends(get_db)):
    """Prometheus URL + job adlarını kaydet. Restart gerekmez.

    Body: {
      prometheus_url,
      pushgateway_url?,
      prometheus_linux_jobs?: string[],   # örn. ["node-exporter","prometheus"]
      prometheus_windows_jobs?: string[],
    }
    """
    from app.core.config import settings, _parse_job_list
    import json
    import re

    def _save(key: str, value: str):
        row = db.query(AppSettings).filter(AppSettings.key == key).first()
        if row:
            row.value = value
        else:
            db.add(AppSettings(key=key, value=value))

    prom_url = (payload.get("prometheus_url") or "").strip().rstrip("/")
    if not prom_url:
        raise HTTPException(status_code=400, detail="Prometheus URL zorunludur")
    if not re.match(r"^https?://", prom_url, re.I):
        raise HTTPException(status_code=400, detail="Prometheus URL http:// veya https:// ile başlamalı")

    # pushgateway opsiyonel — gönderilmezse mevcut değeri koru
    pg_raw = payload.get("pushgateway_url")
    if pg_raw is None:
        pg_url = settings.PUSHGATEWAY_URL
    else:
        pg_url = (pg_raw or "").strip().rstrip("/")
        if pg_url and not re.match(r"^https?://", pg_url, re.I):
            raise HTTPException(status_code=400, detail="Pushgateway URL http:// veya https:// ile başlamalı")

    def _normalize_jobs(raw, default: list) -> list:
        if raw is None:
            return list(default)
        if isinstance(raw, list):
            jobs = [str(x).strip() for x in raw if str(x).strip()]
            return jobs or list(default)
        return _parse_job_list(str(raw), default)

    linux_jobs = _normalize_jobs(
        payload.get("prometheus_linux_jobs"),
        list(settings.PROMETHEUS_LINUX_JOBS) or ["node-exporter"],
    )
    windows_jobs = _normalize_jobs(
        payload.get("prometheus_windows_jobs"),
        list(settings.PROMETHEUS_WINDOWS_JOBS) or ["windows-exporter"],
    )

    _save("prometheus_url", prom_url)
    _save("pushgateway_url", pg_url)
    _save("prometheus_linux_jobs", json.dumps(linux_jobs, ensure_ascii=False))
    _save("prometheus_windows_jobs", json.dumps(windows_jobs, ensure_ascii=False))
    db.commit()

    settings.PROMETHEUS_URL = prom_url
    settings.PUSHGATEWAY_URL = pg_url
    settings.PROMETHEUS_LINUX_JOBS = linux_jobs
    settings.PROMETHEUS_WINDOWS_JOBS = windows_jobs
    logger.info(
        f"Prometheus URL güncellendi: {prom_url} "
        f"(pushgateway={pg_url or 'unset'}, linux_jobs={linux_jobs}, windows_jobs={windows_jobs})"
    )
    return {
        "success": True,
        "prometheus_url": prom_url,
        "pushgateway_url": pg_url,
        "prometheus_linux_jobs": linux_jobs,
        "prometheus_windows_jobs": windows_jobs,
    }


@router.put("/ollama-model")
async def set_ollama_model(payload: dict, db: Session = Depends(get_db)):
    """Aktif Ollama modelini kaydet — chat + agent aynı modele hizalanır (Wave B3)."""
    model = (payload.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="Model adı boş olamaz")

    def _upsert(key: str, value: str) -> None:
        row = db.query(AppSettings).filter(AppSettings.key == key).first()
        if row:
            row.value = value
        else:
            db.add(AppSettings(key=key, value=value))

    _upsert("ollama_active_model", model)
    # Agent tool-calling modeli de aynı değere yazılır; .env AGENT_MODEL yalnızca
    # agent_active_model yokken fallback kalır.
    _upsert("agent_active_model", model)
    db.commit()
    logger.info("Aktif Ollama + agent modeli guncellendi: %s", model)
    return {"success": True, "model": model, "agent_model": model}


@router.put("/remote-llm")
async def set_remote_llm(
    payload: dict,
    db: Session = Depends(get_db),
    _user: User = Depends(require_role("admin")),
):
    """
    Uzak, OpenAI-uyumlu AI gateway (örn. Bifrost) ayarlarını kaydet.
    enabled=true olduğunda TÜM chat/agent/analiz çağrıları bu gateway'e gider.
    Body: {enabled, url, api_key?, model}  — api_key gönderilmezse mevcut değer korunur.
    """
    from app.core.config import settings

    def _save(key: str, value: str):
        row = db.query(AppSettings).filter(AppSettings.key == key).first()
        if row:
            row.value = value
        else:
            db.add(AppSettings(key=key, value=value))

    enabled = bool(payload.get("enabled", False))
    url = (payload.get("url") or "").strip().rstrip("/")
    model = (payload.get("model") or "").strip()
    api_key_raw = payload.get("api_key")
    virtual_key_raw = payload.get("virtual_key")
    clear_virtual_key = bool(payload.get("clear_virtual_key"))
    # Sertifika doğrulaması: varsayılan True (güvenli); gönderilmezse mevcut değeri koru.
    verify_ssl = bool(payload.get("verify_ssl", settings.REMOTE_LLM_VERIFY_SSL))
    ca_bundle = (payload.get("ca_bundle") or "").strip()

    if enabled and (not url or not model):
        raise HTTPException(status_code=400, detail="Uzak AI aktif edilecekse URL ve Model adı zorunludur")
    if ca_bundle and not os.path.isfile(ca_bundle):
        raise HTTPException(
            status_code=400,
            detail=f"CA bundle dosyası container içinde bulunamadı: {ca_bundle} "
                   "(önce dosyayı ${DATA_DIR}/certs/ altına koyup backend'i yeniden başlatın)",
        )

    _save("remote_llm_enabled", "true" if enabled else "false")
    _save("remote_llm_url", url)
    _save("remote_llm_model", model)
    _save("remote_llm_verify_ssl", "true" if verify_ssl else "false")
    _save("remote_llm_ca_bundle", ca_bundle)

    if api_key_raw:  # boş/None gönderilirse mevcut key korunur
        _save("remote_llm_api_key", encrypt_secret(api_key_raw))

    if clear_virtual_key:
        _save("remote_llm_virtual_key", "")
    elif virtual_key_raw:  # boş/None → mevcut VK korunur
        _save("remote_llm_virtual_key", encrypt_secret(str(virtual_key_raw)))

    db.commit()

    # Runtime'a hemen yansıt (restart beklemeden) — management_server_ip ile aynı desen.
    settings.REMOTE_LLM_ENABLED = enabled
    settings.REMOTE_LLM_URL = url
    settings.REMOTE_LLM_MODEL = model
    settings.REMOTE_LLM_VERIFY_SSL = verify_ssl
    settings.REMOTE_LLM_CA_BUNDLE = ca_bundle
    if api_key_raw:
        settings.REMOTE_LLM_API_KEY = api_key_raw
    if clear_virtual_key:
        settings.REMOTE_LLM_VIRTUAL_KEY = ""
    elif virtual_key_raw:
        settings.REMOTE_LLM_VIRTUAL_KEY = str(virtual_key_raw)

    logger.info(
        f"Uzak AI gateway güncellendi: enabled={enabled} url={url} model={model} "
        f"verify_ssl={verify_ssl} ca_bundle={'set' if ca_bundle else 'unset'} "
        f"virtual_key={'cleared' if clear_virtual_key else ('set' if virtual_key_raw else 'unchanged')}"
    )
    try:
        from app.services.settings_broadcast import broadcast_settings_reload, reload_runtime_settings_from_db
        reload_runtime_settings_from_db()
        broadcast_settings_reload()
    except Exception as _bc:
        logger.debug("settings broadcast: %s", _bc)
    return {
        "success": True,
        "enabled": enabled,
        "url": url,
        "model": model,
        "verify_ssl": verify_ssl,
        "ca_bundle": ca_bundle,
        "virtual_key_set": bool(settings.REMOTE_LLM_VIRTUAL_KEY),
    }


@router.post("/remote-llm/test")
async def test_remote_llm(
    payload: dict,
    _user: User = Depends(require_role("admin")),
):
    """Uzak AI gateway bağlantısını test et (kaydetmeden form değerleriyle denenebilir).

    Body: {url, model, api_key?, virtual_key?, verify_ssl?, ca_bundle?}
    api_key / virtual_key boşsa kayıtlı değerler kullanılır.
    """
    import time

    import httpx

    from app.core.config import settings
    from app.services.llm_gateway import _remote_headers

    url = (payload.get("url") or settings.REMOTE_LLM_URL or "").strip().rstrip("/")
    model = (payload.get("model") or settings.REMOTE_LLM_MODEL or "").strip()
    api_key_raw = payload.get("api_key")
    api_key = (api_key_raw or "").strip() or (settings.REMOTE_LLM_API_KEY or "").strip()
    vk_raw = payload.get("virtual_key")
    virtual_key = (vk_raw or "").strip() or (getattr(settings, "REMOTE_LLM_VIRTUAL_KEY", None) or "").strip()
    verify_ssl = bool(payload.get("verify_ssl", settings.REMOTE_LLM_VERIFY_SSL))
    ca_bundle = (payload.get("ca_bundle") or settings.REMOTE_LLM_CA_BUNDLE or "").strip()

    if not url:
        raise HTTPException(status_code=400, detail="Gateway URL gerekli")
    if not model:
        raise HTTPException(status_code=400, detail="Model adı gerekli")

    verify: bool | str = verify_ssl
    if ca_bundle:
        if not os.path.isfile(ca_bundle):
            raise HTTPException(
                status_code=400,
                detail=f"CA bundle dosyası bulunamadı: {ca_bundle}",
            )
        verify = ca_bundle

    chat_url = f"{url}/v1/chat/completions"
    headers = _remote_headers(api_key=api_key, virtual_key=virtual_key)
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 8,
        "temperature": 0,
    }
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=30.0, verify=verify) as client:
            resp = await client.post(chat_url, headers=headers, json=body)
    except httpx.TimeoutException:
        return {"ok": False, "message": "Zaman aşımı (30s) — gateway yanıt vermedi", "latency_ms": None}
    except httpx.ConnectError as exc:
        return {"ok": False, "message": f"Bağlantı hatası: {exc}", "latency_ms": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"İstek başarısız: {exc}", "latency_ms": None}

    latency_ms = int((time.monotonic() - t0) * 1000)
    if resp.status_code >= 400:
        detail = (resp.text or "")[:280]
        msg = f"HTTP {resp.status_code}: {detail or 'yanıt gövdesi boş'}"
        low = detail.lower()
        if resp.status_code in (401, 403) and (
            "virtual_key" in low or "x-bf-vk" in low or "unauthorized" in low or "forbidden" in low
        ):
            msg += (
                " — Bifrost için Virtual Key alanına sk-bf-… yazıp API Key'i boş bırakın "
                "(yalnızca x-bf-vk). Eski Authorization yolu için anahtarı API Key'e koyun."
            )
        return {
            "ok": False,
            "message": msg,
            "latency_ms": latency_ms,
            "url": chat_url,
            "model": model,
        }
    try:
        data = resp.json()
        content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        snippet = str(content).strip()[:80]
    except Exception:
        snippet = ""
    msg = f"Bağlantı OK · {model} · {latency_ms} ms"
    if snippet:
        msg += f" · yanıt: {snippet!r}"
    return {"ok": True, "message": msg, "latency_ms": latency_ms, "url": chat_url, "model": model}


@router.put("/metric-retention")
async def set_metric_retention(payload: dict, db: Session = Depends(get_db)):
    """MetricData saklama süresini güncelle ve eski metrikleri temizle."""
    days_raw = payload.get("days")
    try:
        days = int(days_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="days sayı olmalıdır")

    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="days 1 ile 365 arasında olmalıdır")

    # App setting kaydet
    row = db.query(AppSettings).filter(AppSettings.key == "metric_retention_days").first()
    if row:
        row.value = str(days)
    else:
        db.add(AppSettings(key="metric_retention_days", value=str(days)))
    db.commit()

    # 1) Eski kayıtları anında temizle (kullanıcının beklediği davranış)
    delete_sql = text(
        "DELETE FROM metric_data WHERE timestamp < (NOW() AT TIME ZONE 'UTC') - (:days || ' days')::interval"
    )
    deleted_result = db.execute(delete_sql, {"days": days})
    deleted_rows = int(deleted_result.rowcount or 0)
    db.commit()

    # 2) Timescale retention policy varsa güncelle
    policy_updated = False
    policy_error = None
    try:
        db.execute(text("SELECT remove_retention_policy('metric_data', if_exists => TRUE);"))
        db.execute(
            text(
                "SELECT add_retention_policy('metric_data', (:days || ' days')::interval, if_not_exists => TRUE);"
            ),
            {"days": days},
        )
        db.commit()
        policy_updated = True
    except Exception as e:
        # Timescale extension yoksa veya policy çağrısı hata verirse sadece manuel delete ile devam.
        db.rollback()
        policy_error = str(e)

    return {
        "success": True,
        "metric_retention_days": days,
        "deleted_rows": deleted_rows,
        "policy_updated": policy_updated,
        "policy_error": policy_error,
    }


# ─── Config Backup / Restore (eski ortam → yeni ortam) ─────────────────────

_SENSITIVE_APP_SETTING_KEYS = frozenset({
    "remote_llm_api_key",
    "remote_llm_virtual_key",
    "global_winrm_credential",
    "ucmdb_connection",
})

# Yeni ortamda genelde hedefe özel kalmalı
_SKIP_RESTORE_KEYS_DEFAULT = frozenset({
    "management_server_ip",
})


def _secret_key_fingerprint() -> str:
    import hashlib
    from app.core.config import settings as cfg
    dig = hashlib.sha256((cfg.SECRET_KEY or "").encode()).hexdigest()[:16]
    return f"sha256:{dig}"


def _decrypt_setting_value(key: str, value: str) -> str:
    """Export için Fernet alanlarını plaintext'e çevir."""
    if not value:
        return value
    if key in ("remote_llm_api_key", "remote_llm_virtual_key"):
        return decrypt_secret(value) or ""
    if key == "global_winrm_credential":
        try:
            import json
            obj = json.loads(value)
            if isinstance(obj, dict) and obj.get("password"):
                obj = dict(obj)
                obj["password"] = decrypt_secret(obj["password"]) or ""
            return json.dumps(obj, ensure_ascii=False)
        except Exception:
            return value
    return value


def _encrypt_setting_value(key: str, value: str) -> str:
    """Restore: plaintext → hedef SECRET_KEY ile Fernet."""
    if not value:
        return value
    if key in ("remote_llm_api_key", "remote_llm_virtual_key"):
        return encrypt_secret(value) or value
    if key == "global_winrm_credential":
        try:
            import json
            obj = json.loads(value)
            if isinstance(obj, dict) and obj.get("password"):
                obj = dict(obj)
                # Zaten ciphertext ise decrypt_secret plaintext döner (legacy) veya çözer
                plain = decrypt_secret(obj["password"]) or obj["password"]
                obj["password"] = encrypt_secret(plain) or plain
            return json.dumps(obj, ensure_ascii=False)
        except Exception:
            return value
    return value


def _apply_runtime_overlays(db: Session) -> None:
    """Restore sonrası prometheus / remote_llm / mgmt IP runtime'a yansıt."""
    try:
        from app.core.config import settings as cfg
        import os

        def _get(k: str) -> Optional[str]:
            row = db.query(AppSettings).filter(AppSettings.key == k).first()
            return row.value if row and row.value is not None else None

        for env_key, db_key in (
            ("PROMETHEUS_URL", "prometheus_url"),
            ("PUSHGATEWAY_URL", "pushgateway_url"),
            ("MANAGEMENT_SERVER_IP", "management_server_ip"),
        ):
            v = _get(db_key)
            if v:
                os.environ[env_key] = v
                if hasattr(cfg, env_key):
                    setattr(cfg, env_key, v)

        r_en = _get("remote_llm_enabled")
        if r_en is not None:
            enabled = str(r_en).lower() in ("1", "true", "yes", "on")
            os.environ["REMOTE_LLM_ENABLED"] = "true" if enabled else "false"
            cfg.REMOTE_LLM_ENABLED = enabled
        for attr, db_key in (
            ("REMOTE_LLM_URL", "remote_llm_url"),
            ("REMOTE_LLM_MODEL", "remote_llm_model"),
            ("REMOTE_LLM_CA_BUNDLE", "remote_llm_ca_bundle"),
        ):
            v = _get(db_key)
            if v is not None:
                os.environ[attr] = v
                setattr(cfg, attr, v)
        api_enc = _get("remote_llm_api_key")
        if api_enc:
            plain = decrypt_secret(api_enc) or api_enc
            os.environ["REMOTE_LLM_API_KEY"] = plain
            cfg.REMOTE_LLM_API_KEY = plain
        vk_enc = _get("remote_llm_virtual_key")
        if vk_enc is not None:
            plain_vk = decrypt_secret(vk_enc) if vk_enc else ""
            plain_vk = plain_vk or ""
            os.environ["REMOTE_LLM_VIRTUAL_KEY"] = plain_vk
            cfg.REMOTE_LLM_VIRTUAL_KEY = plain_vk
        vs = _get("remote_llm_verify_ssl")
        if vs is not None:
            verify = str(vs).lower() in ("1", "true", "yes", "on")
            os.environ["REMOTE_LLM_VERIFY_SSL"] = "true" if verify else "false"
            cfg.REMOTE_LLM_VERIFY_SSL = verify
    except Exception as e:
        logger.warning("config restore runtime overlay: %s", e)


@router.get("/config/backup")
async def config_backup(
    include_secrets: bool = True,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    """
    Yapılandırma yedeği — eski ortamdan yeni ortama taşımak için.

    - app_settings (gelişmiş + AI + monitoring + branding …)
    - SSH credential'lar (include_secrets=true ise plaintext; hedefte yeniden şifrelenir)
    - Kullanıcı modül atamaları
    - env_hints (manuel .env birleştirme notları — SECRET_KEY/DB şifresi yok)
    """
    import datetime
    from app.core.config import settings as cfg
    from app.models.module import UserModule

    app_settings: Dict[str, Any] = {}
    for row in db.query(AppSettings).all():
        if not row.key or row.value is None:
            continue
        val = row.value
        if include_secrets and row.key in _SENSITIVE_APP_SETTING_KEYS:
            val = _decrypt_setting_value(row.key, val)
        elif (not include_secrets) and row.key in _SENSITIVE_APP_SETTING_KEYS:
            # Sırları dışarı verme — placeholder
            if row.key in ("remote_llm_api_key", "remote_llm_virtual_key"):
                val = ""
            elif row.key == "global_winrm_credential":
                try:
                    import json
                    obj = json.loads(val)
                    if isinstance(obj, dict):
                        obj = dict(obj)
                        if obj.get("password"):
                            obj["password"] = "***"
                        val = json.dumps(obj, ensure_ascii=False)
                except Exception:
                    val = "***"
        app_settings[row.key] = val

    credentials = []
    for c in db.query(GlobalCredential).order_by(GlobalCredential.name).all():
        item = {
            "name": c.name,
            "username": c.username,
            "port": c.port or 22,
            "is_default": bool(c.is_default),
            "has_password": bool(c.password),
            "has_private_key": bool(c.private_key),
            "has_sudo_password": bool(c.sudo_password),
        }
        if include_secrets:
            item["password"] = decrypt_secret(c.password) if c.password else ""
            item["private_key"] = decrypt_secret(c.private_key) if c.private_key else ""
            item["sudo_password"] = decrypt_secret(c.sudo_password) if c.sudo_password else ""
        credentials.append(item)

    module_grants = []
    users = {u.id: u for u in db.query(User).all()}
    for um in db.query(UserModule).all():
        u = users.get(um.user_id)
        if not u:
            continue
        module_grants.append({
            "username": u.username,
            "module_id": um.module_id,
        })

    cors = getattr(cfg, "CORS_ORIGINS", "") or ""
    if isinstance(cors, (list, tuple)):
        cors = ",".join(str(x) for x in cors)
    env_hints = {
        "OLLAMA_URL": getattr(cfg, "OLLAMA_URL", "") or "",
        "OLLAMA_EMBED_MODEL": getattr(cfg, "OLLAMA_EMBED_MODEL", "") or "",
        "EMBEDDING_URL": getattr(cfg, "EMBEDDING_URL", "") or "",
        "REMOTE_LLM_ENABLED": str(bool(getattr(cfg, "REMOTE_LLM_ENABLED", False))).lower(),
        "REMOTE_LLM_URL": getattr(cfg, "REMOTE_LLM_URL", "") or "",
        "REMOTE_LLM_MODEL": getattr(cfg, "REMOTE_LLM_MODEL", "") or "",
        "CORS_ORIGINS": str(cors),
        "_note": (
            "Bu alanlar bilgilendirme amaçlıdır; yeni ortamın .env dosyasına "
            "elle birleştirin. SECRET_KEY ve POSTGRES_PASSWORD yedekte YOKTUR — "
            "yeni ortam kendi anahtarını kullanmalı; credential'lar restore'da "
            "hedef SECRET_KEY ile yeniden şifrelenir."
        ),
    }

    return {
        "format_version": "2.0",
        "exported_at": datetime.datetime.utcnow().isoformat() + "Z",
        "source_secret_key_fingerprint": _secret_key_fingerprint(),
        "include_secrets": include_secrets,
        "app_settings": app_settings,
        "credentials": credentials,
        "module_grants": module_grants,
        "env_hints": env_hints,
        # geriye uyumluluk
        "version": "2.0",
        "credentials_meta": [
            {k: c[k] for k in ("name", "username", "port", "is_default", "has_password", "has_private_key") if k in c}
            for c in credentials
        ],
    }


class ConfigRestoreRequest(BaseModel):
    app_settings: Optional[dict] = None
    credentials: Optional[List[dict]] = None
    module_grants: Optional[List[dict]] = None
    apply_settings: bool = True
    apply_credentials: bool = True
    apply_modules: bool = True
    # management_server_ip gibi host-özel alanları da zorla yaz
    force_host_keys: bool = False
    source_secret_key_fingerprint: Optional[str] = None
    include_secrets: Optional[bool] = None
    format_version: Optional[str] = None
    version: Optional[str] = None
    env_hints: Optional[dict] = None
    credentials_meta: Optional[List[dict]] = None
    exported_at: Optional[str] = None


@router.post("/config/restore")
async def config_restore(
    data: ConfigRestoreRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    """
    Yedekten yapılandırmayı geri yükle (yeni ortam).

    Credential / remote_llm_api_key plaintext geldiyse hedef SECRET_KEY ile şifrelenir.
    SECRET_KEY ve Postgres şifresi asla üzerine yazılmaz.
    """
    from app.models.module import UserModule, Module

    stats = {"settings": 0, "credentials": 0, "modules": 0, "skipped_keys": [], "warnings": []}

    if data.apply_settings and data.app_settings:
        for key, value in data.app_settings.items():
            if not key or value is None:
                continue
            if key in _SKIP_RESTORE_KEYS_DEFAULT and not data.force_host_keys:
                stats["skipped_keys"].append(key)
                continue
            raw = str(value)
            if key in _SENSITIVE_APP_SETTING_KEYS:
                # Export plaintext veya eski ciphertext — hedef key ile yeniden şifrele
                if key in ("remote_llm_api_key", "remote_llm_virtual_key") and raw in ("", "***"):
                    continue
                store = _encrypt_setting_value(key, raw)
            else:
                store = raw
            row = db.query(AppSettings).filter(AppSettings.key == key).first()
            if row:
                row.value = store
            else:
                db.add(AppSettings(key=key, value=store))
            stats["settings"] += 1

    if data.apply_credentials and data.credentials:
        for item in data.credentials:
            name = (item.get("name") or "").strip()
            if not name:
                continue
            username = (item.get("username") or "").strip()
            if not username:
                stats["warnings"].append(f"credential '{name}': username yok, atlandı")
                continue
            password = item.get("password")
            private_key = item.get("private_key")
            sudo_password = item.get("sudo_password")
            # Meta-only backup (eski format): sırlar yok → sadece kullanıcı/port güncelle
            has_secret_fields = any(k in item for k in ("password", "private_key", "sudo_password"))

            cred = db.query(GlobalCredential).filter(GlobalCredential.name == name).first()
            if not cred:
                if not has_secret_fields:
                    stats["warnings"].append(
                        f"credential '{name}': yedekte sır yok ve hedefte kayıt yok — atlandı"
                    )
                    continue
                cred = GlobalCredential(
                    name=name,
                    username=username,
                    password=encrypt_secret(password or "") or None,
                    private_key=encrypt_secret(private_key or "") or None,
                    sudo_password=encrypt_secret(sudo_password or "") or None,
                    port=int(item.get("port") or 22),
                    is_default=bool(item.get("is_default")),
                )
                if cred.is_default:
                    db.query(GlobalCredential).update({GlobalCredential.is_default: False})
                db.add(cred)
            else:
                cred.username = username
                cred.port = int(item.get("port") or cred.port or 22)
                if has_secret_fields:
                    if password is not None:
                        cred.password = encrypt_secret(password) if password else None
                    if private_key is not None:
                        cred.private_key = encrypt_secret(private_key) if private_key else None
                    if sudo_password is not None:
                        cred.sudo_password = encrypt_secret(sudo_password) if sudo_password else None
                if item.get("is_default"):
                    db.query(GlobalCredential).update({GlobalCredential.is_default: False})
                    cred.is_default = True
            stats["credentials"] += 1

    if data.apply_modules and data.module_grants:
        known_modules = {m.id for m in db.query(Module).all()}
        for grant in data.module_grants:
            username = (grant.get("username") or "").strip()
            module_id = (grant.get("module_id") or "").strip()
            if not username or not module_id:
                continue
            if module_id not in known_modules:
                stats["warnings"].append(f"modül '{module_id}' hedefte yok — atlandı")
                continue
            user = db.query(User).filter(User.username == username).first()
            if not user:
                stats["warnings"].append(f"kullanıcı '{username}' hedefte yok — modül ataması atlandı")
                continue
            exists = (
                db.query(UserModule)
                .filter(UserModule.user_id == user.id, UserModule.module_id == module_id)
                .first()
            )
            if not exists:
                db.add(UserModule(user_id=user.id, module_id=module_id, granted_by=_admin.id))
                stats["modules"] += 1

    db.commit()
    _apply_runtime_overlays(db)

    try:
        from app.services import runtime_settings as rs
        rs.invalidate_cache()
    except Exception:
        pass

    msg_parts = [
        f"{stats['settings']} ayar",
        f"{stats['credentials']} credential",
        f"{stats['modules']} modül ataması",
    ]
    return {
        "success": True,
        "message": "Geri yükleme tamam: " + ", ".join(msg_parts),
        "stats": stats,
        "target_secret_key_fingerprint": _secret_key_fingerprint(),
        "env_hints": data.env_hints or {},
        "env_hints_note": (
            "env_hints otomatik uygulanmaz. Yeni ortam .env dosyasına OLLAMA_URL / "
            "REMOTE_LLM_* değerlerini elle ekleyip backend'i yeniden başlatın."
        ),
    }


class AIProviderRequest(BaseModel):
    provider: str  # groq, openai, openrouter, anthropic
    api_key: str

@router.post("/ai-provider")
async def set_ai_provider_key(data: AIProviderRequest):
    """Harici AI sağlayıcı API anahtarını ortam değişkenine yazar (runtime)."""
    import os
    from app.core.config import settings
    provider_map = {
        "groq": ("GROQ_API_KEY", "GROQ_API_KEY"),
        "openai": ("OPENAI_API_KEY", "OPENAI_API_KEY"),
        "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
        "openrouter": ("OPENROUTER_API_KEY", "OPENROUTER_API_KEY"),
    }
    if data.provider not in provider_map:
        raise HTTPException(status_code=400, detail=f"Bilinmeyen sağlayıcı: {data.provider}")

    env_key, attr = provider_map[data.provider]
    os.environ[env_key] = data.api_key
    setattr(settings, attr, data.api_key)
    return {"success": True, "provider": data.provider, "message": f"{data.provider} API anahtarı güncellendi"}


# ── Kurumsal Kimlik (Marka Adı + Logo) ──────────────────────────────────────
# Okuma tarafı açık uçlardan yapılır (bkz. app/api/public.py) çünkü login
# sayfası henüz bir JWT'ye sahip değildir. Yazma tarafı sadece admin.
BRANDING_LOGO_DIR = "/app/uploads/branding"
BRANDING_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".svg", ".webp"}
BRANDING_MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB


class BrandingRequest(BaseModel):
    app_name: str


@router.put("/branding")
async def set_branding(
    data: BrandingRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    """Uygulama/kurum adını güncelle."""
    app_name = (data.app_name or "").strip()
    if not app_name:
        raise HTTPException(status_code=400, detail="Uygulama adı boş olamaz")
    if len(app_name) > 64:
        raise HTTPException(status_code=400, detail="Uygulama adı en fazla 64 karakter olabilir")

    row = db.query(AppSettings).filter(AppSettings.key == "branding_app_name").first()
    if row:
        row.value = app_name
    else:
        db.add(AppSettings(key="branding_app_name", value=app_name))
    db.commit()
    logger.info(f"Kurumsal uygulama adı güncellendi: {app_name}")
    return {"success": True, "app_name": app_name}


def _existing_branding_logo_filename(db: Session) -> Optional[str]:
    row = db.query(AppSettings).filter(AppSettings.key == "branding_logo_filename").first()
    return row.value if row and row.value else None


@router.post("/branding/logo")
async def upload_branding_logo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    """Kurum logosunu yükle (png/jpg/jpeg/svg/webp, max 2MB)."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in BRANDING_ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Desteklenmeyen dosya türü: {ext or 'bilinmiyor'} (izin verilenler: png, jpg, jpeg, svg, webp)",
        )

    content = await file.read()
    if len(content) > BRANDING_MAX_LOGO_BYTES:
        raise HTTPException(status_code=400, detail="Logo dosyası en fazla 2MB olabilir")
    if not content:
        raise HTTPException(status_code=400, detail="Boş dosya")

    os.makedirs(BRANDING_LOGO_DIR, exist_ok=True)

    # Önceki logoyu (farklı uzantılı olabilir) temizle
    old_filename = _existing_branding_logo_filename(db)
    if old_filename:
        old_path = os.path.join(BRANDING_LOGO_DIR, old_filename)
        if os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    new_filename = f"logo{ext}"
    with open(os.path.join(BRANDING_LOGO_DIR, new_filename), "wb") as f:
        f.write(content)

    row = db.query(AppSettings).filter(AppSettings.key == "branding_logo_filename").first()
    if row:
        row.value = new_filename
    else:
        db.add(AppSettings(key="branding_logo_filename", value=new_filename))
    db.commit()

    logger.info(f"Kurum logosu güncellendi: {new_filename}")
    return {"success": True}


@router.delete("/branding/logo")
async def delete_branding_logo(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    """Kurum logosunu kaldır — varsayılan (marka baş harfleri) gösterime döner."""
    old_filename = _existing_branding_logo_filename(db)
    if old_filename:
        old_path = os.path.join(BRANDING_LOGO_DIR, old_filename)
        if os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass
        db.query(AppSettings).filter(AppSettings.key == "branding_logo_filename").delete()
        db.commit()
    logger.info("Kurum logosu kaldırıldı")
    return {"success": True}


# ── Tehlikeli Bölge: Veri Silme ─────────────────────────────────────────────
# Kullanıcı hesapları, modül/rol atamaları ve global credential/ayarlar her
# durumda korunur. Silinebilecek veriler kategorilere ayrılmıştır — kullanıcı
# hangi kategorileri sileceğini seçebilir.
WIPE_CATEGORIES: dict[str, dict] = {
    "servers": {
        "label": "Sunucular / VM'ler",
        "tables": ["servers", "vm_snapshots", "business_service_map", "agent_actions"],
    },
    "hypervisors": {
        "label": "Hypervisor Bağlantıları",
        "tables": ["hypervisors", "hypervisor_host_inventory", "hypervisor_host_metrics"],
    },
    "exadata": {
        "label": "Exadata Envanteri",
        "tables": ["exadata_racks", "exadata_nodes"],
    },
    "events": {
        "label": "Olaylar / Incident / Alert",
        "tables": ["system_events", "alerts", "incidents", "anomaly_suppressions", "baseline_metrics", "runbook_executions"],
    },
    "metrics": {
        "label": "Metrikler",
        "tables": ["metric_data", "metric_aggregations", "metric_thresholds"],
    },
    "chat": {
        "label": "Chat / AI Geçmişi",
        "tables": ["chat_sessions", "chat_messages", "chat_qa_cache", "triage_cache", "knowledge_items"],
    },
    "reports": {
        "label": "Altyapı Raporları / Workflow",
        "tables": ["infrastructure_reports", "workflow_runs"],
    },
    "packages": {
        "label": "Paket & Repo Yönetimi",
        "tables": ["package_files", "package_jobs", "repo_packages", "repo_sources", "repo_sync_jobs"],
    },
    "system_updates": {
        "label": "Sistem Güncelleme İşleri",
        "tables": ["system_update_jobs", "system_update_plans"],
    },
    "audit": {
        "label": "Audit Logları",
        "tables": ["audit_logs"],
    },
}

WIPE_CONFIRM_PHRASE = "TÜM VERİLERİ SİL"


class WipeDataRequest(BaseModel):
    confirm: str
    categories: Optional[List[str]] = None  # None/boş = hepsi


def _resolve_wipe_tables(categories: Optional[List[str]]) -> List[str]:
    ids = categories if categories else list(WIPE_CATEGORIES.keys())
    unknown = [c for c in ids if c not in WIPE_CATEGORIES]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Bilinmeyen kategori: {', '.join(unknown)}")
    tables: List[str] = []
    for cat_id in ids:
        tables.extend(WIPE_CATEGORIES[cat_id]["tables"])
    return tables


def _table_exists(db: Session, table: str) -> bool:
    """Wipe listesinde eski/opsiyonel tablolar olabilir; yoksa silme adımını atla."""
    return bool(
        db.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :t"
            ),
            {"t": table},
        ).scalar()
    )


def _execute_wipe(db: Session, tables: List[str]) -> None:
    """Seçilen tabloları FK kısıtlamalarını bozmadan siler.

    Kategoriler bağımsız seçilebildiği için TRUNCATE ... CASCADE kullanılmaz
    (seçilmeyen tablolara sızabilir); bunun yerine her FK'nın kendi ondelete
    davranışına (CASCADE / SET NULL) güvenen sıralı DELETE kullanılır. Sadece
    ondelete tanımsız (RESTRICT) iki ilişki elle ele alınır:
      - business_service_map.server_id -> servers
      - infrastructure_reports.hypervisor_id -> hypervisors

    DB'de olmayan tablolar (ör. kaldırılmış triage_cache) sessizce atlanır —
    preview zaten bunları 0 sayar; DELETE başarısız olmamalı.
    """
    table_set = set(tables)

    if (
        "hypervisors" in table_set
        and "infrastructure_reports" not in table_set
        and _table_exists(db, "infrastructure_reports")
    ):
        db.execute(text('UPDATE infrastructure_reports SET hypervisor_id = NULL WHERE hypervisor_id IS NOT NULL'))

    def _sort_key(t: str) -> int:
        if t == "business_service_map":
            return 0
        if t == "servers":
            return 2
        return 1

    for table in sorted(tables, key=_sort_key):
        if not _table_exists(db, table):
            logger.info("wipe_all_data: tablo yok, atlanıyor: %s", table)
            continue
        db.execute(text(f'DELETE FROM "{table}"'))
        try:
            db.execute(text(f'ALTER SEQUENCE IF EXISTS "{table}_id_seq" RESTART WITH 1'))
        except Exception:
            pass


@router.get("/wipe-all-data/preview")
async def preview_wipe_all_data(
    db: Session = Depends(get_db),
    _user: User = Depends(require_role("admin")),
):
    """Kategori bazında silinecek satır sayılarını döner — onay ekranı için."""
    categories = []
    for cat_id, cat in WIPE_CATEGORIES.items():
        total = 0
        table_counts = {}
        for table in cat["tables"]:
            try:
                count = db.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() or 0
            except Exception:
                count = 0
            if count:
                table_counts[table] = count
            total += count
        categories.append({
            "id": cat_id,
            "label": cat["label"],
            "tables": table_counts,
            "total_rows": total,
        })
    return {
        "categories": categories,
        "total_rows": sum(c["total_rows"] for c in categories),
        "preserved": ["users", "modules", "user_modules", "global_credentials", "app_settings", "cost_config"],
    }


@router.post("/wipe-all-data")
async def wipe_all_data(
    data: WipeDataRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    """Seçilen kategorilerdeki verileri siler (kategori verilmezse tümü).

    Kullanıcı hesapları, modül/rol atamaları, global credential'lar ve
    sistem ayarları (Ollama modeli, retention süresi, WinRM cred vb.)
    her durumda korunur. Geri alınamaz — sadece admin, aynen yazılan onay
    metniyle çalışır.
    """
    if (data.confirm or "").strip() != WIPE_CONFIRM_PHRASE:
        raise HTTPException(
            status_code=400,
            detail=f'Onay metni hatalı. Devam etmek için tam olarak "{WIPE_CONFIRM_PHRASE}" yazmalısınız.',
        )

    tables = _resolve_wipe_tables(data.categories)
    if not tables:
        raise HTTPException(status_code=400, detail="Silinecek kategori seçilmedi")

    try:
        _execute_wipe(db, tables)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("wipe_all_data failed")
        raise HTTPException(status_code=500, detail=f"Veri silme hatası: {str(e)}")

    selected_labels = (
        [WIPE_CATEGORIES[c]["label"] for c in data.categories]
        if data.categories else ["Tüm kategoriler"]
    )

    from app.services.audit import record_audit
    record_audit(
        db,
        category="admin",
        action="admin.wipe_all_data",
        status="success",
        actor=user,
        summary=f"{user.username} veri sildi: {', '.join(selected_labels)}",
        detail={"categories": data.categories or list(WIPE_CATEGORIES.keys()), "tables": tables},
    )

    return {
        "success": True,
        "message": f"Seçilen veriler silindi ({', '.join(selected_labels)}). Kullanıcılar, modül yetkileri ve sistem ayarları korundu.",
    }


# ─── Tam veritabanı yedek / geri yükleme (pg_dump) ───────────────────────────

@router.get("/db-backup/capability")
def db_backup_capability(_admin: User = Depends(require_role("admin"))):
    from app.services import db_migration_backup as dmb
    return dmb.capability()


@router.get("/db-backup/export")
def db_backup_export(
    request: Request,
    include_dropt: bool = True,
    include_migration_secrets: bool = True,
    admin: User = Depends(require_role("admin")),
):
    """ainew (+ opsiyonel Dropt) PostgreSQL dump zip indir."""
    import shutil
    from fastapi.responses import FileResponse
    from app.services import db_migration_backup as dmb
    from app.services.audit import record_audit

    try:
        zip_path, manifest = dmb.create_backup_zip(
            include_dropt=include_dropt,
            include_migration_secrets=include_migration_secrets,
        )
    except Exception as e:
        record_audit(
            None,
            category="admin",
            action="db_backup.export",
            status="failed",
            actor=admin,
            summary=f"DB yedek başarısız: {e}",
            detail={"error": str(e)[:400]},
            ip_address=request.client.host if request.client else None,
        )
        raise HTTPException(503, f"Yedek alınamadı: {e}")

    secrets_meta = (manifest.get("migration_secrets") or {})
    record_audit(
        None,
        category="admin",
        action="db_backup.export",
        status="success",
        actor=admin,
        summary="Tam veritabanı yedeği indirildi",
        detail={
            "include_dropt": include_dropt,
            "include_migration_secrets": include_migration_secrets,
            "migration_secrets_included": bool(secrets_meta.get("included")),
            "ainew_bytes": ((manifest.get("databases") or {}).get("ainew") or {}).get("size_bytes"),
            "dropt_included": ((manifest.get("databases") or {}).get("dropt") or {}).get("included"),
        },
        ip_address=request.client.host if request.client else None,
    )

    cleanup_dir = zip_path.parent

    def _cleanup():
        try:
            shutil.rmtree(cleanup_dir, ignore_errors=True)
        except Exception:
            pass

    # Background cleanup after send — FileResponse + BackgroundTask
    from starlette.background import BackgroundTask

    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=zip_path.name,
        background=BackgroundTask(_cleanup),
    )


@router.post("/db-backup/validate")
async def db_backup_validate(
    file: UploadFile = File(...),
    _admin: User = Depends(require_role("admin")),
):
    """Yüklenen zip'i doğrula (restore öncesi önizleme)."""
    import tempfile
    from pathlib import Path
    from app.services import db_migration_backup as dmb

    suffix = Path(file.filename or "backup.zip").suffix or ".zip"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        raw = await file.read()
        tmp.write(raw)
        tmp_path = Path(tmp.name)
    try:
        parsed = dmb.validate_backup_zip(tmp_path)
        man = parsed["manifest"]
        return {
            "ok": True,
            "manifest": {
                "format": man.get("format"),
                "format_version": man.get("format_version"),
                "app_version": man.get("app_version"),
                "exported_at": man.get("exported_at"),
                "secret_key_fingerprint": man.get("secret_key_fingerprint"),
                "migration_secrets": {
                    "included": bool(parsed.get("has_migration_secrets")),
                    "secret_key_fingerprint": parsed.get("zip_secret_key_fingerprint"),
                },
                "databases": man.get("databases"),
                "warnings": man.get("warnings"),
            },
            "fingerprint_match": parsed["fingerprint_match"],
            "current_fingerprint": parsed["current_fingerprint"],
            "zip_secret_key_fingerprint": parsed.get("zip_secret_key_fingerprint"),
            "has_migration_secrets": bool(parsed.get("has_migration_secrets")),
            "has_dropt": bool(parsed.get("dropt_sql")),
            "ainew_size_bytes": len(parsed["ainew_sql"] or b""),
            "dropt_size_bytes": len(parsed["dropt_sql"] or b"") if parsed.get("dropt_sql") else 0,
            "restore_confirm_phrase": dmb.RESTORE_CONFIRM,
        }
    except Exception as e:
        raise HTTPException(400, str(e))
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


@router.post("/db-backup/restore")
async def db_backup_restore(
    request: Request,
    file: UploadFile = File(...),
    confirm: str = Form(...),
    restore_ainew: bool = Form(True),
    restore_dropt: bool = Form(True),
    require_fingerprint_match: bool = Form(True),
    apply_migration_secrets: bool = Form(True),
    admin: User = Depends(require_role("admin")),
):
    """
    Tam DB geri yükleme. Mevcut verinin üzerine yazar.
    confirm alanı tam olarak: VERITABANI GERI YUKLE
    apply_migration_secrets: zip içindeki migration-secrets.env → hedef .env
    """
    import tempfile
    from pathlib import Path
    from app.services import db_migration_backup as dmb
    from app.services.audit import record_audit

    suffix = Path(file.filename or "backup.zip").suffix or ".zip"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        result = dmb.restore_backup_zip(
            tmp_path,
            confirm=confirm,
            restore_ainew=restore_ainew,
            restore_dropt=restore_dropt,
            require_fingerprint_match=require_fingerprint_match,
            apply_migration_secrets=apply_migration_secrets,
        )
    except ValueError as e:
        record_audit(
            None,
            category="admin",
            action="db_backup.restore",
            status="failed",
            actor=admin,
            summary=f"DB restore reddedildi: {e}",
            ip_address=request.client.host if request.client else None,
        )
        raise HTTPException(400, str(e))
    except Exception as e:
        record_audit(
            None,
            category="admin",
            action="db_backup.restore",
            status="failed",
            actor=admin,
            summary=f"DB restore başarısız: {e}",
            detail={"error": str(e)[:500]},
            ip_address=request.client.host if request.client else None,
        )
        raise HTTPException(503, f"Geri yükleme başarısız: {e}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    # Audit: secret değerleri yazma
    audit_detail = {
        k: v for k, v in (result or {}).items()
        if k != "migration_secrets"
    }
    ms = (result or {}).get("migration_secrets") or {}
    audit_detail["migration_secrets"] = {
        "applied": ms.get("applied"),
        "skipped": ms.get("skipped"),
        "install_dir": ms.get("install_dir"),
        "artifact": ms.get("artifact"),
        "errors": ms.get("errors"),
        "recreate_required": ms.get("recreate_required"),
    }

    record_audit(
        None,
        category="admin",
        action="db_backup.restore",
        status="success",
        actor=admin,
        summary="Tam veritabanı geri yüklendi",
        detail=audit_detail,
        ip_address=request.client.host if request.client else None,
    )

    msg = "Veritabanı geri yüklendi."
    if ms.get("applied"):
        msg += (
            " Secret'lar .env dosyalarına yazıldı — "
            "docker compose up -d --force-recreate backend worker (+ dropt) çalıştırın, "
            "sonra oturumu yenileyin."
        )
    elif ms.get("artifact"):
        msg += f" Secret artefaktı: {ms.get('artifact')} — elle uygulayıp recreate edin."
    else:
        msg += " Oturumu yenileyin; gerekirse backend/worker'ı yeniden başlatın."

    return {
        "ok": True,
        "message": msg,
        "result": result,
    }


@router.get("/db-backup/migration-secrets")
def db_backup_migration_secrets_status(_admin: User = Depends(require_role("admin"))):
    """Taşıma secret fingerprint özeti (plaintext yok)."""
    from app.services import migration_secrets as ms

    return ms.public_status()


@router.get("/db-backup/migration-secrets/export")
def db_backup_migration_secrets_export(
    request: Request,
    confirm: str = "",
    include_db_passwords: bool = True,
    admin: User = Depends(require_role("admin")),
):
    """Hedefe yapıştırılacak migration .env dosyasını indir (audit'li)."""
    from datetime import datetime, timezone
    from fastapi.responses import Response
    from app.services import migration_secrets as ms
    from app.services.audit import record_audit

    if (confirm or "").strip() != ms.EXPORT_CONFIRM:
        raise HTTPException(
            400,
            f"Onay metni gerekli: {ms.EXPORT_CONFIRM}",
        )

    try:
        body, meta = ms.build_export_env_text(include_db_passwords=include_db_passwords)
    except Exception as e:
        record_audit(
            None,
            category="admin",
            action="db_backup.migration_secrets_export",
            status="failed",
            actor=admin,
            summary=f"Taşıma secret export başarısız: {e}",
            detail={"error": str(e)[:400]},
            ip_address=request.client.host if request.client else None,
        )
        raise HTTPException(503, f"Export alınamadı: {e}")

    record_audit(
        None,
        category="admin",
        action="db_backup.migration_secrets_export",
        status="success",
        actor=admin,
        summary="Taşıma secret dosyası indirildi",
        detail={
            "include_db_passwords": include_db_passwords,
            "secret_key_fingerprint": meta.get("secret_key_fingerprint"),
            "fernet_present": any(
                k.get("key") == "FERNET_KEY" and k.get("present") for k in (meta.get("keys") or [])
            ),
            "ready_for_full_migrate": meta.get("ready_for_full_migrate"),
        },
        ip_address=request.client.host if request.client else None,
    )

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"ainew-migrate-secrets-{ts}.env"
    return Response(
        content=body.encode("utf-8"),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
