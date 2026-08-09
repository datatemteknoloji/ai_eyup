from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.settings import (
    APP_NAME_KEY,
    AUTOMATION_PASSWORD_KEY,
    AUTOMATION_USER_KIND_KEY,
    AUTOMATION_USERNAME_KEY,
    SMTP_HOST_KEY,
    SMTP_TEST_MAIL_KEY,
    AppSetting,
)
from app.models.user import AuthSource, User, UserRole
from app.services.credential_manager import CredentialCryptoError, CredentialManager

DEFAULT_AUTOMATION_USERNAME = "root"
DEFAULT_AUTOMATION_USER_KIND = "root"


def ensure_admin_user(session: Session) -> None:
    """Create bootstrap Admin from env; optionally reset password when flagged."""
    settings = get_settings()
    username = settings.admin_username.strip()
    existing = session.exec(select(User).where(User.username == username)).first()

    if existing is None:
        admin = User(
            id=1,
            username=username,
            password_hash=hash_password(settings.admin_password),
            role=UserRole.admin,
            auth_source=AuthSource.local,
            is_active=True,
        )
        session.add(admin)
        session.commit()
        return

    if settings.reset_admin_password:
        existing.password_hash = hash_password(settings.admin_password)
        existing.is_active = True
        session.add(existing)
        session.commit()


def ensure_default_settings(session: Session) -> None:
    settings = get_settings()
    if session.get(AppSetting, APP_NAME_KEY) is None:
        session.add(AppSetting(key=APP_NAME_KEY, value=settings.default_app_name))

    from app.services.assistant_settings import ensure_assistant_defaults

    ensure_assistant_defaults(session)

    auto_row = session.get(AppSetting, AUTOMATION_USERNAME_KEY)
    if auto_row is None:
        session.add(AppSetting(key=AUTOMATION_USERNAME_KEY, value=DEFAULT_AUTOMATION_USERNAME))
    elif auto_row.value.strip() in {"dtt-automation", "svc-opt"}:
        # Align with current ops choice: default automation user is root
        auto_row.value = DEFAULT_AUTOMATION_USERNAME
        session.add(auto_row)

    kind_row = session.get(AppSetting, AUTOMATION_USER_KIND_KEY)
    if kind_row is None:
        session.add(AppSetting(key=AUTOMATION_USER_KIND_KEY, value=DEFAULT_AUTOMATION_USER_KIND))
    session.commit()


def get_app_name(session: Session) -> str:
    row = session.get(AppSetting, APP_NAME_KEY)
    if row and row.value.strip():
        return row.value.strip()
    return get_settings().default_app_name


def set_app_name(session: Session, name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Uygulama adı boş olamaz")
    if len(cleaned) > 120:
        raise ValueError("Uygulama adı çok uzun")
    row = session.get(AppSetting, APP_NAME_KEY)
    if row is None:
        row = AppSetting(key=APP_NAME_KEY, value=cleaned)
    else:
        row.value = cleaned
    session.add(row)
    session.commit()
    session.refresh(row)
    return row.value


def get_automation_username(session: Session) -> str:
    row = session.get(AppSetting, AUTOMATION_USERNAME_KEY)
    if row and row.value.strip():
        return row.value.strip()
    return DEFAULT_AUTOMATION_USERNAME


def set_automation_username(session: Session, username: str) -> str:
    cleaned = username.strip()
    if not cleaned:
        raise ValueError("Otomasyon kullanıcı adı boş olamaz")
    if len(cleaned) > 128:
        raise ValueError("Otomasyon kullanıcı adı çok uzun")
    row = session.get(AppSetting, AUTOMATION_USERNAME_KEY)
    if row is None:
        row = AppSetting(key=AUTOMATION_USERNAME_KEY, value=cleaned)
    else:
        row.value = cleaned
    session.add(row)
    # root kullanıcı → tip otomatik root
    if cleaned == "root":
        kind_row = session.get(AppSetting, AUTOMATION_USER_KIND_KEY)
        if kind_row is None:
            kind_row = AppSetting(key=AUTOMATION_USER_KIND_KEY, value="root")
        else:
            kind_row.value = "root"
        session.add(kind_row)
    session.commit()
    session.refresh(row)
    return row.value


def automation_password_is_set(session: Session) -> bool:
    row = session.get(AppSetting, AUTOMATION_PASSWORD_KEY)
    return bool(row and row.value.strip())


def get_automation_password(session: Session) -> str | None:
    row = session.get(AppSetting, AUTOMATION_PASSWORD_KEY)
    if not row or not row.value.strip():
        return None
    try:
        return CredentialManager().decrypt(row.value.strip())
    except CredentialCryptoError:
        return None


def set_automation_password(session: Session, password: str) -> None:
    cleaned = password.strip()
    if not cleaned:
        raise ValueError("Otomasyon şifresi boş olamaz")
    if len(cleaned) > 512:
        raise ValueError("Otomasyon şifresi çok uzun")
    try:
        encrypted = CredentialManager().encrypt(cleaned)
    except CredentialCryptoError as exc:
        raise ValueError(str(exc)) from exc
    row = session.get(AppSetting, AUTOMATION_PASSWORD_KEY)
    if row is None:
        row = AppSetting(key=AUTOMATION_PASSWORD_KEY, value=encrypted)
    else:
        row.value = encrypted
    session.add(row)
    session.commit()


def get_smtp_host(session: Session) -> str:
    row = session.get(AppSetting, SMTP_HOST_KEY)
    return (row.value or "").strip() if row else ""


def set_smtp_host(session: Session, host: str) -> str:
    cleaned = (host or "").strip()
    if len(cleaned) > 255:
        raise ValueError("SMTP host çok uzun")
    if cleaned and any(c.isspace() for c in cleaned):
        raise ValueError("SMTP host boşluk içeremez")
    row = session.get(AppSetting, SMTP_HOST_KEY)
    if row is None:
        row = AppSetting(key=SMTP_HOST_KEY, value=cleaned)
    else:
        row.value = cleaned
    session.add(row)
    session.commit()
    session.refresh(row)
    return row.value


def get_smtp_test_mail(session: Session) -> str:
    row = session.get(AppSetting, SMTP_TEST_MAIL_KEY)
    return (row.value or "").strip() if row else ""


def set_smtp_test_mail(session: Session, address: str) -> str:
    cleaned = (address or "").strip()
    if len(cleaned) > 320:
        raise ValueError("Test mail adresi çok uzun")
    if cleaned and ("@" not in cleaned or " " in cleaned):
        raise ValueError("Geçersiz test mail adresi")
    row = session.get(AppSetting, SMTP_TEST_MAIL_KEY)
    if row is None:
        row = AppSetting(key=SMTP_TEST_MAIL_KEY, value=cleaned)
    else:
        row.value = cleaned
    session.add(row)
    session.commit()
    session.refresh(row)
    return row.value
