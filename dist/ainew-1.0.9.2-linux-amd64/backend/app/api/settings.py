"""
Settings API - Global Credentials CRUD + Apply to Servers
"""
import logging
import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import text
from typing import List, Optional
from pydantic import BaseModel
from app.core.database import get_db
from app.core.auth import get_current_user, require_role
from app.models.credential import GlobalCredential
from app.models.server import Server
from app.models.app_settings import AppSettings
from app.models.user import User
from app.core.encryption import encrypt_secret, decrypt_secret

logger = logging.getLogger(__name__)
router = APIRouter()


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
            from concurrent.futures import ThreadPoolExecutor, as_completed
            from app.services.ssh_manager import SSHManager

            def _one(snap: dict) -> tuple:
                try:
                    ssh = SSHManager(
                        host=snap["ip"],
                        username=username,
                        password=plain_password,
                        private_key=plain_key,
                        port=port,
                    )
                    ok = bool(ssh.connect())
                    ssh.close()
                    return snap["id"], ok
                except Exception:
                    return snap["id"], False

            logger.info(
                "Credential apply SSH (arka plan): %s sunucu, workers=%s",
                len(targets_snap),
                workers,
            )
            results: dict = {}
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cred-apply-ssh") as pool:
                futs = [pool.submit(_one, t) for t in targets_snap]
                done = 0
                for fut in as_completed(futs):
                    sid, ok = fut.result()
                    results[sid] = ok
                    done += 1
                    if done % 100 == 0 or done == len(targets_snap):
                        logger.info("Credential SSH (arka plan) %s/%s", done, len(targets_snap))

            bg = SessionLocal()
            try:
                ok_n = fail_n = 0
                for sid, ok in results.items():
                    row = bg.query(Server).filter(Server.id == sid).first()
                    if row is None:
                        continue
                    row.ai_ready = ok
                    if ok:
                        ok_n += 1
                    else:
                        fail_n += 1
                bg.commit()
                logger.info(
                    "Credential '%s' AI Ready tamamlandı: ok=%s fail=%s",
                    cred_name, ok_n, fail_n,
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


@router.post("/credentials/test-all-ssh")
async def test_all_servers_ssh(db: Session = Depends(get_db)):
    """Linux sunucularda SSH test et (Windows hariç)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
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

    successful = []
    failed = []
    skipped = []
    key_deployed = []

    test_targets = []
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

    workers = bulk_ssh_workers()
    logger.info("test-all-ssh: %s sunucu, workers=%s", len(test_targets), workers)

    def _test_one(snap: dict) -> dict:
        try:
            from app.services.ssh_manager import SSHManager
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

    by_id = {s.id: s for s in servers}
    done = 0
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="test-all-ssh") as pool:
        futures = [pool.submit(_test_one, t) for t in test_targets]
        for fut in as_completed(futures):
            row = fut.result()
            srv = by_id.get(row["id"])
            if srv is not None:
                srv.ai_ready = row["ok"]
            if row["ok"]:
                successful.append(row["name"])
                if row.get("key_ok"):
                    key_deployed.append(row["name"])
            else:
                failed.append(row["name"])
            done += 1
            if done % 100 == 0 or done == len(test_targets):
                logger.info("test-all-ssh ilerlemesi %s/%s", done, len(test_targets))

    db.commit()

    msg = f"SSH Test tamamlandı. Başarılı: {len(successful)}, Başarısız: {len(failed)}, Atlandı: {len(skipped)}"
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

    return {
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
    """Gelişmiş ayarları kaydet. Restart gerekmez (cache 15sn)."""
    from app.services.runtime_settings import save_advanced_settings, ADVANCED_SCHEMA
    if not isinstance(body.settings, dict) or not body.settings:
        raise HTTPException(status_code=400, detail="settings sözlüğü gerekli")
    unknown = [k for k in body.settings if k not in ADVANCED_SCHEMA]
    saved = save_advanced_settings(body.settings, db)
    return {
        "success": True,
        "saved": saved,
        "unknown_keys": unknown,
        "message": f"{len(saved)} ayar kaydedildi. Arka plan görevleri bir sonraki döngüde yeni aralığı kullanır.",
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
    """Aktif Ollama modelini kaydet"""
    model = (payload.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="Model adı boş olamaz")
    row = db.query(AppSettings).filter(AppSettings.key == "ollama_active_model").first()
    if row:
        row.value = model
    else:
        db.add(AppSettings(key="ollama_active_model", value=model))
    db.commit()
    logger.info(f"Aktif Ollama modeli guncellendi: {model}")
    return {"success": True, "model": model}


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

    db.commit()

    # Runtime'a hemen yansıt (restart beklemeden) — management_server_ip ile aynı desen.
    settings.REMOTE_LLM_ENABLED = enabled
    settings.REMOTE_LLM_URL = url
    settings.REMOTE_LLM_MODEL = model
    settings.REMOTE_LLM_VERIFY_SSL = verify_ssl
    settings.REMOTE_LLM_CA_BUNDLE = ca_bundle
    if api_key_raw:
        settings.REMOTE_LLM_API_KEY = api_key_raw

    logger.info(
        f"Uzak AI gateway güncellendi: enabled={enabled} url={url} model={model} "
        f"verify_ssl={verify_ssl} ca_bundle={'set' if ca_bundle else 'unset'}"
    )
    return {"success": True, "enabled": enabled, "url": url, "model": model, "verify_ssl": verify_ssl, "ca_bundle": ca_bundle}


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


# ─── Config Backup / Restore ──────────────────────────

@router.get("/config/backup")
async def config_backup(db: Session = Depends(get_db)):
    """Uygulama ayarlarını JSON olarak yedekle (app_settings, credential metadata)."""
    import datetime
    app_settings = {}
    for row in db.query(AppSettings).all():
        if row.key and row.value is not None:
            app_settings[row.key] = row.value

    credentials_meta = []
    for c in db.query(GlobalCredential).order_by(GlobalCredential.name).all():
        credentials_meta.append({
            "name": c.name,
            "username": c.username,
            "port": c.port,
            "is_default": c.is_default,
            "has_password": bool(c.password),
            "has_private_key": bool(c.private_key),
        })

    return {
        "version": "1.0",
        "exported_at": datetime.datetime.utcnow().isoformat() + "Z",
        "app_settings": app_settings,
        "credentials_meta": credentials_meta,
    }


class ConfigRestoreRequest(BaseModel):
    app_settings: Optional[dict] = None


@router.post("/config/restore")
async def config_restore(data: ConfigRestoreRequest, db: Session = Depends(get_db)):
    """Yedekten app_settings'i geri yükle."""
    if not data.app_settings:
        return {"success": True, "message": "Restore edilecek app_settings yok", "restored": 0}

    restored = 0
    for key, value in data.app_settings.items():
        if not key or value is None:
            continue
        row = db.query(AppSettings).filter(AppSettings.key == key).first()
        if row:
            row.value = str(value)
        else:
            db.add(AppSettings(key=key, value=str(value)))
        restored += 1

    db.commit()
    return {"success": True, "message": f"{restored} ayar geri yüklendi", "restored": restored}


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
