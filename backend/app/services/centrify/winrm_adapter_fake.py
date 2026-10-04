"""Fake WinRM Centrify Adaptörü — geliştirme ve test ortamı için.

Gerçek WinRM bağlantısı olmadan, sabit verilerle adaptör arayüzünü simüle eder.
Production'da KULLANILMAZ.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from app.services.centrify.winrm_adapter import ConnectionTestResult, OpResult

logger = logging.getLogger(__name__)

_FAKE_ZONES = [
    {
        "ad_dn": "CN=Zone-Prod,CN=Zones,OU=Centrify,DC=example,DC=com",
        "name": "Zone-Prod",
        "description": "Üretim zone'u",
        "zone_type": "hierarchical",
        "parent_zone_dn": "",
        "ad_guid": str(uuid.uuid5(uuid.NAMESPACE_DNS, "zone-prod")),
    },
    {
        "ad_dn": "CN=Zone-Test,CN=Zones,OU=Centrify,DC=example,DC=com",
        "name": "Zone-Test",
        "description": "Test zone'u",
        "zone_type": "hierarchical",
        "parent_zone_dn": "",
        "ad_guid": str(uuid.uuid5(uuid.NAMESPACE_DNS, "zone-test")),
    },
    {
        "ad_dn": "CN=Zone-Dev,CN=Zone-Test,CN=Zones,OU=Centrify,DC=example,DC=com",
        "name": "Zone-Dev",
        "description": "Geliştirme zone'u (Zone-Test altında)",
        "zone_type": "hierarchical",
        "parent_zone_dn": "CN=Zone-Test,CN=Zones,OU=Centrify,DC=example,DC=com",
        "ad_guid": str(uuid.uuid5(uuid.NAMESPACE_DNS, "zone-dev")),
    },
]

_FAKE_ROLES = {
    "Zone-Prod": [
        {
            "name": "sysadmin",
            "description": "Tam yetkili sistem yöneticisi",
            "ad_guid": str(uuid.uuid5(uuid.NAMESPACE_DNS, "role-sysadmin")),
            "ad_dn": "CN=sysadmin,CN=Roles,CN=Zone-Prod,CN=Zones,OU=Centrify,DC=example,DC=com",
            "is_system_role": "false",
            "password_login_allowed": "true",
            "sso_login_allowed": "true",
            "require_mfa": "false",
            "rights": "reboot||systemctl-restart",
        },
        {
            "name": "dba-oracle",
            "description": "Oracle DBA rolü",
            "ad_guid": str(uuid.uuid5(uuid.NAMESPACE_DNS, "role-dba-oracle")),
            "ad_dn": "CN=dba-oracle,CN=Roles,CN=Zone-Prod,CN=Zones,OU=Centrify,DC=example,DC=com",
            "is_system_role": "false",
            "password_login_allowed": "true",
            "sso_login_allowed": "false",
            "require_mfa": "true",
            "rights": "systemctl-restart",
        },
        {
            "name": "readonly",
            "description": "Salt okunur erişim",
            "ad_guid": str(uuid.uuid5(uuid.NAMESPACE_DNS, "role-readonly")),
            "ad_dn": "CN=readonly,CN=Roles,CN=Zone-Prod,CN=Zones,OU=Centrify,DC=example,DC=com",
            "is_system_role": "false",
            "password_login_allowed": "true",
            "sso_login_allowed": "true",
            "require_mfa": "false",
            "rights": "",
        },
        {
            "name": "ops-reboot",
            "description": "Yalnızca reboot hakkı — sysadmin benzeri daraltılmış",
            "ad_guid": str(uuid.uuid5(uuid.NAMESPACE_DNS, "role-ops-reboot")),
            "ad_dn": "CN=ops-reboot,CN=Roles,CN=Zone-Prod,CN=Zones,OU=Centrify,DC=example,DC=com",
            "is_system_role": "false",
            "password_login_allowed": "false",
            "sso_login_allowed": "false",
            "require_mfa": "false",
            "rights": "reboot",
        },
    ],
}

_FAKE_COMMANDS = {
    "Zone-Prod": [
        {
            "name": "reboot",
            "description": "Sunucu yeniden başlatma",
            "ad_guid": str(uuid.uuid5(uuid.NAMESPACE_DNS, "cmd-reboot")),
            "ad_dn": "CN=reboot,CN=Commands,CN=Zone-Prod,CN=Zones,OU=Centrify,DC=example,DC=com",
            "command_path": "/usr/sbin/reboot",
            "match_type": "exact",
            "run_as_user": "root",
            "run_as_group": "",
            "auth_type": "password",
        },
        {
            "name": "systemctl-restart",
            "description": "Servis yeniden başlatma",
            "ad_guid": str(uuid.uuid5(uuid.NAMESPACE_DNS, "cmd-systemctl")),
            "ad_dn": "CN=systemctl-restart,CN=Commands,CN=Zone-Prod,CN=Zones,OU=Centrify,DC=example,DC=com",
            "command_path": "/usr/bin/systemctl restart *",
            "match_type": "glob",
            "run_as_user": "root",
            "run_as_group": "",
            "auth_type": "password",
        },
        {
            "name": "shutdown",
            "description": "Sunucu kapatma",
            "ad_guid": str(uuid.uuid5(uuid.NAMESPACE_DNS, "cmd-shutdown")),
            "ad_dn": "CN=shutdown,CN=Commands,CN=Zone-Prod,CN=Zones,OU=Centrify,DC=example,DC=com",
            "command_path": "/usr/sbin/shutdown",
            "match_type": "exact",
            "run_as_user": "root",
            "run_as_group": "",
            "auth_type": "password",
        },
    ],
}

_FAKE_COMPUTERS = {
    "Zone-Prod": [
        {
            "name": "prod-app-01",
            "fqdn": "prod-app-01.example.com",
            "os_type": "Linux",
            "agent_version": "5.9.0",
            "ad_guid": str(uuid.uuid5(uuid.NAMESPACE_DNS, "comp-prod-app-01")),
            "ad_dn": "CN=prod-app-01,CN=Computers,CN=Zone-Prod,CN=Zones,OU=Centrify,DC=example,DC=com",
        },
    ],
}

_FAKE_UNIX = {
    "Zone-Prod": [
        {
            "user_name": "john.smith",
            "user_dn": "CN=John Smith,OU=Users,DC=example,DC=com",
            "uid": "10001",
            "gid": "10000",
            "home_dir": "/home/john.smith",
            "shell": "/bin/bash",
            "gecos": "John Smith",
            "enabled": "true",
        },
    ],
}

_FAKE_ASSIGNMENTS = {
    "Zone-Prod": [
        {
            "role_name": "sysadmin",
            "assignee_type": "user",
            "assignee_dn": "CN=John Smith,OU=Users,DC=example,DC=com",
            "assignee_name": "john.smith",
            "scope_type": "zone",
            "scope_dn": "",
            "ad_guid": str(uuid.uuid5(uuid.NAMESPACE_DNS, "ra-john-sysadmin")),
            "ad_dn": "",
            "start_time": "",
            "end_time": "",
        },
    ],
}


def _zone_name(zone_dn: str) -> str:
    return zone_dn.split(",")[0].replace("CN=", "")


class WinRMCentrifyAdapterFake:
    """Test/dev için WinRM bağlantısı olmadan çalışan fake adaptör."""

    def __init__(self, **kwargs):
        logger.info("Fake Centrify adaptörü kullanılıyor (geliştirme modu)")

    def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(
            connected=True,
            winrm_ok=True,
            adedit_found=True,
            adedit_version="ADEdit 5.9.0 (fake)",
            zone_count=len(_FAKE_ZONES),
            latency_ms=5,
        )

    def list_zones(self) -> list[dict]:
        return list(_FAKE_ZONES)

    def list_zone_inventory(self, zone_dn: str) -> dict:
        zn = _zone_name(zone_dn)
        return {
            "zone_dn": zone_dn,
            "roles": list(_FAKE_ROLES.get(zn, [])),
            "commands": list(_FAKE_COMMANDS.get(zn, [])),
            "assignments": list(_FAKE_ASSIGNMENTS.get(zn, [])),
            "computers": list(_FAKE_COMPUTERS.get(zn, [])),
            "unix_profiles": list(_FAKE_UNIX.get(zn, [])),
            "computer_roles": [],
        }

    def list_roles(self, zone_dn: str) -> list[dict]:
        return list(_FAKE_ROLES.get(_zone_name(zone_dn), []))

    def list_commands(self, zone_dn: str) -> list[dict]:
        return list(_FAKE_COMMANDS.get(_zone_name(zone_dn), []))

    def list_role_assignments(self, zone_dn: str) -> list[dict]:
        return list(_FAKE_ASSIGNMENTS.get(_zone_name(zone_dn), []))

    def list_computer_roles(self, zone_dn: str) -> list[dict]:
        return []

    def list_computers(self, zone_dn: str) -> list[dict]:
        return list(_FAKE_COMPUTERS.get(_zone_name(zone_dn), []))

    def list_unix_profiles(self, zone_dn: str) -> list[dict]:
        return list(_FAKE_UNIX.get(_zone_name(zone_dn), []))

    def get_role_detail(self, zone_dn: str, role_name: str) -> dict:
        for r in self.list_roles(zone_dn):
            if r["name"] == role_name:
                rights = r.get("rights") or ""
                return {
                    **r,
                    "rights": [x for x in str(rights).split("||") if x],
                }
        return {"error": f"role not found: {role_name}"}

    @classmethod
    def from_config(cls, config: dict) -> "WinRMCentrifyAdapterFake":
        return cls()
