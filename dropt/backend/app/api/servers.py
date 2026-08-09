from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlmodel import Session, col, func, or_, select

from app.api.deps import get_current_user, require_admin
from app.assistant.servers import invalidate_server_index
from app.core.database import get_session
from app.models.server import Credential, ServerStatus, TargetServer
from app.models.user import User
from app.schemas.server import (
    ServerCreate,
    ServerImportParseResponse,
    ServerImportResponse,
    ServerImportRowRequest,
    ServerImportRowResult,
    ServerListResponse,
    ServerPublic,
    ServerUpdate,
)
from app.services.bootstrap import get_automation_password, get_automation_username
from app.services.credential_manager import CredentialCryptoError, CredentialManager
from app.services.server_import import parse_inventory_file
from app.services.ssh_probe import (
    ensure_portal_keypair,
    install_portal_pubkey_with_password,
    probe_ssh_key,
)

router = APIRouter(prefix="/servers", tags=["servers"])


def _public(
    session: Session,
    server: TargetServer,
    cred: Credential | None,
    connection_ok: bool | None = None,
) -> ServerPublic:
    from app.services.machine_type import effective_machine_type

    return ServerPublic(
        id=server.id,  # type: ignore[arg-type]
        hostname=server.hostname,
        ip=server.ip,
        port=server.port,
        status=server.status,
        tags=server.tags,
        description=server.description,
        username=(cred.ssh_username if cred and cred.ssh_username else get_automation_username(session)),
        has_password=bool(cred and cred.encrypted_ssh_password),
        ssh_key_installed=bool(server.ssh_key_installed),
        os_pretty=server.os_pretty or "",
        machine_type=effective_machine_type(server),
        virtualization=server.virtualization or "",
        last_connection_message=server.last_connection_message or "",
        connection_ok=connection_ok,
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


def _get_server_or_404(session: Session, server_id: int) -> TargetServer:
    server = session.get(TargetServer, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sunucu bulunamadı")
    return server


def _refresh_inventory_facts(session: Session, server: TargetServer) -> None:
    """Pull OS / virt type after a successful SSH connection."""
    try:
        from app.services.server_facts import collect_server_facts

        facts = collect_server_facts(session, server)
        if not facts.get("reachable") and not facts.get("ok"):
            return
        os_label = (facts.get("os_pretty") or facts.get("os_name") or "").strip()
        if facts.get("os_version") and facts.get("os_name") and not facts.get("os_pretty"):
            os_label = f"{facts.get('os_name')} {facts.get('os_version')}".strip()
        server.os_pretty = os_label[:255]
        server.machine_type = str(facts.get("machine_type") or "")[:32]
        server.virtualization = str(facts.get("virtualization") or "")[:64]
        from app.services.machine_type import apply_physical_override

        apply_physical_override(server)
    except Exception:
        pass


def _bootstrap_connection(
    session: Session,
    server: TargetServer,
    *,
    host: str,
    port: int,
    username: str,
    password: str,
) -> bool:
    """
    Enroll / re-enroll a host.
    Prefer portal key first (host may already have authorized_keys from a prior import).
    Fall back to password + pubkey install when key auth is not yet available.
    """
    ensure_portal_keypair()

    key_probe = probe_ssh_key(host=host, port=port, username=username)
    if key_probe.ok:
        server.last_connection_message = (
            f"{key_probe.message} · önceki key ile yeniden eklendi"
        )[:1024]
        server.ssh_key_installed = True
        server.status = ServerStatus.ready
        _refresh_inventory_facts(session, server)
        return True

    result = install_portal_pubkey_with_password(
        host=host,
        port=port,
        username=username,
        password=password,
    )
    ok = bool(result.key_installed or result.password_ok)
    server.last_connection_message = result.message[:1024]
    server.ssh_key_installed = result.key_installed
    server.status = ServerStatus.ready if ok else ServerStatus.unreachable
    if ok:
        _refresh_inventory_facts(session, server)
    return ok


def _test_connection(
    session: Session,
    server: TargetServer,
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    force_reinstall: bool = False,
) -> bool:
    """
    Prefer pubkey probe when already installed.
    Only rewrite authorized_keys when key is missing or broken (or forced).
    """
    ensure_portal_keypair()

    if server.ssh_key_installed and not force_reinstall:
        key_probe = probe_ssh_key(host=host, port=port, username=username)
        if key_probe.ok:
            server.last_connection_message = key_probe.message[:1024]
            server.status = ServerStatus.ready
            _refresh_inventory_facts(session, server)
            return True
        # Key flag was stale or host lost authorized_keys — repair below.

    return _bootstrap_connection(
        session,
        server,
        host=host,
        port=port,
        username=username,
        password=password,
    )


@router.get("/defaults")
def server_form_defaults(
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    return {"username": get_automation_username(session), "port": 22}


@router.get("", response_model=ServerListResponse)
def list_servers(
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    q: str | None = Query(default=None, description="hostname or IP search"),
    status_filter: ServerStatus | None = Query(default=None, alias="status"),
    ssh_key_installed: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> ServerListResponse:
    stmt = select(TargetServer)
    count_stmt = select(func.count()).select_from(TargetServer)

    if q and q.strip():
        term = f"%{q.strip().lower()}%"
        filt = or_(
            func.lower(TargetServer.hostname).like(term),
            func.lower(TargetServer.ip).like(term),
            func.lower(TargetServer.tags).like(term),
        )
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(filt)

    if status_filter is not None:
        stmt = stmt.where(TargetServer.status == status_filter)
        count_stmt = count_stmt.where(TargetServer.status == status_filter)

    if ssh_key_installed is not None:
        stmt = stmt.where(TargetServer.ssh_key_installed == ssh_key_installed)
        count_stmt = count_stmt.where(TargetServer.ssh_key_installed == ssh_key_installed)

    total = session.exec(count_stmt).one()
    rows = session.exec(
        stmt.order_by(col(TargetServer.hostname)).offset((page - 1) * page_size).limit(page_size)
    ).all()

    items = [
        _public(
            session,
            server,
            session.get(Credential, server.credentials_id) if server.credentials_id else None,
        )
        for server in rows
    ]
    return ServerListResponse(items=items, total=total, page=page, page_size=page_size)


class HostEnsureIn(BaseModel):
    hostname: str = Field(min_length=1, max_length=255)
    ip: str = Field(min_length=3, max_length=64)
    port: int = Field(default=22, ge=1, le=65535)
    description: str = Field(default="", max_length=512)
    skip_connection_test: bool = True


@router.post("/ensure-host", response_model=ServerPublic)
def ensure_host_from_ainew(
    body: HostEnsureIn,
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> ServerPublic:
    """Upsert TargetServer by IP for ainew Level 1 mapping (no inventoy CRUD UI)."""
    hostname = body.hostname.strip()
    ip = body.ip.strip()
    existing = session.exec(select(TargetServer).where(TargetServer.ip == ip)).first()
    if existing is None:
        existing = session.exec(
            select(TargetServer).where(func.lower(TargetServer.hostname) == hostname.lower())
        ).first()
    username = get_automation_username(session)
    password = get_automation_password(session) or "ainew-pending"
    if existing is not None:
        existing.hostname = hostname
        existing.port = body.port
        if body.description:
            existing.description = body.description[:512]
        existing.updated_at = datetime.now(UTC)
        # Refresh automation creds so Level 1 Settings password changes apply
        cred = session.get(Credential, existing.credentials_id) if existing.credentials_id else None
        try:
            crypto = CredentialManager()
            if cred is None:
                cred = Credential(
                    label=f"{hostname}-ainew",
                    ssh_username=username,
                    encrypted_ssh_password=crypto.encrypt(password),
                )
                session.add(cred)
                session.commit()
                session.refresh(cred)
                existing.credentials_id = cred.id
            else:
                cred.ssh_username = username
                if password and password != "ainew-pending":
                    cred.encrypted_ssh_password = crypto.encrypt(password)
                session.add(cred)
        except CredentialCryptoError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        session.add(existing)
        session.commit()
        session.refresh(existing)
        cred = session.get(Credential, existing.credentials_id) if existing.credentials_id else None
        return _public(session, existing, cred)

    try:
        crypto = CredentialManager()
        cred = Credential(
            label=f"{hostname}-ainew",
            ssh_username=username,
            encrypted_ssh_password=crypto.encrypt(password),
        )
    except CredentialCryptoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    session.add(cred)
    session.commit()
    session.refresh(cred)
    now = datetime.now(UTC)
    server = TargetServer(
        hostname=hostname,
        ip=ip,
        port=body.port,
        status=ServerStatus.unknown,
        tags="ainew-level1",
        description=(body.description or f"ainew-map")[:512],
        credentials_id=cred.id,
        created_at=now,
        updated_at=now,
    )
    if not body.skip_connection_test and password != "ainew-pending":
        _bootstrap_connection(
            session, server, host=ip, port=body.port, username=username, password=password
        )
    session.add(server)
    session.commit()
    session.refresh(server)
    invalidate_server_index()
    return _public(session, server, cred)


class HostEnsureBulkIn(BaseModel):
    hosts: list[HostEnsureIn] = Field(default_factory=list, max_length=5000)


class HostEnsureBulkItemOut(BaseModel):
    hostname: str
    ip: str
    dropt_server_id: int | None = None
    created: bool = False
    error: str | None = None


class HostEnsureBulkOut(BaseModel):
    total: int
    ensured: int
    created: int
    errors: list[str] = Field(default_factory=list)
    items: list[HostEnsureBulkItemOut] = Field(default_factory=list)


@router.post("/ensure-hosts-bulk", response_model=HostEnsureBulkOut)
def ensure_hosts_bulk_from_ainew(
    body: HostEnsureBulkIn,
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> HostEnsureBulkOut:
    """Batch upsert TargetServer by IP for ainew Level 1 sync-all."""
    username = get_automation_username(session)
    password = get_automation_password(session) or "ainew-pending"
    crypto = CredentialManager()

    ensured = created = 0
    errors: list[str] = []
    items_out: list[HostEnsureBulkItemOut] = []

    # Prefetch existing by IP for fewer round-trips
    ips = [h.ip.strip() for h in body.hosts if h.ip.strip()]
    existing_by_ip: dict[str, TargetServer] = {}
    if ips:
        rows = session.exec(select(TargetServer).where(col(TargetServer.ip).in_(ips))).all()
        for row in rows:
            if row.ip:
                existing_by_ip[row.ip.strip()] = row

    for host in body.hosts:
        hostname = host.hostname.strip()
        ip = host.ip.strip()
        if not hostname or not ip:
            errors.append(f"{hostname or '?'}: hostname/ip eksik")
            items_out.append(HostEnsureBulkItemOut(hostname=hostname or "", ip=ip or "", error="hostname/ip eksik"))
            continue
        try:
            existing = existing_by_ip.get(ip)
            if existing is None:
                existing = session.exec(
                    select(TargetServer).where(func.lower(TargetServer.hostname) == hostname.lower())
                ).first()
            was_create = existing is None
            if existing is not None:
                existing.hostname = hostname
                existing.port = host.port
                if host.description:
                    existing.description = host.description[:512]
                existing.updated_at = datetime.now(UTC)
                cred = session.get(Credential, existing.credentials_id) if existing.credentials_id else None
                if cred is None:
                    cred = Credential(
                        label=f"{hostname}-ainew",
                        ssh_username=username,
                        encrypted_ssh_password=crypto.encrypt(password),
                    )
                    session.add(cred)
                    session.flush()
                    existing.credentials_id = cred.id
                else:
                    cred.ssh_username = username
                    if password and password != "ainew-pending":
                        cred.encrypted_ssh_password = crypto.encrypt(password)
                    session.add(cred)
                session.add(existing)
                session.flush()
                existing_by_ip[ip] = existing
                dropt_id = int(existing.id)  # type: ignore[arg-type]
            else:
                cred = Credential(
                    label=f"{hostname}-ainew",
                    ssh_username=username,
                    encrypted_ssh_password=crypto.encrypt(password),
                )
                session.add(cred)
                session.flush()
                now = datetime.now(UTC)
                server = TargetServer(
                    hostname=hostname,
                    ip=ip,
                    port=host.port,
                    status=ServerStatus.unknown,
                    tags="ainew-level1",
                    description=(host.description or "ainew-map")[:512],
                    credentials_id=cred.id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(server)
                session.flush()
                existing_by_ip[ip] = server
                dropt_id = int(server.id)  # type: ignore[arg-type]
                created += 1
            ensured += 1
            items_out.append(
                HostEnsureBulkItemOut(
                    hostname=hostname,
                    ip=ip,
                    dropt_server_id=dropt_id,
                    created=was_create,
                )
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"{hostname}: {exc}"
            errors.append(msg)
            items_out.append(HostEnsureBulkItemOut(hostname=hostname, ip=ip, error=str(exc)))

    session.commit()
    invalidate_server_index()
    return HostEnsureBulkOut(
        total=len(body.hosts),
        ensured=ensured,
        created=created,
        errors=errors[:50],
        items=items_out,
    )


@router.get("/{server_id}", response_model=ServerPublic)
def get_server(
    server_id: int,
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> ServerPublic:
    server = _get_server_or_404(session, server_id)
    cred = session.get(Credential, server.credentials_id) if server.credentials_id else None
    return _public(session, server, cred)


@router.get("/{server_id}/facts")
def get_server_facts(
    server_id: int,
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    server = _get_server_or_404(session, server_id)
    try:
        from app.services.machine_type import (
            apply_physical_override,
            effective_machine_type,
            hostname_has_physical_override,
        )
        from app.services.server_facts import collect_server_facts

        facts = collect_server_facts(session, server)
        # Envanter kilidi: override hostlarda physical göster / kaydet
        apply_physical_override(server)
        session.add(server)
        session.commit()
        facts["machine_type"] = effective_machine_type(server)
        facts["machine_type_override"] = hostname_has_physical_override(server.hostname or "")
        return facts
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("", response_model=ServerPublic, status_code=status.HTTP_201_CREATED)
def create_server(
    body: ServerCreate,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> ServerPublic:
    username = get_automation_username(session)
    try:
        crypto = CredentialManager()
        cred = Credential(
            label=f"{body.hostname}-cred",
            ssh_username=username,
            encrypted_ssh_password=crypto.encrypt(body.password),
        )
    except CredentialCryptoError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    session.add(cred)
    session.commit()
    session.refresh(cred)

    now = datetime.now(UTC)
    server = TargetServer(
        hostname=body.hostname,
        ip=body.ip,
        port=body.port,
        status=ServerStatus.unknown,
        tags=body.tags,
        description=body.description,
        credentials_id=cred.id,
        created_at=now,
        updated_at=now,
    )
    connection_ok = _bootstrap_connection(
        session,
        server,
        host=body.ip,
        port=body.port,
        username=username,
        password=body.password,
    )
    session.add(server)
    session.commit()
    session.refresh(server)
    invalidate_server_index()
    return _public(session, server, cred, connection_ok=connection_ok)


@router.post("/import", response_model=ServerImportResponse)
async def import_servers(
    file: UploadFile = File(...),
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> ServerImportResponse:
    password = get_automation_password(session)
    if not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Önce Ayarlar’da otomasyon kullanıcı şifresini kaydedin",
        )
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dosya boş")
    try:
        rows = parse_inventory_file(file.filename or "inventory.csv", raw)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    results: list[ServerImportRowResult] = []
    created = ready = unreachable = skipped = 0
    for row in rows:
        item = _import_one_row(session, hostname=row["hostname"], ip=row["ip"], password=password)
        results.append(item)
        if item.status == "skipped":
            skipped += 1
        elif item.status == "ready":
            created += 1
            ready += 1
        elif item.status == "unreachable":
            created += 1
            unreachable += 1
        else:
            # error — not persisted or failed mid-way
            if item.server_id is not None:
                created += 1
                unreachable += 1
            else:
                skipped += 1

    if created:
        invalidate_server_index()
    return ServerImportResponse(
        ok=True,
        total_rows=len(rows),
        created=created,
        ready=ready,
        unreachable=unreachable,
        skipped=skipped,
        items=results,
    )


@router.post("/import/parse", response_model=ServerImportParseResponse)
async def import_servers_parse(
    file: UploadFile = File(...),
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> ServerImportParseResponse:
    if not get_automation_password(session):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Önce Ayarlar’da otomasyon kullanıcı şifresini kaydedin",
        )
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dosya boş")
    try:
        rows = parse_inventory_file(file.filename or "inventory.csv", raw)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ServerImportParseResponse(rows=rows, total=len(rows))


@router.post("/import/row", response_model=ServerImportRowResult)
def import_servers_row(
    body: ServerImportRowRequest,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> ServerImportRowResult:
    password = get_automation_password(session)
    if not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Önce Ayarlar’da otomasyon kullanıcı şifresini kaydedin",
        )
    return _import_one_row(session, hostname=body.hostname, ip=body.ip, password=password)


def _import_one_row(
    session: Session,
    *,
    hostname: str,
    ip: str,
    password: str,
) -> ServerImportRowResult:
    username = get_automation_username(session)
    try:
        crypto = CredentialManager()
    except CredentialCryptoError as exc:
        return ServerImportRowResult(
            hostname=hostname,
            ip=ip,
            status="error",
            message=str(exc),
        )

    existing = session.exec(
        select(TargetServer).where(
            or_(
                func.lower(TargetServer.hostname) == hostname.lower(),
                TargetServer.ip == ip,
            )
        )
    ).first()
    if existing is not None:
        return ServerImportRowResult(
            hostname=hostname,
            ip=ip,
            status="skipped",
            message=f"Zaten kayıtlı (id={existing.id})",
            server_id=existing.id,
        )

    try:
        cred = Credential(
            label=f"{hostname}-cred",
            ssh_username=username,
            encrypted_ssh_password=crypto.encrypt(password),
        )
        session.add(cred)
        session.commit()
        session.refresh(cred)

        now = datetime.now(UTC)
        server = TargetServer(
            hostname=hostname,
            ip=ip,
            port=22,
            status=ServerStatus.unknown,
            tags="",
            description="excel-import",
            credentials_id=cred.id,
            created_at=now,
            updated_at=now,
        )
        try:
            connection_ok = _bootstrap_connection(
                session,
                server,
                host=ip,
                port=22,
                username=username,
                password=password,
            )
        except Exception as exc:  # noqa: BLE001 — keep batch going
            server.last_connection_message = str(exc)[:1024]
            server.status = ServerStatus.unreachable
            connection_ok = False

        session.add(server)
        session.commit()
        session.refresh(server)
        return ServerImportRowResult(
            hostname=hostname,
            ip=ip,
            status="ready" if connection_ok else "unreachable",
            message=server.last_connection_message or "",
            server_id=server.id,
        )
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return ServerImportRowResult(
            hostname=hostname,
            ip=ip,
            status="error",
            message=str(exc)[:1024],
        )


@router.patch("/{server_id}", response_model=ServerPublic)
def update_server(
    server_id: int,
    body: ServerUpdate,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> ServerPublic:
    server = _get_server_or_404(session, server_id)
    username = get_automation_username(session)
    cred = session.get(Credential, server.credentials_id) if server.credentials_id else None
    if cred is None:
        cred = Credential(label=f"{server.hostname}-cred", ssh_username=username)
        session.add(cred)
        session.commit()
        session.refresh(cred)
        server.credentials_id = cred.id

    try:
        crypto = CredentialManager()
    except CredentialCryptoError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    data = body.model_dump(exclude_unset=True)
    for field in ("hostname", "ip", "port", "tags", "description"):
        if field in data and data[field] is not None:
            setattr(server, field, data[field])
    if "status" in data and data["status"] is not None and not body.test_connection:
        server.status = data["status"]

    # Always keep inventory username aligned with Admin automation setting
    cred.ssh_username = username

    plain_password: str | None = None
    if body.password is not None:
        cred.encrypted_ssh_password = crypto.encrypt(body.password)
        plain_password = body.password

    if not cred.encrypted_ssh_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sunucu için SSH şifresi gerekli",
        )

    connection_ok: bool | None = None
    if body.test_connection:
        if plain_password is None:
            try:
                plain_password = crypto.decrypt(cred.encrypted_ssh_password)
            except CredentialCryptoError as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=str(exc),
                ) from exc
        # New password supplied → reinstall/verify path; else key-first test
        connection_ok = _test_connection(
            session,
            server,
            host=server.ip,
            port=server.port,
            username=username,
            password=plain_password,
            force_reinstall=body.password is not None,
        )

    now = datetime.now(UTC)
    cred.updated_at = now
    server.updated_at = now
    session.add(cred)
    session.add(server)
    session.commit()
    session.refresh(server)
    session.refresh(cred)
    invalidate_server_index()
    return _public(session, server, cred, connection_ok=connection_ok)


@router.post("/{server_id}/test-connection", response_model=ServerPublic)
def test_connection(
    server_id: int,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> ServerPublic:
    server = _get_server_or_404(session, server_id)
    username = get_automation_username(session)
    cred = session.get(Credential, server.credentials_id) if server.credentials_id else None
    if cred is None or not cred.encrypted_ssh_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Kayıtlı şifre yok")
    try:
        password = CredentialManager().decrypt(cred.encrypted_ssh_password)
    except CredentialCryptoError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    cred.ssh_username = username
    ok = _test_connection(
        session,
        server,
        host=server.ip,
        port=server.port,
        username=username,
        password=password,
    )
    server.updated_at = datetime.now(UTC)
    session.add(cred)
    session.add(server)
    session.commit()
    session.refresh(server)
    return _public(session, server, cred, connection_ok=ok)


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(
    server_id: int,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> None:
    server = _get_server_or_404(session, server_id)
    cred_id = server.credentials_id
    session.delete(server)
    session.commit()
    if cred_id:
        cred = session.get(Credential, cred_id)
        if cred is not None:
            session.delete(cred)
            session.commit()
    invalidate_server_index()
