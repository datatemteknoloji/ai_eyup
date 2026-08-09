from __future__ import annotations

from typing import Any

from app.modules import (
    asm,
    filesystem,
    hostname,
    limits,
    local_user,
    log_collect,
    mail_config,
    network,
    packages,
    path_perms,
    reboot,
    services,
    sudoers,
    sysctl,
    vlan,
)

MODULES: dict[str, Any] = {
    "local_user": local_user,
    "log_collect": log_collect,
    "hostname": hostname,
    "reboot": reboot,
    "sudoers": sudoers,
    "filesystem": filesystem,
    "path_perms": path_perms,
    "limits": limits,
    "sysctl": sysctl,
    "vlan": vlan,
    "network": network,
    "asm": asm,
    "packages": packages,
    "services": services,
    "mail_config": mail_config,
}


def get_module(name: str):
    mod = MODULES.get(name)
    if mod is None:
        raise ValueError(f"Desteklenmeyen modül: {name}")
    return mod


def supported_modules() -> set[str]:
    return set(MODULES.keys())
