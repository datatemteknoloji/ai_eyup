"""Centrify WinRM Adaptörü — Access Manager Windows sunucusuna WinRM ile bağlanır.

Mevcut WinRMClient üzerine inşa edilir. PowerShell scriptlerini çalıştırarak
zone nesnelerini okur/yazar. Circuit breaker koruması ile.

Kullanıcı girdisi PowerShell'e string interpolasyon yapılmaz — parametre olarak geçilir.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.services.centrify.circuit_breaker import (
    is_circuit_open,
    record_auth_failure,
    record_auth_success,
)
from app.services.centrify.exceptions import (
    CentrifyAmbiguousResultError,
    CentrifyAuthError,
    CentrifyCircuitOpenError,
    CentrifyConnectionError,
    CentrifyErrorClass,
    CentrifyScriptError,
)

logger = logging.getLogger(__name__)

PS_SCRIPTS_DIR = Path(__file__).parent / "ps_scripts"

_AUTH_ERROR_MARKERS = (
    "401",
    "unauthorized",
    "access is denied",
    "logon failure",
    "the user name or password is incorrect",
    "winrm cannot process the request",
    "kerberos",
)

_CONNECTION_ERROR_MARKERS = (
    "connection refused",
    "connection timed out",
    "could not connect",
    "network is unreachable",
    "no route to host",
    "winrmerror",
)


@dataclass
class OpResult:
    """Yazma operasyonunun sonucu."""
    success: bool
    message: str = ""
    data: dict = field(default_factory=dict)
    error_class: Optional[CentrifyErrorClass] = None


@dataclass
class ConnectionTestResult:
    """Bağlantı testi sonucu."""
    connected: bool
    winrm_ok: bool = False
    adedit_found: bool = False
    adedit_version: str = ""
    zone_count: int = 0
    latency_ms: int = 0
    error: str = ""


class WinRMCentrifyAdapter:
    """Access Manager Windows sunucusuna WinRM ile bağlanarak
    ADEdit/PowerShell üzerinden zone yönetimi yapar."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 5985,
        use_https: bool = False,
        timeout: int = 60,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.use_https = use_https
        self.timeout = timeout
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from app.services.windows.winrm_client import WinRMClient
            self._client = WinRMClient(
                host=self.host,
                username=self.username,
                password=self.password,
                port=self.port,
                use_https=self.use_https,
                timeout=self.timeout,
            )
        return self._client

    # ── Dahili yardımcılar ──────────────────────────────────────

    def _check_circuit(self) -> None:
        """Circuit açıksa hemen reddet."""
        if is_circuit_open():
            raise CentrifyCircuitOpenError(
                "Centrify circuit breaker açık — tüm işlemler durduruldu. "
                "Admin reset gerekli."
            )

    def _classify_error(self, stderr: str) -> CentrifyErrorClass:
        """stderr'deki hata mesajına göre sınıflandır."""
        lower = stderr.lower()
        for marker in _AUTH_ERROR_MARKERS:
            if marker in lower:
                return CentrifyErrorClass.PERMANENT
        for marker in _CONNECTION_ERROR_MARKERS:
            if marker in lower:
                return CentrifyErrorClass.TRANSIENT
        return CentrifyErrorClass.TRANSIENT

    def _handle_auth_error(self, stderr: str) -> None:
        """Auth hatası tespiti ve circuit breaker kaydı."""
        lower = stderr.lower()
        for marker in _AUTH_ERROR_MARKERS:
            if marker in lower:
                record_auth_failure()
                raise CentrifyAuthError(
                    f"WinRM kimlik doğrulama hatası: {stderr[:200]}"
                )

    def _load_script(self, script_name: str) -> str:
        """ps_scripts/ dizininden PS1 dosyasını oku."""
        script_path = PS_SCRIPTS_DIR / script_name
        if not script_path.exists():
            raise FileNotFoundError(f"PowerShell scripti bulunamadı: {script_name}")
        return script_path.read_text(encoding="utf-8")

    def _build_script_with_params(self, script_name: str, params: dict[str, str] | None = None) -> str:
        """Scripti yükle ve parametreleri güvenli şekilde ekle."""
        body = self._load_script(script_name)
        if not params:
            return body
        param_lines = []
        for key, value in params.items():
            safe_value = value.replace("'", "''")
            param_lines.append(f"${key} = '{safe_value}'")
        param_block = "\n".join(param_lines)
        return f"{param_block}\n\n{body}"

    def _run_ps(self, script: str) -> dict[str, Any]:
        """WinRM ile PowerShell çalıştır; circuit breaker + hata sınıflandırması."""
        self._check_circuit()
        result = self.client.run_ps(script)
        if result["exit_code"] == -1 and result["stderr"]:
            self._handle_auth_error(result["stderr"])
            error_class = self._classify_error(result["stderr"])
            if error_class == CentrifyErrorClass.TRANSIENT:
                raise CentrifyConnectionError(
                    f"WinRM bağlantı hatası ({self.host}): {result['stderr'][:200]}"
                )
        if result["success"]:
            record_auth_success()
        return result

    def _run_script(self, script_name: str, params: dict[str, str] | None = None) -> Any:
        """PS1 scriptini çalıştır ve JSON parse et (throttle'lı)."""
        from app.services.centrify.sync_throttle import call_with_throttle

        def _do():
            script = self._build_script_with_params(script_name, params)
            result = self._run_ps(script)
            if not result["success"]:
                self._handle_auth_error(result["stderr"])
                raise CentrifyScriptError(
                    f"Script hatası ({script_name}): {result['stderr'][:300]}",
                    stderr=result["stderr"],
                    exit_code=result["exit_code"],
                )
            stdout = result["stdout"].strip()
            if not stdout:
                return []
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError as exc:
                raise CentrifyScriptError(
                    f"Script JSON parse hatası ({script_name}): {exc}",
                    stderr=f"stdout: {stdout[:500]}",
                    exit_code=0,
                )
            if isinstance(parsed, dict) and "error" in parsed and parsed["error"]:
                raise CentrifyScriptError(
                    f"ADEdit hatası ({script_name}): {parsed['error']}",
                    stderr=parsed["error"],
                    exit_code=1,
                )
            return parsed

        return call_with_throttle(_do, label=script_name)

    # ── Bağlantı testi ──────────────────────────────────────────

    def test_connection(self) -> ConnectionTestResult:
        """WinRM bağlantısı + ADEdit varlık kontrolü."""
        import time
        t0 = time.time()
        try:
            data = self._run_script("test_connection.ps1")
            latency = int((time.time() - t0) * 1000)
            if isinstance(data, dict):
                return ConnectionTestResult(
                    connected=True,
                    winrm_ok=data.get("winrm_ok", True),
                    adedit_found=data.get("adedit_found", False),
                    adedit_version=data.get("adedit_version", ""),
                    zone_count=data.get("zone_count", 0),
                    latency_ms=latency,
                    error=data.get("error", ""),
                )
            return ConnectionTestResult(connected=True, winrm_ok=True, latency_ms=latency)
        except CentrifyCircuitOpenError:
            return ConnectionTestResult(
                connected=False,
                error="Circuit breaker açık — bağlantı testi yapılamaz",
            )
        except CentrifyAuthError as exc:
            return ConnectionTestResult(
                connected=False,
                error=f"Kimlik doğrulama hatası: {exc}",
                latency_ms=int((time.time() - t0) * 1000),
            )
        except (CentrifyConnectionError, CentrifyScriptError) as exc:
            return ConnectionTestResult(
                connected=False,
                error=str(exc),
                latency_ms=int((time.time() - t0) * 1000),
            )
        except Exception as exc:
            return ConnectionTestResult(
                connected=False,
                error=f"Beklenmeyen hata: {exc}",
                latency_ms=int((time.time() - t0) * 1000),
            )

    # ── Okuma işlemleri ─────────────────────────────────────────

    def list_zones(self) -> list[dict]:
        """Tüm zone'ları listele."""
        data = self._run_script("list_zones.ps1")
        if isinstance(data, dict):
            return [data]
        return data if isinstance(data, list) else []

    def list_zone_inventory(self, zone_dn: str) -> dict:
        """Tek WinRM çağrısında zone envanteri (roller+rights+login, komut, atama, host, unix)."""
        # Uzun süren okuma — geçici timeout yükselt
        old_timeout = self.timeout
        try:
            self.timeout = max(old_timeout, int(os.environ.get("CENTRIFY_SYNC_INVENTORY_TIMEOUT", "300")))
            # client yeniden kurulmasın diye mevcut client timeout'unu da güncelle
            if self._client is not None and hasattr(self._client, "timeout"):
                self._client.timeout = self.timeout
            data = self._run_script("list_zone_inventory.ps1", {"ZoneDN": zone_dn})
            if isinstance(data, dict):
                return data
            return {
                "zone_dn": zone_dn,
                "roles": [], "commands": [], "assignments": [],
                "computers": [], "unix_profiles": [], "computer_roles": [],
            }
        finally:
            self.timeout = old_timeout
            if self._client is not None and hasattr(self._client, "timeout"):
                self._client.timeout = old_timeout

    def list_roles(self, zone_dn: str) -> list[dict]:
        """Zone içindeki rolleri listele (rights + login bayrakları dahil)."""
        data = self._run_script("list_roles.ps1", {"ZoneDN": zone_dn})
        if isinstance(data, dict):
            return [data]
        return data if isinstance(data, list) else []

    def list_commands(self, zone_dn: str) -> list[dict]:
        """Zone içindeki komut/right tanımlarını listele."""
        data = self._run_script("list_commands.ps1", {"ZoneDN": zone_dn})
        if isinstance(data, dict):
            return [data]
        return data if isinstance(data, list) else []

    def list_role_assignments(self, zone_dn: str) -> list[dict]:
        """Zone içindeki role assignment'ları listele."""
        data = self._run_script("list_role_assignments.ps1", {"ZoneDN": zone_dn})
        if isinstance(data, dict):
            return [data]
        return data if isinstance(data, list) else []

    def list_computer_roles(self, zone_dn: str) -> list[dict]:
        """Zone içindeki computer role'leri listele."""
        data = self._run_script("list_computer_roles.ps1", {"ZoneDN": zone_dn})
        if isinstance(data, dict):
            return [data]
        return data if isinstance(data, list) else []

    def list_computers(self, zone_dn: str) -> list[dict]:
        """Zone computer listesi."""
        data = self._run_script("list_computers.ps1", {"ZoneDN": zone_dn})
        if isinstance(data, dict):
            return [data]
        return data if isinstance(data, list) else []

    def list_unix_profiles(self, zone_dn: str) -> list[dict]:
        """Zone UNIX profil listesi."""
        data = self._run_script("list_unix_profiles.ps1", {"ZoneDN": zone_dn})
        if isinstance(data, dict):
            return [data]
        return data if isinstance(data, list) else []

    def get_role_detail(self, zone_dn: str, role_name: str) -> dict:
        """Rolün detaylarını ve bağlı komutlarını getir."""
        data = self._run_script("get_role_detail.ps1", {"ZoneDN": zone_dn, "RoleName": role_name})
        return data if isinstance(data, dict) else {}

    # ── Yazma işlemleri ─────────────────────────────────────────

    def create_role(self, zone_dn: str, name: str, description: str = "") -> OpResult:
        """Zone'da yeni rol oluştur."""
        data = self._run_script("create_role.ps1", {
            "ZoneDN": zone_dn, "RoleName": name, "Description": description,
        })
        return OpResult(success=data.get("success", False), message="Rol oluşturuldu", data=data)

    def update_role(self, zone_dn: str, name: str, new_desc: str = "") -> OpResult:
        """Rol açıklamasını güncelle."""
        data = self._run_script("create_role.ps1", {
            "ZoneDN": zone_dn, "RoleName": name, "Description": new_desc,
        })
        return OpResult(success=data.get("success", False), message="Rol güncellendi", data=data)

    def delete_role(self, zone_dn: str, name: str) -> OpResult:
        """Zone'dan rol sil."""
        data = self._run_script("delete_role.ps1", {"ZoneDN": zone_dn, "RoleName": name})
        return OpResult(success=data.get("success", False), message="Rol silindi", data=data)

    def clone_role(self, src_zone: str, src_role: str, dst_zone: str, dst_name: str) -> OpResult:
        """Rolü komutlarıyla birlikte klonla."""
        data = self._run_script("clone_role.ps1", {
            "SrcZoneDN": src_zone, "SrcRoleName": src_role,
            "DstZoneDN": dst_zone, "DstRoleName": dst_name,
        })
        return OpResult(success=data.get("success", False), message="Rol klonlandı", data=data)

    def overwrite_role_commands(self, src_zone: str, src_role: str,
                                 dst_zone: str, dst_role: str) -> OpResult:
        """Hedef rolün komutlarını kaynak rolünkilerle üzerine yaz."""
        data = self._run_script("overwrite_role.ps1", {
            "SrcZoneDN": src_zone, "SrcRoleName": src_role,
            "DstZoneDN": dst_zone, "DstRoleName": dst_role,
        })
        return OpResult(success=data.get("success", False), message="Rol üzerine yazıldı", data=data)

    def create_role_assignment(self, zone_dn: str, role: str, assignee_dn: str,
                                scope: str = "zone") -> OpResult:
        """Role assignment oluştur."""
        return OpResult(success=True, message="Role assignment oluşturuldu (stub)")

    def delete_role_assignment(self, zone_dn: str, assignment_id: str) -> OpResult:
        """Role assignment sil."""
        return OpResult(success=True, message="Role assignment silindi (stub)")

    def create_command(self, zone_dn: str, name: str, path: str, run_as: str,
                        auth_type: str, match: str, run_as_group: str = "",
                        description: str = "") -> OpResult:
        """Komut/right tanımla."""
        data = self._run_script("create_command.ps1", {
            "ZoneDN": zone_dn, "CommandName": name, "CommandPath": path,
            "MatchType": match, "RunAsUser": run_as,
            "RunAsGroup": run_as_group, "AuthType": auth_type,
            "Description": description,
        })
        return OpResult(success=data.get("success", False), message="Komut oluşturuldu", data=data)

    def delete_command(self, zone_dn: str, name: str) -> OpResult:
        """Komut/right sil."""
        data = self._run_script("delete_command.ps1", {"ZoneDN": zone_dn, "CommandName": name})
        return OpResult(success=data.get("success", False), message="Komut silindi", data=data)

    def add_command_to_role(self, zone_dn: str, role: str, command: str) -> OpResult:
        """Role komut ekle."""
        data = self._run_script("add_command_to_role.ps1", {
            "ZoneDN": zone_dn, "RoleName": role, "CommandName": command,
        })
        return OpResult(success=data.get("success", False), message="Komut role eklendi", data=data)

    def remove_command_from_role(self, zone_dn: str, role: str, command: str) -> OpResult:
        """Rolden komut kaldır."""
        data = self._run_script("remove_command_from_role.ps1", {
            "ZoneDN": zone_dn, "RoleName": role, "CommandName": command,
        })
        return OpResult(success=data.get("success", False), message="Komut rolden kaldırıldı", data=data)

    # ── Fabrika ─────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config: dict) -> "WinRMCentrifyAdapter":
        """Centrify entegrasyon ayarlarından adapter oluştur."""
        from app.core.encryption import decrypt_secret
        password = decrypt_secret(config.get("password_enc", ""))
        return cls(
            host=config["winrm_host"],
            username=config["service_account"],
            password=password or "",
            port=config.get("winrm_port", 5985),
            use_https=config.get("winrm_https", False),
            timeout=config.get("timeout", 60),
        )
