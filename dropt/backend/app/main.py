from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session

from app.api import (
    admin_system,
    assistant,
    audit,
    auth,
    bridge,
    centrify,
    health,
    hostname_api,
    identity,
    jobs,
    local_users,
    ops,
    package_repos,
    portal_users,
    security,
    servers,
    settings as settings_api,
    terminal,
)
from app.core.config import get_settings
from app.core.database import engine, init_db
from app.models import centrify as _centrify_models  # noqa: F401
from app.models import identity as _identity_models  # noqa: F401
from app.models import job as _job_models  # noqa: F401 — register tables
from app.models import package_repos as _package_repos_models  # noqa: F401
from app.models import security as _security_models  # noqa: F401
from app.models import server as _server_models  # noqa: F401
from app.models import assistant_feedback as _assistant_feedback_models  # noqa: F401
from app.models import assistant_history as _assistant_history_models  # noqa: F401
from app.models import settings as _settings_models  # noqa: F401
from app.models import user as _user_models  # noqa: F401
from app.services.bootstrap import ensure_admin_user, ensure_default_settings
from app.services.identity_store import get_or_create_identity
from app.services.security_policy import ensure_security_defaults
from app.services.ssh_probe import ensure_portal_keypair
from app.services.tls_certs import ensure_certs


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    ensure_portal_keypair()
    try:
        ensure_certs()
    except Exception:
        pass
    with Session(engine) as session:
        ensure_admin_user(session)
        ensure_default_settings(session)
        ensure_security_defaults(session)
        get_or_create_identity(session)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.default_app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api")
    app.include_router(bridge.router, prefix="/api")
    app.include_router(settings_api.router, prefix="/api")
    app.include_router(assistant.router, prefix="/api")
    app.include_router(package_repos.router, prefix="/api")
    app.include_router(centrify.router, prefix="/api")
    app.include_router(portal_users.router, prefix="/api")
    app.include_router(identity.router, prefix="/api")
    app.include_router(security.router, prefix="/api")
    app.include_router(servers.router, prefix="/api")
    app.include_router(local_users.router, prefix="/api")
    app.include_router(hostname_api.router, prefix="/api")
    app.include_router(ops.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(audit.router, prefix="/api")
    app.include_router(admin_system.router, prefix="/api")
    app.include_router(terminal.router, prefix="/api")
    return app


app = create_app()
