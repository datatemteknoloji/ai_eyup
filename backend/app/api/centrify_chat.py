"""Centrify AI Asistanı — Sayfaya özel RAG destekli chat endpoint.

Centrify zone yönetimi hakkında sorulara cevap verir. READ-ONLY tool'lar
ile mevcut zone/role/command verisini sorgular. Yazma yapmaz.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import require_module
from app.core.config import settings, get_active_model, remote_llm_enabled
from app.core.database import get_db
from app.models.chat_session import ChatSession, ChatMessage
from app.models.user import User
from app.services.chat_session_scope import (
    create_owned_session,
    get_owned_session,
    require_owned_session,
    require_user_id,
    sessions_q,
)

logger = logging.getLogger(__name__)

CATEGORY = "centrify"
router = APIRouter()

# ── Sistem prompt'u ───────────────────────────────────────────

SYSTEM_PROMPT = """Sen ainew platformunun Centrify / Delinea Server Suite uzmanısın.
Kullanıcının zone, rol, komut (right), role assignment, computer, computer role ve UNIX profili
hakkındaki sorularına cevap veriyorsun.

## Kurallar
- Yalnızca Türkçe yanıt ver (kullanıcı İngilizce sorarsa bile)
- Yalnızca okuma yapabilirsin — yazma için kullanıcıyı sağ tık menüsü / Rol Ata diyaloglarına yönlendir
- Context ve özellikle <<<CENTRIFY_TOOL_DATA>>> bloklarındaki JSON'u olduğu gibi kullan; uydurma
- Boş liste (0 rol, 0 sunucu, 0 komut) geçerli cevaptır — "veri yok" diye kaçma; "0" de
- Emin olmadığın bilgileri uydurma; "Bu bilgiye mevcut veride ulaşamadım" de
- Bu üründeki assignment kayıtlarına göre cevap ver: parent zone ataması child zone sunucusuna
  otomatik miras sayılmaz — yalnızca kayıtlı zone/computer scope atamalarını kullan
- limitations alanında nested_groups=unsupported görürsen iç içe grup çözümü olmadığını söyle
- Benzer rol/komut sorularında score ve shared_commands alanlarını kullan; uydurma benzerlik yapma
- Best practice önerilerinde bulun (en az yetki prensibi, role ayrımı)

## Yanıt biçimi (zorunlu)
- HTML YASAK: `<ul>`, `<li>`, `<br>`, `<table>`, `<p>`, `<div>` yazma. Yalnızca Markdown.
- "Nasıl yapılır / nasıl veririm" sorularında TABLO KULLANMA. Numaralı adımlar:
  1. **Kısa başlık** — tek cümle. UI yolu (ör. Computers → sağ tık → Rol Ata).
- Tablo yalnızca düz karşılaştırma için: 2–4 sütun, her hücre tek satır, hücre içi liste yok.
- Mevcut zone/rol/komutu öner; `sudo` right'ı veya `*` glob ile tüm komutları açmayı önerme.
- Kısa tut; süsleme ve tekrar yok.

## Delinea/Centrify Bilgi Tabanı
- Zone: Sunucu gruplarını organize eden AD container. Hierarchical (alt zone destekler) ve Classic tip.
- Role: Yetki kümesi. login bayrakları: password_login_allowed, sso_login_allowed, require_mfa.
- Command/Right: dzdo hakkı. match_type: exact|glob|regex. auth_type: none|password|mfa. run_as_user.
- Role Assignment: kullanıcı/grup → role. scope_type=zone (tüm zone) veya computer (tek sunucu; host adı verilir).
- Computer: zone'a join olmuş Linux/Windows sunucu (name, fqdn, os, agent_version).
- dzdo: AD tabanlı sudo benzeri; adclient/centrifydc ajanı uygular.
- ZPA / ADEdit: AD zone yönetimi araçları.

## Sık Sorulan Sorular Rehberi
- "dzdo ile sudo farkı nedir?" → dzdo AD tabanlı, merkezi; sudo yerel dosya
- "Role nasıl klonlanır?" → Roller'de sağ tık Kopyala; işlem doğrudan uygulanır
- "Komut beyaz listesi nedir?" → Yalnızca izinli path'lerden komut tanımlanabilir
"""


# ── Pydantic şemaları ─────────────────────────────────────────


class CentrifyChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: Optional[int] = None
    zone_id: Optional[int] = None


class CentrifyChatSessionOut(BaseModel):
    id: int
    title: str
    created_at: str
    message_count: int


# ── Context toplama (READ-ONLY) ──────────────────────────────


def _role_login_flags(role) -> str:
    """password_login / sso / mfa bayraklarını kısa metin olarak döndür."""
    return (
        f"password_login={'evet' if role.password_login_allowed else 'hayır'}, "
        f"sso={'evet' if role.sso_login_allowed else 'hayır'}, "
        f"mfa={'evet' if role.require_mfa else 'hayır'}"
    )


def _gather_centrify_context(zone_id: Optional[int] = None) -> str:
    """Centrify DB'den zone/role/command/computer/assignment verisini topla.

    zone_id verilmezse tüm zone'lar; verilirse o zone'un tam detayı.
    """
    try:
        from app.services.centrify.database import get_centrify_thread_session
        from app.models.centrify_zone import (
            CentrifyZone, CentrifyRole, CentrifyCommand, CentrifyComputer,
            CentrifyRoleAssignment, CentrifyOperation,
        )
        db = get_centrify_thread_session()
        if db is None:
            return "Centrify DB erişilemiyor."

        try:
            parts: list[str] = []

            zones = db.query(CentrifyZone).filter_by(deleted_in_ad=False).all()
            if not zones:
                return "Centrify'da henüz veri yok."

            zone_map = {z.id: z for z in zones}
            computers = db.query(CentrifyComputer).filter_by(deleted_in_ad=False).all()
            computer_map = {c.id: c for c in computers}
            target_zone_ids = [zone_id] if zone_id else [z.id for z in zones]

            parts.append("## Zone Hiyerarşisi")
            for z in zones:
                parent = zone_map.get(z.parent_zone_id) if z.parent_zone_id else None
                parent_info = f" (üst: {parent.name})" if parent else ""
                parts.append(f"- **{z.name}** id={z.id} ({z.zone_type}){parent_info}")

            parts.append(
                "\n## Önemli: Bu üründeki atama modeli\n"
                "- Yalnızca kayıtlı Role Assignment satırları geçerlidir.\n"
                "- Parent zone ataması child zone sunucusuna otomatik miras sayılmaz.\n"
                "- computer scope atamada host adı/FQDN aşağıda belirtilir."
            )

            for zid in target_zone_ids:
                zone = zone_map.get(zid)
                if not zone:
                    continue

                parts.append(f"\n## Zone: {zone.name} (id={zid})")

                roles = db.query(CentrifyRole).filter_by(zone_id=zid, deleted_in_ad=False).all()
                parts.append(f"### Roller ({len(roles)})")
                if not roles:
                    parts.append("- (rol tanımı yok — 0)")
                for r in roles:
                    sys_tag = " [SİSTEM]" if r.is_system_role else ""
                    cmd_names: list[str] = []
                    if r.role_commands:
                        for rc in r.role_commands[:20]:
                            c = rc.command
                            if c and not c.deleted_in_ad:
                                cmd_names.append(f"`{c.name}`")
                    cmd_info = f" → komutlar: {', '.join(cmd_names)}" if cmd_names else " → komut yok"
                    parts.append(
                        f"- **{r.name}**{sys_tag} [{_role_login_flags(r)}]{cmd_info}"
                        f"{(' — ' + r.description) if r.description else ''}"
                    )

                cmds = db.query(CentrifyCommand).filter_by(zone_id=zid, deleted_in_ad=False).all()
                parts.append(f"### Komutlar ({len(cmds)})")
                if not cmds:
                    parts.append("- (komut yok — 0)")
                for c in cmds:
                    parts.append(
                        f"- `{c.name}`: `{c.command_path}` "
                        f"(match:{c.match_type}, runAs:{c.run_as_user or 'root'}, auth:{c.auth_type})"
                    )

                zone_computers = [c for c in computers if c.zone_id == zid]
                parts.append(f"### Computers ({len(zone_computers)})")
                if not zone_computers:
                    parts.append("- (sunucu yok — 0)")
                for c in zone_computers:
                    parts.append(
                        f"- **{c.name}** fqdn=`{c.fqdn or '—'}` os=`{c.os_type or '—'}` "
                        f"agent=`{c.agent_version or '—'}` id={c.id}"
                    )

                assignments = db.query(CentrifyRoleAssignment).filter_by(
                    zone_id=zid, deleted_in_ad=False,
                ).all()
                parts.append(f"### Atamalar ({len(assignments)})")
                if not assignments:
                    parts.append("- (atama yok — 0)")
                for a in assignments:
                    role = db.query(CentrifyRole).filter_by(id=a.role_id).first()
                    role_name = role.name if role else "?"
                    host = ""
                    if a.scope_type == "computer" and a.computer_id:
                        comp = computer_map.get(a.computer_id)
                        if comp:
                            host = f", host={comp.name} fqdn={comp.fqdn or '—'}"
                        else:
                            host = f", computer_id={a.computer_id}"
                    parts.append(
                        f"- {a.assignee_name} ({a.assignee_type}) → **{role_name}** "
                        f"(scope: {a.scope_type}{host})"
                    )

            pending = db.query(CentrifyOperation).filter(
                CentrifyOperation.status.in_(["pending_approval", "approved", "provisioning"])
            ).count()
            if pending > 0:
                parts.append(f"\n## Bekleyen / devam eden işlemler: {pending}")

            return "\n".join(parts)
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Centrify context toplama hatası: %s", exc)
        return "Centrify context toplanamadı."


# ── Tool fonksiyonları (READ-ONLY) ───────────────────────────


def _tool_search_roles(query: str) -> str:
    """Rol adı/açıklama ile arama — login bayrakları dahil."""
    try:
        from app.services.centrify.database import get_centrify_thread_session
        from app.models.centrify_zone import CentrifyRole, CentrifyZone
        db = get_centrify_thread_session()
        if db is None:
            return "DB erişilemiyor"
        try:
            roles = db.query(CentrifyRole).filter(
                CentrifyRole.deleted_in_ad == False,
                (CentrifyRole.name.ilike(f"%{query}%")) | (CentrifyRole.description.ilike(f"%{query}%"))
            ).limit(20).all()
            if not roles:
                return f"'{query}' ile eşleşen rol bulunamadı."
            lines = []
            for r in roles:
                z = db.query(CentrifyZone).filter_by(id=r.zone_id).first()
                zn = z.name if z else "?"
                cmds = []
                for rc in (r.role_commands or [])[:15]:
                    if rc.command and not rc.command.deleted_in_ad:
                        cmds.append(rc.command.name)
                sys_tag = " [SİSTEM]" if r.is_system_role else ""
                lines.append(
                    f"- {r.name}{sys_tag} (zone: {zn}) [{_role_login_flags(r)}] "
                    f"komutlar: {', '.join(cmds) if cmds else 'yok'}"
                )
            return "\n".join(lines)
        finally:
            db.close()
    except Exception as exc:
        return f"Arama hatası: {exc}"


def _tool_search_commands(query: str) -> str:
    """Komut adı/path ile arama."""
    try:
        from app.services.centrify.database import get_centrify_thread_session
        from app.models.centrify_zone import CentrifyCommand, CentrifyZone, CentrifyRole
        db = get_centrify_thread_session()
        if db is None:
            return "DB erişilemiyor"
        try:
            cmds = db.query(CentrifyCommand).filter(
                CentrifyCommand.deleted_in_ad == False,
                (CentrifyCommand.name.ilike(f"%{query}%")) | (CentrifyCommand.command_path.ilike(f"%{query}%"))
            ).limit(20).all()
            if not cmds:
                return f"'{query}' ile eşleşen komut bulunamadı."
            lines = []
            for c in cmds:
                z = db.query(CentrifyZone).filter_by(id=c.zone_id).first()
                zn = z.name if z else "?"
                role_names = []
                for rc in (c.role_commands or []):
                    if rc.role and not rc.role.deleted_in_ad:
                        role_names.append(rc.role.name)
                roles_info = f", roller: {', '.join(role_names)}" if role_names else ""
                lines.append(
                    f"- {c.name}: `{c.command_path}` (zone: {zn}, match:{c.match_type}, "
                    f"runAs:{c.run_as_user}, auth:{c.auth_type}{roles_info})"
                )
            return "\n".join(lines)
        finally:
            db.close()
    except Exception as exc:
        return f"Arama hatası: {exc}"


def _tool_search_assignments(query: str) -> str:
    """Kullanıcı/grup/host bazlı atama arama — computer host adı dahil."""
    try:
        from app.services.centrify.database import get_centrify_thread_session
        from app.models.centrify_zone import (
            CentrifyRoleAssignment, CentrifyRole, CentrifyZone, CentrifyComputer,
        )
        db = get_centrify_thread_session()
        if db is None:
            return "DB erişilemiyor"
        try:
            q = f"%{query}%"
            items = db.query(CentrifyRoleAssignment).filter(
                CentrifyRoleAssignment.deleted_in_ad == False,
                CentrifyRoleAssignment.assignee_name.ilike(q),
            ).limit(30).all()
            # Host adına göre de ara
            if not items:
                comps = db.query(CentrifyComputer).filter(
                    CentrifyComputer.deleted_in_ad == False,
                    (CentrifyComputer.name.ilike(q)) | (CentrifyComputer.fqdn.ilike(q)),
                ).all()
                cids = [c.id for c in comps]
                if cids:
                    items = db.query(CentrifyRoleAssignment).filter(
                        CentrifyRoleAssignment.deleted_in_ad == False,
                        CentrifyRoleAssignment.computer_id.in_(cids),
                    ).limit(30).all()
            if not items:
                return f"'{query}' ile eşleşen atama bulunamadı."
            lines = []
            for a in items:
                role = db.query(CentrifyRole).filter_by(id=a.role_id).first()
                zone = db.query(CentrifyZone).filter_by(id=a.zone_id).first()
                host = ""
                if a.computer_id:
                    comp = db.query(CentrifyComputer).filter_by(id=a.computer_id).first()
                    if comp:
                        host = f", host={comp.name} fqdn={comp.fqdn or '—'}"
                lines.append(
                    f"- {a.assignee_name} ({a.assignee_type}) → {role.name if role else '?'} "
                    f"@ {zone.name if zone else '?'} (scope: {a.scope_type}{host})"
                )
            return "\n".join(lines)
        finally:
            db.close()
    except Exception as exc:
        return f"Arama hatası: {exc}"


def _tool_search_computers(query: str) -> str:
    """Sunucu adı/FQDN/OS veya zone adı ile arama."""
    try:
        from app.services.centrify.database import get_centrify_thread_session
        from app.models.centrify_zone import CentrifyComputer, CentrifyZone
        db = get_centrify_thread_session()
        if db is None:
            return "DB erişilemiyor"
        try:
            q = (query or "").strip()
            comps = []
            if q:
                # Önce zone adına göre
                zones = db.query(CentrifyZone).filter(
                    CentrifyZone.deleted_in_ad == False,
                    CentrifyZone.name.ilike(f"%{q}%"),
                ).all()
                if zones:
                    zids = [z.id for z in zones]
                    comps = db.query(CentrifyComputer).filter(
                        CentrifyComputer.deleted_in_ad == False,
                        CentrifyComputer.zone_id.in_(zids),
                    ).limit(40).all()
                if not comps:
                    comps = db.query(CentrifyComputer).filter(
                        CentrifyComputer.deleted_in_ad == False,
                        (CentrifyComputer.name.ilike(f"%{q}%"))
                        | (CentrifyComputer.fqdn.ilike(f"%{q}%"))
                        | (CentrifyComputer.os_type.ilike(f"%{q}%")),
                    ).limit(40).all()
            else:
                comps = db.query(CentrifyComputer).filter_by(deleted_in_ad=False).limit(40).all()
            if not comps:
                return f"'{query}' ile eşleşen sunucu bulunamadı." if q else "Sunucu bulunamadı."
            # Zone rol sayısını da ekle (role definition soruları için)
            lines = []
            zone_role_cache: dict[int, int] = {}
            from app.models.centrify_zone import CentrifyRole
            for c in comps:
                z = db.query(CentrifyZone).filter_by(id=c.zone_id).first()
                if c.zone_id not in zone_role_cache:
                    zone_role_cache[c.zone_id] = db.query(CentrifyRole).filter_by(
                        zone_id=c.zone_id, deleted_in_ad=False,
                    ).count()
                lines.append(
                    f"- **{c.name}** zone={z.name if z else '?'} "
                    f"(zone_rol_sayısı={zone_role_cache[c.zone_id]}) "
                    f"fqdn=`{c.fqdn or '—'}` os=`{c.os_type or '—'}` agent=`{c.agent_version or '—'}`"
                )
            return "\n".join(lines)
        finally:
            db.close()
    except Exception as exc:
        return f"Arama hatası: {exc}"


def _tool_check_user_permissions(user: str) -> str:
    """Kullanıcının tüm zone'lardaki yetkilerini kontrol et — scope/host dahil."""
    try:
        from app.services.centrify.database import get_centrify_thread_session
        from app.models.centrify_zone import (
            CentrifyRoleAssignment, CentrifyRole, CentrifyZone, CentrifyComputer,
        )
        db = get_centrify_thread_session()
        if db is None:
            return "DB erişilemiyor"
        try:
            items = db.query(CentrifyRoleAssignment).filter(
                CentrifyRoleAssignment.deleted_in_ad == False,
                CentrifyRoleAssignment.assignee_name.ilike(f"%{user}%")
            ).all()
            if not items:
                return f"'{user}' için atama bulunamadı."
            lines = [
                f"## {user} Yetkileri",
                "Not: Bu listedeki atamalar dışında child zone mirası varsayılmaz.",
            ]
            for a in items:
                role = db.query(CentrifyRole).filter_by(id=a.role_id).first()
                zone = db.query(CentrifyZone).filter_by(id=a.zone_id).first()
                if role and zone:
                    cmds = []
                    for rc in (role.role_commands or []):
                        c = rc.command
                        if c and not c.deleted_in_ad:
                            cmds.append(f"`{c.name}`")
                    host = ""
                    if a.computer_id:
                        comp = db.query(CentrifyComputer).filter_by(id=a.computer_id).first()
                        if comp:
                            host = f", host={comp.name}"
                    lines.append(
                        f"- **{zone.name}** → {role.name} [{_role_login_flags(role)}] "
                        f"(scope: {a.scope_type}{host}): "
                        f"{', '.join(cmds[:12]) if cmds else 'komut yok'}"
                    )
            return "\n".join(lines)
        finally:
            db.close()
    except Exception as exc:
        return f"Kontrol hatası: {exc}"


def _tool_compare_roles(role_a: str, role_b: str) -> str:
    """İki rolün komutlarını ve login bayraklarını karşılaştır."""
    try:
        from app.services.centrify.database import get_centrify_thread_session
        from app.models.centrify_zone import CentrifyRole, CentrifyZone
        db = get_centrify_thread_session()
        if db is None:
            return "DB erişilemiyor"
        try:
            r1 = db.query(CentrifyRole).filter(CentrifyRole.name.ilike(f"%{role_a}%"), CentrifyRole.deleted_in_ad == False).first()
            r2 = db.query(CentrifyRole).filter(CentrifyRole.name.ilike(f"%{role_b}%"), CentrifyRole.deleted_in_ad == False).first()
            if not r1:
                return f"'{role_a}' rolü bulunamadı."
            if not r2:
                return f"'{role_b}' rolü bulunamadı."

            def _cmd_set(role):
                return {rc.command.name: rc.command.command_path for rc in (role.role_commands or []) if rc.command and not rc.command.deleted_in_ad}

            c1, c2 = _cmd_set(r1), _cmd_set(r2)
            only_a = set(c1) - set(c2)
            only_b = set(c2) - set(c1)
            both = set(c1) & set(c2)
            z1 = db.query(CentrifyZone).filter_by(id=r1.zone_id).first()
            z2 = db.query(CentrifyZone).filter_by(id=r2.zone_id).first()

            lines = [
                f"## {r1.name} ({z1.name if z1 else '?'}) vs {r2.name} ({z2.name if z2 else '?'})",
                f"### Login: {r1.name} → {_role_login_flags(r1)}",
                f"### Login: {r2.name} → {_role_login_flags(r2)}",
            ]
            if both:
                lines.append(f"### Ortak ({len(both)}): " + ", ".join(f"`{n}`" for n in sorted(both)))
            if only_a:
                lines.append(f"### Yalnızca {r1.name} ({len(only_a)}): " + ", ".join(f"`{n}`" for n in sorted(only_a)))
            if only_b:
                lines.append(f"### Yalnızca {r2.name} ({len(only_b)}): " + ", ".join(f"`{n}`" for n in sorted(only_b)))
            if not only_a and not only_b:
                lines.append("İki rol aynı komutlara sahip.")
            return "\n".join(lines)
        finally:
            db.close()
    except Exception as exc:
        return f"Karşılaştırma hatası: {exc}"


def _tool_effective_access(user: str, computer: str) -> str:
    from app.services.centrify.database import get_centrify_thread_session
    from app.services.centrify.query_service import resolve_effective_access, format_query_result
    db = get_centrify_thread_session()
    if db is None:
        return "DB erişilemiyor"
    try:
        return format_query_result("resolve_effective_access", resolve_effective_access(db, user=user, computer=computer))
    finally:
        db.close()


def _tool_diagnose_login(user: str, computer: str) -> str:
    from app.services.centrify.database import get_centrify_thread_session
    from app.services.centrify.query_service import diagnose_login_failure, format_query_result
    db = get_centrify_thread_session()
    if db is None:
        return "DB erişilemiyor"
    try:
        return format_query_result("diagnose_login_failure", diagnose_login_failure(db, user=user, computer=computer))
    finally:
        db.close()


def _tool_expiring_assignments(days: int = 30) -> str:
    from app.services.centrify.database import get_centrify_thread_session
    from app.services.centrify.query_service import find_expiring_assignments, format_query_result
    db = get_centrify_thread_session()
    if db is None:
        return "DB erişilemiyor"
    try:
        return format_query_result("find_expiring_assignments", find_expiring_assignments(db, days=days))
    finally:
        db.close()


def _tool_similar_roles(role: str = "", commands: Optional[list[str]] = None) -> str:
    from app.services.centrify.database import get_centrify_thread_session
    from app.services.centrify.query_service import find_similar_roles, format_query_result
    db = get_centrify_thread_session()
    if db is None:
        return "DB erişilemiyor"
    try:
        return format_query_result(
            "find_similar_roles",
            find_similar_roles(db, role=role, commands=commands, limit=10),
        )
    finally:
        db.close()


def _tool_similar_commands(command: str = "", path: str = "") -> str:
    from app.services.centrify.database import get_centrify_thread_session
    from app.services.centrify.query_service import find_similar_commands, format_query_result
    db = get_centrify_thread_session()
    if db is None:
        return "DB erişilemiyor"
    try:
        return format_query_result(
            "find_similar_commands",
            find_similar_commands(db, command=command, path=path, limit=15),
        )
    finally:
        db.close()


def _tool_explain_role(role: str) -> str:
    from app.services.centrify.database import get_centrify_thread_session
    from app.services.centrify.query_service import explain_role, format_query_result
    db = get_centrify_thread_session()
    if db is None:
        return "DB erişilemiyor"
    try:
        return format_query_result("explain_role", explain_role(db, role=role))
    finally:
        db.close()


def _tool_explain_command(command: str) -> str:
    from app.services.centrify.database import get_centrify_thread_session
    from app.services.centrify.query_service import explain_command, format_query_result
    db = get_centrify_thread_session()
    if db is None:
        return "DB erişilemiyor"
    try:
        return format_query_result("explain_command", explain_command(db, command=command))
    finally:
        db.close()


TOOLS = {
    "search_roles": _tool_search_roles,
    "search_commands": _tool_search_commands,
    "search_assignments": _tool_search_assignments,
    "search_computers": _tool_search_computers,
    "check_user_permissions": _tool_check_user_permissions,
    "compare_roles": _tool_compare_roles,
    "resolve_effective_access": _tool_effective_access,
    "diagnose_login_failure": _tool_diagnose_login,
    "find_expiring_assignments": _tool_expiring_assignments,
    "find_similar_roles": _tool_similar_roles,
    "find_similar_commands": _tool_similar_commands,
    "explain_role": _tool_explain_role,
    "explain_command": _tool_explain_command,
}


def _extract_host_token(lower: str) -> Optional[str]:
    import re
    m = re.search(r"\b([a-z0-9][a-z0-9_-]{2,}(?:\.[a-z0-9._-]+)+)\b", lower)
    if m:
        tok = m.group(1)
        # user.name.domain dışı — basit user.name değilse host say
        if not re.fullmatch(r"[a-z][a-z0-9_-]*\.[a-z][a-z0-9_-]*", tok):
            return tok
    for m in re.finditer(r"\b([a-z0-9][a-z0-9_-]{3,})\b", lower):
        token = m.group(1)
        if token.startswith("grp_"):
            continue
        if re.fullmatch(r"[a-z]+\.[a-z]+", token):
            continue
        if token in (
            "zone", "linux", "unix", "oracle", "network", "backup", "tomcat", "windows",
            "computer", "sunucu", "hangi", "komut", "yetki", "erişim", "login", "giriş",
            "applications", "universal", "global", "websphere", "other",
        ):
            continue
        # host benzeri: tire/sayı içeren veya bilinen suffix
        if "-" in token or re.search(r"\d", token) or token.endswith(("prd1", "prod", "srv")):
            return token
    return None


def _extract_person_token(lower: str, exclude: Optional[set] = None) -> Optional[str]:
    import re
    exclude = exclude or set()
    # Önce user.name / GRP_
    for m in re.finditer(r"\b(grp_[a-z0-9_]+|[a-z][a-z0-9_-]+\.[a-z][a-z0-9_-]+)\b", lower):
        token = m.group(1)
        if token in exclude:
            continue
        return token
    return None


def _run_tool_if_needed(message: str) -> Optional[str]:
    """Kullanıcı mesajındaki anahtar kelimelere göre otomatik tool çağırma."""
    lower = message.lower()
    results: list[str] = []

    import re

    # ── Deterministik hesaplayıcılar (öncelikli) ──
    host = _extract_host_token(lower)
    person = _extract_person_token(lower, exclude={host} if host else set())

    login_kw = ["neden bağlan", "bağlanam", "login", "giriş yapam", "oturum açılam", "diagnose", "teşhis"]
    access_kw = [
        "hangi komut", "çalıştırabilir", "effective", "etkili yetki", "root olarak",
        "dzdo ile", "yetkisi var mı", "komutları neler", "erişimi",
    ]
    expire_kw = ["süresi dol", "expire", "expiring", "dolacak atama", "bitiş tarih", "end_time"]
    similar_role_kw = [
        "benzer rol", "benzeri rol", "benzer roller", "aynı işi yapan rol", "çakışan rol",
        "rol var mı", "mevcut rol", "duplicate role", "similar role",
    ]
    similar_cmd_kw = [
        "benzer komut", "benzer right", "aynı komut", "komut var mı", "similar command",
        "path benzer", "çakışan komut",
    ]
    explain_role_kw = ["ne işe yarar", "ne yapar", "amacı ne", "açıkla", "anlat", "what does"]
    explain_cmd_kw = ["komut ne işe", "right ne işe", "path ne işe"]

    if any(kw in lower for kw in login_kw) and person and host:
        results.append(_tool_diagnose_login(person, host))
    elif any(kw in lower for kw in access_kw) and person and host:
        results.append(_tool_effective_access(person, host))
    elif any(kw in lower for kw in expire_kw):
        days = 30
        m = re.search(r"(\d+)\s*gün", lower)
        if m:
            days = int(m.group(1))
        results.append(_tool_expiring_assignments(days))
    elif any(kw in lower for kw in similar_role_kw):
        role_tok = None
        m = re.search(r"(?:rol(?:ü|u)?|role)\s+([a-z0-9_./-]+)", lower)
        if m:
            role_tok = m.group(1)
        if not role_tok:
            m = re.search(r"\b([a-z][a-z0-9_-]{2,}(?:-[a-z0-9_-]+)+)\b", lower)
            if m:
                role_tok = m.group(1)
        # "systemctl restart ve chronyc içeren rol" → komut ipuçları
        cmd_hints = re.findall(r"`([^`]+)`|/[\w./*-]+|[a-z0-9_-]+\.(?:sh|py|service)", lower)
        results.append(_tool_similar_roles(role=role_tok or "", commands=cmd_hints or None))
    elif any(kw in lower for kw in similar_cmd_kw):
        cmd_tok = ""
        m = re.search(r"(?:komut|command|right|path)\s+([^\s,]+)", lower)
        if m:
            cmd_tok = m.group(1)
        if not cmd_tok:
            m = re.search(r"(/[\w./*-]+|[a-z0-9_-]+(?:-[a-z0-9_-]+)+)", lower)
            if m:
                cmd_tok = m.group(1)
        results.append(_tool_similar_commands(command=cmd_tok, path=cmd_tok if cmd_tok.startswith("/") else ""))
    elif any(kw in lower for kw in explain_cmd_kw) or (
        any(kw in lower for kw in explain_role_kw) and any(x in lower for x in ("komut", "command", "right", "path", "/usr", "/bin"))
    ):
        cmd_tok = ""
        m = re.search(r"(?:komut|command|right)\s+([^\s?]+)", lower)
        if m:
            cmd_tok = m.group(1)
        if not cmd_tok:
            m = re.search(r"(/[\w./*-]+|[a-z0-9_-]+(?:-[a-z0-9_-]+)+)", lower)
            if m:
                cmd_tok = m.group(1)
        if cmd_tok:
            results.append(_tool_explain_command(cmd_tok))
    elif any(kw in lower for kw in explain_role_kw) and any(x in lower for x in ("rol", "role")):
        role_tok = ""
        m = re.search(r"(?:rol(?:ü|u)?|role)\s+([a-z0-9_./-]+)", lower)
        if m:
            role_tok = m.group(1)
        if not role_tok:
            m = re.search(r"\b([a-z][a-z0-9_-]{2,}(?:-[a-z0-9_-]+)+)\b", lower)
            if m:
                role_tok = m.group(1)
        if role_tok:
            results.append(_tool_explain_role(role_tok))
    elif person and host and any(kw in lower for kw in ["yetki", "izin", "permission", "erişim", "access", "miras"]):
        results.append(_tool_effective_access(person, host))

    # Karşılaştırma
    cmp = re.search(
        r"(?:karşılaştır|compare|fark|diff)\s+(\S+)\s+(?:ile|vs|and|with|&)\s+(\S+)",
        lower,
    ) or re.search(
        r"(\S+)\s+ile\s+(\S+)\s+(?:rollerini|rolü|role|komut|login|haklar)",
        lower,
    )
    if cmp:
        results.append(_tool_compare_roles(cmp.group(1), cmp.group(2)))

    # Yetki kontrol — yalnızca host yoksa genel liste
    if not host and any(kw in lower for kw in ["yetki", "izin", "permission", "erişim", "access", "çalıştırabilir", "miras"]):
        if person:
            results.append(_tool_check_user_permissions(person))

    # Rol arama
    role_kw = ["rol ara", "role search", "benzer rol", "rol bul",
               "hangi roller", "roller neler", "rolleri listele", "roles",
               "rol tanımı", "role definition", "sistem rol"]
    if any(kw in lower for kw in role_kw) and not (person and host):
        q = ""
        for pat in [r"(?:zone|zon)\S*\s+(\S+)", r"(\S+)\s+(?:rolü|role|rolleri|roller)"]:
            m = re.search(pat, lower)
            if m:
                q = m.group(1)
                break
        if not q:
            q = lower.split("rol")[-1].strip()[:50]
        if q:
            results.append(_tool_search_roles(q))

    # Komut arama (effective access zaten alındıysa atla)
    cmd_kw = ["komut ara", "command search", "komut bul", "right ara",
              "hangi komutlar", "komutlar neler", "komutları listele",
              "atanmış komutlar", "commands", "command_path", "run_as", "runas"]
    if any(kw in lower for kw in cmd_kw) and not (person and host):
        q = ""
        for pat in [r"(\S+)\s+(?:komutları|komutlar|commands)", r"(?:komut|command)\S*\s+(\S+)"]:
            m = re.search(pat, lower)
            if m:
                q = m.group(1)
                break
        if not q:
            q = lower.split("komut")[-1].strip()[:50]
        if q:
            results.append(_tool_search_commands(q))

    # Atama arama
    assign_kw = ["atama ara", "assignment", "atanmış", "atama bul",
                 "kime atanmış", "hangi kullanıcı", "kim erişebilir",
                 "hangi grup", "scope_type", "computer-scope", "computer scope",
                 "zone-scope"]
    if any(kw in lower for kw in assign_kw) and not any(kw in lower for kw in expire_kw):
        q = person or ""
        if not q:
            for pat in [
                r"\b(grp_[a-z0-9_]+|[a-z]+\.[a-z]+)\b",
                r"(\S+)\s+(?:atanmış|atama|assignment)",
            ]:
                m = re.search(pat, lower)
                if m:
                    q = m.group(1)
                    break
        if q:
            results.append(_tool_search_assignments(q))

    # Sunucu arama
    comp_kw = ["sunucu", "computer", "fqdn", "ajan", "agent_version",
               "agent sürüm", "hangi host", "host adı"]
    if any(kw in lower for kw in comp_kw) and not (person and host and any(kw in lower for kw in access_kw + login_kw)):
        q = host or ""
        for zone_hint in ("oracle applications", "other applications", "tomcat",
                          "websphere", "network", "backup", "universal", "global", "oracle"):
            if zone_hint in lower:
                q = zone_hint
                break
        results.append(_tool_search_computers(q or ""))

    seen = set()
    uniq = []
    for r in results:
        if r and r not in seen:
            seen.add(r)
            uniq.append(r)
    return "\n\n---\n\n".join(uniq) if uniq else None


# ── LLM streaming ────────────────────────────────────────────


async def _stream_ollama(prompt: str, model: str):
    """Ollama /api/chat streaming — system/user role ayrımı destekler."""
    ollama_url = getattr(settings, "OLLAMA_URL", "") or "http://localhost:11434"
    url = f"{ollama_url.rstrip('/')}/api/chat"

    # prompt'u system ve user kısımlarına ayır
    if "\n\nKullanıcı: " in prompt:
        idx = prompt.rfind("\n\nKullanıcı: ")
        system_part = prompt[:idx]
        user_part = prompt[idx:].replace("\n\nKullanıcı: ", "").replace("\n\nAsistan:", "").strip()
    else:
        system_part = ""
        user_part = prompt

    messages = []
    if system_part:
        messages.append({"role": "system", "content": system_part})
    messages.append({"role": "user", "content": user_part})

    payload = {"model": model, "messages": messages, "stream": True}
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, json=payload) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode(errors="replace")[:300]
                    yield f"data: {json.dumps({'token': f'[Ollama Hatası {resp.status_code}] {body}'})}\n\n"
                    return
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        msg = data.get("message", {})
                        token = msg.get("content", "")
                        if token:
                            yield f"data: {json.dumps({'token': token})}\n\n"
                        if data.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue
    except Exception as exc:
        yield f"data: {json.dumps({'token': f'Ollama bağlantı hatası ({ollama_url}): {exc}'})}\n\n"


async def _stream_remote_llm(prompt: str, model: str):
    """REMOTE_LLM (OpenAI-uyumlu) streaming."""
    from app.services.llm_external import resolve_external_chat_target
    target = resolve_external_chat_target(model)
    if not target:
        if remote_llm_enabled():
            url = (settings.REMOTE_LLM_URL or "").rstrip("/")
            api_key = settings.REMOTE_LLM_API_KEY or ""
            model_name = settings.REMOTE_LLM_MODEL or model
            if not url or not api_key:
                yield f"data: {json.dumps({'token': 'LLM API anahtarı veya URL yapılandırılmamış. Ayarlar → AI bölümünü kontrol edin.'})}\n\n"
                return
            url = url + "/chat/completions"
        else:
            yield f"data: {json.dumps({'token': 'LLM yapılandırması bulunamadı. Ayarlar → AI bölümünden Ollama veya Remote LLM yapılandırın.'})}\n\n"
            return
    else:
        url = target.url
        api_key = target.api_key
        model_name = target.model

    if not api_key or not api_key.strip():
        yield f"data: {json.dumps({'token': 'LLM API anahtarı boş. Ayarlar → AI bölümünü kontrol edin.'})}\n\n"
        return

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "max_tokens": 2048,
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    yield f"data: {json.dumps({'token': f'[API Hatası {resp.status_code}]'})}\n\n"
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        token = delta.get("content", "")
                        if token:
                            yield f"data: {json.dumps({'token': token})}\n\n"
                    except json.JSONDecodeError:
                        continue
    except Exception as exc:
        yield f"data: {json.dumps({'token': f'LLM bağlantı hatası: {exc}'})}\n\n"


# ── API endpoint'leri ─────────────────────────────────────────


@router.post("/stream")
async def centrify_chat_stream(
    body: CentrifyChatRequest,
    request: Request,
    user: User = Depends(require_module("level1")),
):
    """SSE streaming chat — Centrify asistanı (level1 modülü zorunlu)."""
    user_id = int(user.id or 0)
    username = user.username or "anonymous"

    # Context topla
    ctx = _gather_centrify_context(body.zone_id)
    tool_result = _run_tool_if_needed(body.message)
    if tool_result:
        logger.info(
            "centrify_chat_tool user=%s zone_id=%s msg_preview=%s tool_bytes=%s",
            username,
            body.zone_id,
            (body.message or "")[:120],
            len(tool_result),
        )

    # Session yönetimi
    from app.core.database import SessionLocal
    sdb = SessionLocal()
    try:
        uid = require_user_id(user)
        if body.session_id:
            session = get_owned_session(sdb, body.session_id, uid, CATEGORY)
        else:
            session = None

        if not session:
            title = body.message[:60] + ("…" if len(body.message) > 60 else "")
            session = create_owned_session(
                sdb, user_id=uid, title=title, category=CATEGORY, server_ids=[],
            )

        # Geçmiş mesajları
        history = sdb.query(ChatMessage).filter_by(session_id=session.id).order_by(ChatMessage.created_at).all()
        history_text = ""
        for m in history[-6:]:
            role = "Kullanıcı" if m.role == "user" else "Asistan"
            history_text += f"\n{role}: {m.content[:500]}"

        # Kullanıcı mesajını kaydet
        sdb.add(ChatMessage(session_id=session.id, role="user", content=body.message))
        sdb.commit()
        session_id = session.id
    finally:
        sdb.close()

    # Prompt oluştur
    prompt_parts = [SYSTEM_PROMPT, "\n\n## Mevcut Centrify Verisi\n", ctx]
    if tool_result:
        prompt_parts.append(f"\n\n## Tool Sonucu\n{tool_result}")
    if history_text:
        prompt_parts.append(f"\n\n## Önceki Konuşma{history_text}")
    prompt_parts.append(f"\n\nKullanıcı: {body.message}\n\nAsistan:")

    prompt = "\n".join(prompt_parts)

    from app.core.database import SessionLocal as _SL
    _mdb = _SL()
    try:
        model = get_active_model(_mdb)
    finally:
        _mdb.close()
    from app.services.llm_external import detect_provider
    provider = detect_provider(model)

    async def generate():
        full_response = []
        try:
            # LLM yapılandırılmamışsa tool/context sonuçlarını doğrudan göster
            from app.services.llm_external import resolve_external_chat_target as _resolve
            _ext = _resolve(model)
            _has_remote = remote_llm_enabled() and bool((settings.REMOTE_LLM_API_KEY or "").strip())
            _has_ollama_chat = False
            if provider == "ollama":
                try:
                    import httpx as _hx
                    _ollama_url = getattr(settings, "OLLAMA_URL", "") or "http://localhost:11434"
                    _r = _hx.get(f"{_ollama_url.rstrip('/')}/api/tags", timeout=3)
                    _models = [m.get("name", "") for m in _r.json().get("models", [])]
                    _has_ollama_chat = any(not ("embed" in n or "nomic" in n) for n in _models)
                except Exception:
                    pass
            llm_available = bool(_ext) or _has_remote or _has_ollama_chat

            if not llm_available:
                fallback_parts = ["**Centrify Asistan** _(LLM yapılandırılmamış — veriye dayalı yanıt)_\n\n"]
                if tool_result:
                    fallback_parts.append(f"{tool_result}\n\n")
                fallback_parts.append(f"📊 **Mevcut Veri:**\n{ctx[:1500]}")
                fallback_text = "\n".join(fallback_parts)
                yield f"data: {json.dumps({'token': fallback_text})}\n\n"
                yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"
                sdb2 = SessionLocal()
                try:
                    sdb2.add(ChatMessage(session_id=session_id, role="assistant", content=fallback_text))
                    sdb2.commit()
                finally:
                    sdb2.close()
                return

            if provider == "ollama":
                gen = _stream_ollama(prompt, model)
            else:
                gen = _stream_remote_llm(prompt, model)

            async for chunk in gen:
                full_response.append(chunk)
                yield chunk

            yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"

            # Asistan yanıtını kaydet
            response_text = ""
            for c in full_response:
                if c.startswith("data: "):
                    try:
                        d = json.loads(c[6:].strip())
                        response_text += d.get("token", "")
                    except Exception:
                        pass
            if response_text:
                sdb2 = SessionLocal()
                try:
                    sdb2.add(ChatMessage(session_id=session_id, role="assistant", content=response_text))
                    sdb2.commit()
                finally:
                    sdb2.close()
        except Exception as exc:
            logger.exception("Centrify chat stream hatası")
            yield f"data: {json.dumps({'token': f'[Hata: {exc}]'})}\n\n"
            yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/sessions")
async def list_sessions(request: Request, user: User = Depends(require_module("level1"))):
    """Centrify chat oturumlarını listele."""
    from app.core.database import SessionLocal
    sdb = SessionLocal()
    try:
        uid = require_user_id(user)
        sessions = (
            sessions_q(sdb, uid, CATEGORY)
            .order_by(ChatSession.created_at.desc())
            .limit(50)
            .all()
        )
        return [
            CentrifyChatSessionOut(
                id=s.id, title=s.title or "",
                created_at=s.created_at.isoformat() if s.created_at else "",
                message_count=sdb.query(ChatMessage).filter_by(session_id=s.id).count(),
            )
            for s in sessions
        ]
    finally:
        sdb.close()


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: int, user: User = Depends(require_module("level1"))):
    """Oturum mesajlarını getir."""
    from app.core.database import SessionLocal
    sdb = SessionLocal()
    try:
        require_owned_session(sdb, session_id, require_user_id(user), CATEGORY)
        msgs = (
            sdb.query(ChatMessage)
            .filter_by(session_id=session_id)
            .order_by(ChatMessage.created_at)
            .all()
        )
        return [
            {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat() if m.created_at else ""}
            for m in msgs
        ]
    finally:
        sdb.close()


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: int, user: User = Depends(require_module("level1"))):
    """Chat oturumunu sil."""
    from app.core.database import SessionLocal
    sdb = SessionLocal()
    try:
        session = require_owned_session(sdb, session_id, require_user_id(user), CATEGORY)
        sdb.query(ChatMessage).filter_by(session_id=session_id).delete()
        sdb.delete(session)
        sdb.commit()
        return {"ok": True}
    finally:
        sdb.close()
