from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.deps import require_admin
from app.core.database import get_session
from app.models.package_repos import PkgLocalRepo, PkgSubscription
from app.models.user import User
from app.services import package_repo_store as store

router = APIRouter(prefix="/settings/package-repos", tags=["package-repos"])


class SubscriptionIn(BaseModel):
    label: str = ""
    os_value: str = Field(description="örn. rhel:8")
    org: str = ""
    activation_key: Optional[str] = None
    enabled: bool = True


class LocalRepoIn(BaseModel):
    keyword: str = Field(min_length=1, max_length=64)
    label: str = ""
    os_value: str = Field(description="örn. rhel:8")
    source_type: str = Field(
        default="nfs",
        description="nfs | portal_files | subscription",
    )
    nfs_path: str = ""
    mount_point: str = ""
    repo_id: str = ""
    baseurl_suffix: str = ""
    portal_path: str = ""
    file_glob: str = "*.rpm"
    needs_data_mount: bool = False
    post_commands: str = ""
    enabled: bool = True


def _parse_os_value(value: str) -> tuple[str, str]:
    raw = (value or "").strip().lower()
    if ":" not in raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "os_value 'os_id:major' olmalı (örn. rhel:8)")
    os_id, major = raw.split(":", 1)
    os_id, major = os_id.strip(), major.strip()
    if not os_id or not major:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "os_value geçersiz")
    return os_id, major


def _normalize_source(body: LocalRepoIn) -> str:
    st = (body.source_type or "nfs").strip().lower()
    if st not in {"nfs", "portal_files", "subscription"}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "source_type nfs, portal_files veya subscription olmalı",
        )
    return st


def _apply_repo_fields(row: PkgLocalRepo, body: LocalRepoIn, os_id: str, major: str) -> None:
    st = _normalize_source(body)
    kw = body.keyword.strip().lower()
    row.keyword = kw
    row.label = (body.label or kw).strip()
    row.os_id = os_id
    row.os_major = major
    row.source_type = st
    row.post_commands = body.post_commands or ""
    row.enabled = body.enabled
    # Data mount (hedef dizin) NFS ve subscription reçetelerinde kullanılabilir
    row.needs_data_mount = bool(body.needs_data_mount) if st in {"nfs", "subscription"} else False

    if st == "nfs":
        if not (body.nfs_path or "").strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "NFS path zorunlu")
        if not (body.mount_point or "").strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mount point zorunlu")
        row.nfs_path = body.nfs_path.strip()
        row.mount_point = body.mount_point.strip()
        row.repo_id = (body.repo_id or f"dropt-{kw}").strip()
        row.baseurl_suffix = body.baseurl_suffix.strip()
        row.portal_path = ""
        row.file_glob = "*.rpm"
    elif st == "portal_files":
        try:
            path = store.validate_portal_path(body.portal_path)
            store.resolve_portal_rpm_files(path, body.file_glob or "*.rpm")
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        row.portal_path = path
        row.file_glob = (body.file_glob or "*.rpm").strip() or "*.rpm"
        row.nfs_path = ""
        row.mount_point = ""
        row.repo_id = (body.repo_id or f"dropt-{kw}").strip()
        row.baseurl_suffix = ""
    else:
        # subscription: paketler Satellite/dnf'den; path + post_commands recipe'de
        if not (body.post_commands or "").strip():
            # post veya en azından bilgilendirici not — zorunlu değil ama boş recipe anlamsız
            # paketler UI'dan da gelebilir; uyarı yok, boş post OK
            pass
        row.nfs_path = ""
        row.mount_point = ""
        row.portal_path = ""
        row.file_glob = "*.rpm"
        row.repo_id = (body.repo_id or f"dropt-{kw}").strip()
        row.baseurl_suffix = ""


@router.get("/os-options")
def os_options(
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    return store.inventory_os_options(session)


@router.get("/overview")
def overview(
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return {
        "os_options": store.inventory_os_options(session),
        "subscriptions": [store.subscription_public(s) for s in store.list_subscriptions(session)],
        "local_repos": [store.local_repo_public(r) for r in store.list_local_repos(session)],
        "keywords": store.list_keywords(session),
        "portal_rpm_root": store.PORTAL_RPM_ROOT,
    }


@router.get("/keywords")
def keywords(
    _user: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    return store.list_keywords(session)


@router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
def create_subscription(
    body: SubscriptionIn,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    os_id, major = _parse_os_value(body.os_value)
    existing = store.find_subscription_for_os(session, os_id, major)
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Bu OS için subscription zaten var: {os_id}:{major}")
    row = PkgSubscription(
        label=(body.label or f"{os_id}-{major}").strip(),
        os_id=os_id,
        os_major=major,
        org=body.org.strip(),
        enabled=body.enabled,
    )
    if body.activation_key and body.activation_key.strip():
        row.activation_key_enc = store.encrypt_activation_key(body.activation_key)
    session.add(row)
    session.commit()
    session.refresh(row)
    return store.subscription_public(row)


@router.put("/subscriptions/{sub_id}")
def update_subscription(
    sub_id: int,
    body: SubscriptionIn,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    row = session.get(PkgSubscription, sub_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription yok")
    os_id, major = _parse_os_value(body.os_value)
    row.label = (body.label or f"{os_id}-{major}").strip()
    row.os_id = os_id
    row.os_major = major
    row.org = body.org.strip()
    row.enabled = body.enabled
    if body.activation_key is not None and body.activation_key.strip():
        row.activation_key_enc = store.encrypt_activation_key(body.activation_key)
    session.add(row)
    session.commit()
    session.refresh(row)
    return store.subscription_public(row)


@router.delete("/subscriptions/{sub_id}")
def delete_subscription(
    sub_id: int,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Response:
    row = session.get(PkgSubscription, sub_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription yok")
    session.delete(row)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/local-repos", status_code=status.HTTP_201_CREATED)
def create_local_repo(
    body: LocalRepoIn,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    os_id, major = _parse_os_value(body.os_value)
    kw = body.keyword.strip().lower()
    if store.find_local_repo(session, kw, os_id, major):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Bu OS için keyword zaten var: {kw} @ {os_id}:{major}"
        )
    row = PkgLocalRepo()
    _apply_repo_fields(row, body, os_id, major)
    session.add(row)
    session.commit()
    session.refresh(row)
    return store.local_repo_public(row)


@router.put("/local-repos/{repo_id}")
def update_local_repo(
    repo_id: int,
    body: LocalRepoIn,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    row = session.get(PkgLocalRepo, repo_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Local repo yok")
    os_id, major = _parse_os_value(body.os_value)
    _apply_repo_fields(row, body, os_id, major)
    session.add(row)
    session.commit()
    session.refresh(row)
    return store.local_repo_public(row)


@router.delete("/local-repos/{repo_id}")
def delete_local_repo(
    repo_id: int,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Response:
    row = session.get(PkgLocalRepo, repo_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Local repo yok")
    session.delete(row)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("")
def legacy_list(
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return overview(_admin, session)
