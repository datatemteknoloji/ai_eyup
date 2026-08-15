"""Level 1 ↔ Dropt Ops sidecar integration.

- Exchange ainew JWT for Dropt portal token (bridge)
- Upsert ainew Linux servers into Dropt target_servers
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_role
from app.core.database import get_db
from app.models.server import Server
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


def _dropt_base() -> str:
    return (os.getenv("DROPT_API_URL") or "http://127.0.0.1:8001").rstrip("/")


def _bridge_secret() -> str:
    return (os.getenv("AINEW_BRIDGE_SECRET") or "").strip()


class DroptSessionOut(BaseModel):
    access_token: str
    expires_in_minutes: int = 480
    dropt_username: str
    dropt_role: str


class EnsureServerOut(BaseModel):
    ainew_server_id: int
    dropt_server_id: int
    hostname: str
    ip: str
    created: bool = False


@router.post("/dropt-session", response_model=DroptSessionOut)
def create_dropt_session(user: User = Depends(get_current_user)) -> DroptSessionOut:
    secret = _bridge_secret()
    if not secret:
        raise HTTPException(500, detail="AINEW_BRIDGE_SECRET tanımlı değil")
    role = "admin" if user.role in ("admin", "superadmin") else "operator"
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.post(
                f"{_dropt_base()}/api/auth/bridge",
                headers={"X-Ainew-Bridge-Secret": secret, "Content-Type": "application/json"},
                json={"username": user.username, "role": role, "full_name": user.full_name or ""},
            )
    except httpx.RequestError as exc:
        logger.error("Dropt bridge unreachable: %s", exc)
        raise HTTPException(503, detail=f"Dropt API erişilemiyor: {exc}") from exc
    if r.status_code >= 400:
        _raise_dropt_upstream(r.status_code, r.text[:500] or "Dropt bridge hatası")
    data = r.json()
    token = (data.get("token") or {}).get("access_token")
    if not token:
        raise HTTPException(502, detail="Dropt token alınamadı")
    du = data.get("user") or {}
    return DroptSessionOut(
        access_token=token,
        expires_in_minutes=int((data.get("token") or {}).get("expires_in_minutes") or 480),
        dropt_username=str(du.get("username") or user.username),
        dropt_role=str(du.get("role") or role),
    )


def _raise_dropt_upstream(status_code: int, detail: str) -> None:
    """Dropt hata kodunu ainew JWT 401'inden ayır — aksi halde FE oturumu düşer."""
    # authStore her /api/v1 401'inde clearToken yapıyor; upstream 401/403 ≠ ainew oturumu
    if status_code in (401, 403):
        raise HTTPException(502, detail=detail)
    raise HTTPException(status_code, detail=detail)


def _dropt_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@router.get("/linux-servers")
def list_linux_servers_for_level1(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Ainew → Level 1 sync adayları: AI Ready + (RHEL|Oracle Linux) + IP; Exadata hariç.

    Linux modülü görünürlüğünden bağımsız — Exadata bağlı sunucular burada yok
    (ileride Linux listesinde görünseler bile Dropt adayı değiller).
    """
    _ = user
    from app.services.level1_inventory import eligible_for_level1_dropt_sync
    from app.services.platform_scope import get_exadata_server_id_set

    exadata_ids = get_exadata_server_id_set(db)
    q = db.query(Server).filter(
        Server.ip_address.isnot(None),
        Server.ip_address != "",
        Server.ai_ready.is_(True),  # noqa: E712
    )
    rows = q.order_by(Server.name.asc()).limit(5000).all()
    out = []
    for s in rows:
        if not eligible_for_level1_dropt_sync(s, exadata_ids=exadata_ids):
            continue
        out.append({
            "id": s.id,
            "name": s.name,
            "hostname": s.hostname or s.vm_guest_hostname or s.name,
            "ip_address": s.ip_address,
            "status": s.status,
            "os_version": s.os_version,
            "os_type": s.os_type,
            "os_pretty": ((s.os_version or "").strip() or (s.vm_guest_os_full or "").strip()),
            "server_type": s.server_type,
            "tier": s.tier,
            "ai_ready": bool(s.ai_ready),
        })
    return out


class EnsureBody(BaseModel):
    dropt_token: str = Field(min_length=10)


@router.post("/servers/{server_id}/ensure", response_model=EnsureServerOut)
def ensure_dropt_server(
    server_id: int,
    body: EnsureBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EnsureServerOut:
    """Map ainew Server → Dropt TargetServer (upsert by IP)."""
    s = db.query(Server).filter(Server.id == server_id).first()
    if not s or not s.ip_address:
        raise HTTPException(404, detail="Sunucu bulunamadı veya IP yok")
    hostname = (s.hostname or s.vm_guest_hostname or s.name or s.ip_address).strip()
    ip = s.ip_address.strip()
    token = body.dropt_token

    try:
        with httpx.Client(timeout=30.0) as client:
            # Pre-list to know create vs update
            existed_id: Optional[int] = None
            lr = client.get(
                f"{_dropt_base()}/api/servers",
                headers=_dropt_headers(token),
                params={"page_size": 200, "q": ip},
            )
            if lr.status_code < 400:
                payload = lr.json()
                items = (
                    payload
                    if isinstance(payload, list)
                    else payload.get("items") or payload.get("servers") or []
                )
                for it in items:
                    if str(it.get("ip") or "").strip() == ip:
                        existed_id = int(it["id"])
                        break

            # Always upsert so automation credentials stay in sync with Level 1 Settings
            cr = client.post(
                f"{_dropt_base()}/api/servers/ensure-host",
                headers=_dropt_headers(token),
                json={
                    "hostname": hostname,
                    "ip": ip,
                    "port": 22,
                    "description": (
                        f"ainew:{s.id} {(s.name or '').strip()}".strip()[:512]
                    ),
                    "skip_connection_test": False,
                    "ainew_ai_ready": bool(s.ai_ready),
                },
            )
            if cr.status_code >= 400:
                _raise_dropt_upstream(
                    cr.status_code, f"Dropt ensure-host: {cr.text[:400]}"
                )
            result = cr.json()
            dropt_id = int(result["id"])
            if (result.get("status") or "").lower() == "unreachable":
                try:
                    client.delete(
                        f"{_dropt_base()}/api/servers/{dropt_id}",
                        headers=_dropt_headers(token),
                    )
                except Exception:  # noqa: BLE001
                    pass
                raise HTTPException(
                    422,
                    detail="Otomasyon SSH unreachable — Level 1'e eklenmedi",
                )
            return EnsureServerOut(
                ainew_server_id=s.id,
                dropt_server_id=dropt_id,
                hostname=str(result.get("hostname") or hostname),
                ip=str(result.get("ip") or ip),
                created=existed_id is None,
            )
    except httpx.RequestError as exc:
        raise HTTPException(503, detail=f"Dropt API erişilemiyor: {exc}") from exc


class SyncAllOut(BaseModel):
    total: int = 0
    ensured: int = 0
    created: int = 0
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)
    job_id: Optional[str] = None
    status: Optional[str] = None
    message: Optional[str] = None


@router.post("/servers/sync-all", response_model=SyncAllOut)
def sync_all_linux_servers_to_dropt(
    body: EnsureBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    background: bool = Query(True, description="True: arka planda job; False: senkron bulk"),
) -> SyncAllOut:
    """Ainew AI Ready + RHEL|Oracle Linux envanterini Dropt'a yaz (Exadata hariç; SSH testi yok)."""
    from app.services import bulk_job_tracker as jobs

    linux = list_linux_servers_for_level1(db, user)
    hosts_payload = []
    skipped = 0
    for row in linux:
        ip = (row.get("ip_address") or "").strip()
        if not ip:
            skipped += 1
            continue
        hostname = (row.get("hostname") or row.get("name") or ip).strip()
        ainew_name = (row.get("name") or "").strip()
        desc = f"ainew:{row.get('id')}"
        if ainew_name:
            desc = f"{desc} {ainew_name}"[:512]
        st = (row.get("server_type") or "").upper()
        machine_type = "virtual" if st == "VIRTUAL" else ("physical" if st == "PHYSICAL" else "")
        hosts_payload.append({
            "hostname": hostname,
            "ip": ip,
            "port": 22,
            "description": desc,
            # Sync maliyeti / banner timeout: ainew AI Ready yeter; Dropt SSH bootstrap yok
            "skip_connection_test": True,
            "ainew_ai_ready": bool(row.get("ai_ready")),
            "os_pretty": (row.get("os_pretty") or row.get("os_version") or "").strip()[:255],
            "machine_type": machine_type,
        })

    if not hosts_payload:
        return SyncAllOut(total=len(linux), ensured=0, created=0, skipped=skipped, status="done")

    token = body.dropt_token

    def _run_bulk(job_id: Optional[str] = None) -> SyncAllOut:
        ensured = created = 0
        errors: list[str] = []
        # Chunk to keep Dropt payload bounded
        chunk_size = 500
        try:
            with httpx.Client(timeout=120.0) as client:
                for i in range(0, len(hosts_payload), chunk_size):
                    chunk = hosts_payload[i : i + chunk_size]
                    if job_id:
                        jobs.tick(
                            job_id,
                            done=i,
                            total=len(hosts_payload),
                            message=f"Dropt bulk ensure {i}/{len(hosts_payload)}",
                        )
                    cr = client.post(
                        f"{_dropt_base()}/api/servers/ensure-hosts-bulk",
                        headers=_dropt_headers(token),
                        json={"hosts": chunk},
                    )
                    if cr.status_code >= 400:
                        errors.append(f"bulk chunk@{i}: {cr.text[:400]}")
                        continue
                    data = cr.json()
                    ensured += int(data.get("ensured") or 0)
                    created += int(data.get("created") or 0)
                    errors.extend(list(data.get("errors") or [])[:20])
        except httpx.RequestError as exc:
            errors.append(f"Dropt API erişilemiyor: {exc}")
        out = SyncAllOut(
            total=len(linux),
            ensured=ensured,
            created=created,
            skipped=skipped,
            errors=errors[:50],
            status="done",
        )
        if job_id:
            jobs.finish(
                job_id,
                status="done" if not errors else "done",
                message=f"Dropt sync: {ensured} ensured, {created} created",
                result=out.model_dump(),
            )
        return out

    if not background:
        return _run_bulk()

    job_id = jobs.create_job(
        "dropt_sync_all",
        "Level 1 Dropt envanter senkronu",
        total=len(hosts_payload),
        message="Dropt bulk ensure başlıyor...",
    )

    def _bg() -> None:
        try:
            _run_bulk(job_id)
        except Exception as exc:  # noqa: BLE001
            jobs.finish(job_id, status="error", message=str(exc), error=str(exc))

    import threading
    threading.Thread(target=_bg, daemon=True, name=f"dropt-sync-{job_id}").start()
    return SyncAllOut(
        total=len(linux),
        ensured=0,
        created=0,
        skipped=skipped,
        job_id=job_id,
        status="running",
        message="Arka planda Dropt bulk sync başladı",
    )


class SyncAssistantOut(BaseModel):
    ok: bool
    mode: str
    model: str
    detail: str = ""


@router.post("/sync-assistant-llm", response_model=SyncAssistantOut)
def sync_assistant_llm_from_ainew(
    body: EnsureBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SyncAssistantOut:
    """Push ainew AI Ayarları (Ollama / Remote LLM) into Dropt Ops Assistant settings.

    Level 1 no longer has its own assistant model panel — Dropt FAB uses host AI config.
    """
    del user  # auth gate only
    from urllib.parse import urlparse

    from app.core.config import get_active_model, settings

    remote_on = bool(getattr(settings, "REMOTE_LLM_ENABLED", False))
    patch: dict[str, Any] = {"assistant_enabled": True}
    active_ollama = get_active_model(db)

    if remote_on and (getattr(settings, "REMOTE_LLM_URL", "") or "").strip():
        url = settings.REMOTE_LLM_URL.strip().rstrip("/")
        model = (getattr(settings, "REMOTE_LLM_MODEL", None) or active_ollama or "").strip()
        patch.update(
            {
                "assistant_ollama_mode": "gateway",
                "assistant_gateway_url": url,
                "assistant_model": model,
            }
        )
        api_key = (getattr(settings, "REMOTE_LLM_API_KEY", None) or "").strip()
        if api_key:
            patch["assistant_gateway_api_key"] = api_key
        mode = "gateway"
    else:
        ollama = (getattr(settings, "OLLAMA_URL", None) or "http://127.0.0.1:11434").strip()
        parsed = urlparse(ollama if "://" in ollama else f"http://{ollama}")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 11434
        patch.update(
            {
                "assistant_ollama_mode": "direct",
                "assistant_direct_host": host,
                "assistant_direct_port": port,
                "assistant_model": active_ollama,
            }
        )
        mode = "direct"

    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.patch(
                f"{_dropt_base()}/api/settings",
                headers=_dropt_headers(body.dropt_token),
                json=patch,
            )
    except httpx.RequestError as exc:
        raise HTTPException(503, detail=f"Dropt API erişilemiyor: {exc}") from exc
    if r.status_code >= 400:
        _raise_dropt_upstream(
            r.status_code, f"Dropt assistant sync: {r.text[:400]}"
        )
    return SyncAssistantOut(
        ok=True,
        mode=mode,
        model=str(patch.get("assistant_model") or ""),
        detail="Asistan, ainew AI Ayarları ile senkronize edildi",
    )


# ── Envanter SoT: Ops / Excel → ainew servers → Dropt ensure ─────────────────


class InventoryCreateIn(BaseModel):
    dropt_token: str = Field(min_length=10)
    hostname: str = Field(min_length=1, max_length=255)
    ip: str = Field(min_length=3, max_length=64)
    os_type: str = Field(default="linux")
    name: Optional[str] = None
    # Opsiyonel ainew yönetim SSH (boşsa GlobalCredential / datatem)
    ssh_username: Optional[str] = None
    ssh_password: Optional[str] = None
    ssh_port: Optional[int] = None


class InventoryCreateOut(BaseModel):
    ainew_server_id: int
    dropt_server_id: Optional[int] = None
    hostname: str
    ip: str
    server_type: str
    created: bool
    skipped: bool = False
    detected: bool = False
    message: str = ""


class InventoryImportRowIn(BaseModel):
    dropt_token: str = Field(min_length=10)
    hostname: str
    ip: str
    os_type: str = "linux"


class InventoryImportRowOut(BaseModel):
    hostname: str
    ip: str
    status: str  # ready | skipped | error
    message: str
    ainew_server_id: Optional[int] = None
    dropt_server_id: Optional[int] = None
    server_id: Optional[int] = None  # Dropt FE uyumu
    server_type: Optional[str] = None


@router.post("/inventory/servers", response_model=InventoryCreateOut)
def inventory_create_server(
    body: InventoryCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
) -> InventoryCreateOut:
    """Ops Center Sunucu ekle — ainew SoT + Dropt ensure + otomatik PHYSICAL/VIRTUAL."""
    from app.services.level1_inventory import create_or_get_ainew_server, ensure_and_detect

    _ = user
    override: dict[str, Any] = {}
    if body.ssh_username:
        override["username"] = body.ssh_username.strip()
    if body.ssh_password:
        override["password"] = body.ssh_password
    if body.ssh_port:
        override["port"] = int(body.ssh_port)

    server, created = create_or_get_ainew_server(
        db,
        hostname=body.hostname,
        ip=body.ip,
        server_type="UNKNOWN",
        os_type=body.os_type or "linux",
        name=body.name,
        connection_override=override or None,
        source="level1-ops",
    )
    msg = "Mevcut ainew kaydı" if not created else "Ainew envantere eklendi"
    dropt_id, detect = ensure_and_detect(
        db,
        server,
        dropt_base=_dropt_base(),
        dropt_token=body.dropt_token,
    )
    db.refresh(server)
    if detect.get("ensure_error"):
        msg += f"; Dropt ensure uyarı: {detect['ensure_error']}"
    elif dropt_id:
        msg += "; Dropt ensure OK"
    if detect.get("detected"):
        msg += f"; tip={server.server_type} ({detect.get('source')})"
    else:
        msg += "; tip henüz tespit edilemedi (UNKNOWN)"
    return InventoryCreateOut(
        ainew_server_id=server.id,
        dropt_server_id=dropt_id,
        hostname=server.hostname or body.hostname,
        ip=server.ip_address or body.ip,
        server_type=server.server_type or "UNKNOWN",
        created=created,
        skipped=not created,
        detected=bool(detect.get("detected")),
        message=msg,
    )


@router.post("/inventory/import/parse")
async def inventory_import_parse(
    file: UploadFile = File(...),
    user: User = Depends(require_role("admin")),
):
    """Excel/CSV parse — satırlar ainew import/row ile yazılır."""
    from app.services.inventory_import import parse_inventory_file

    _ = user
    raw = await file.read()
    if not raw:
        raise HTTPException(400, detail="Dosya boş")
    try:
        rows = parse_inventory_file(file.filename or "inventory.csv", raw)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    return {"rows": rows, "total": len(rows)}


@router.post("/inventory/import/row", response_model=InventoryImportRowOut)
def inventory_import_row(
    body: InventoryImportRowIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
) -> InventoryImportRowOut:
    """Excel satırı → ainew + Dropt ensure + otomatik tip tespiti."""
    from app.services.level1_inventory import create_or_get_ainew_server, ensure_and_detect

    _ = user
    try:
        server, created = create_or_get_ainew_server(
            db,
            hostname=body.hostname,
            ip=body.ip,
            server_type="UNKNOWN",
            os_type=body.os_type or "linux",
            source="level1-excel",
        )
    except Exception as exc:  # noqa: BLE001
        return InventoryImportRowOut(
            hostname=body.hostname,
            ip=body.ip,
            status="error",
            message=str(exc),
        )

    dropt_id, detect = ensure_and_detect(
        db,
        server,
        dropt_base=_dropt_base(),
        dropt_token=body.dropt_token,
    )
    db.refresh(server)
    st = server.server_type or "UNKNOWN"
    tip = f"tip={st}"
    if detect.get("detected"):
        tip += f" ({detect.get('source')})"

    if not created:
        return InventoryImportRowOut(
            hostname=body.hostname,
            ip=body.ip,
            status="skipped",
            message=f"Zaten ainew kaydı (id={server.id}); {tip}",
            ainew_server_id=server.id,
            dropt_server_id=dropt_id,
            server_id=dropt_id,
            server_type=st,
        )

    if dropt_id and detect.get("detected"):
        status = "ready"
        message = f"Ainew + Dropt OK; {tip}"
    elif dropt_id:
        status = "ready"
        message = f"Ainew + Dropt OK; {tip}"
    else:
        status = "unreachable"
        message = f"Ainew oluşturuldu; Dropt/detect: {detect.get('ensure_error') or tip}"

    return InventoryImportRowOut(
        hostname=body.hostname,
        ip=body.ip,
        status=status,
        message=message,
        ainew_server_id=server.id,
        dropt_server_id=dropt_id,
        server_id=dropt_id,
        server_type=st,
    )


class InventoryUpdateIn(BaseModel):
    dropt_token: str = Field(min_length=10)
    current_ip: str
    hostname: str
    ip: str
    dropt_server_id: Optional[int] = None


class InventoryDeleteIn(BaseModel):
    dropt_token: str = Field(min_length=10)
    ip: str
    dropt_server_id: Optional[int] = None


@router.post("/inventory/servers/update", response_model=InventoryCreateOut)
def inventory_update_server(
    body: InventoryUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
) -> InventoryCreateOut:
    """Ops düzenle — ainew kaydını IP ile bul/güncelle + Dropt ensure."""
    from app.services.level1_inventory import ensure_dropt_for_server, find_server_by_ip_or_hostname

    _ = user
    server = find_server_by_ip_or_hostname(db, ip=body.current_ip.strip(), hostname="")
    if not server:
        server = find_server_by_ip_or_hostname(db, ip=body.ip.strip(), hostname=body.hostname.strip())
    if not server:
        raise HTTPException(404, detail="Ainew envanterinde bu IP ile sunucu yok — önce ekleyin veya sync yapın")
    server.hostname = body.hostname.strip()
    server.ip_address = body.ip.strip()
    if server.name == body.current_ip or not server.name:
        server.name = body.hostname.strip()
    db.commit()
    db.refresh(server)
    dropt_id = body.dropt_server_id
    msg = "Ainew güncellendi"
    try:
        result = ensure_dropt_for_server(
            dropt_base=_dropt_base(),
            dropt_token=body.dropt_token,
            server=server,
        )
        dropt_id = int(result["id"]) if result.get("id") is not None else dropt_id
        msg += "; Dropt ensure OK"
    except Exception as exc:  # noqa: BLE001
        msg += f"; Dropt: {exc}"
    return InventoryCreateOut(
        ainew_server_id=server.id,
        dropt_server_id=dropt_id,
        hostname=server.hostname or body.hostname,
        ip=server.ip_address or body.ip,
        server_type=server.server_type or "PHYSICAL",
        created=False,
        message=msg,
    )


@router.post("/inventory/servers/delete")
def inventory_delete_server(
    body: InventoryDeleteIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    """Ops sil — ainew + Dropt."""
    from app.services.level1_inventory import find_server_by_ip_or_hostname

    _ = user
    server = find_server_by_ip_or_hostname(db, ip=body.ip.strip(), hostname="")
    ainew_deleted = False
    if server:
        db.delete(server)
        db.commit()
        ainew_deleted = True
    dropt_deleted = False
    if body.dropt_server_id:
        try:
            with httpx.Client(timeout=20.0) as client:
                r = client.delete(
                    f"{_dropt_base()}/api/servers/{body.dropt_server_id}",
                    headers=_dropt_headers(body.dropt_token),
                )
            dropt_deleted = r.status_code < 400
        except httpx.RequestError as exc:
            logger.warning("Dropt delete failed: %s", exc)
    return {
        "ok": True,
        "ainew_deleted": ainew_deleted,
        "dropt_deleted": dropt_deleted,
    }
