from typing import Optional

from pydantic import BaseModel, Field


class PublicSettings(BaseModel):
    app_name: str
    version: str
    sso_enabled: bool = False
    ad_enabled: bool = False
    sso_mode: str = "kerberos"
    assistant_enabled: bool = False


class AdminSettings(BaseModel):
    app_name: str
    version: str
    automation_username: str
    automation_user_kind: str = "root"  # root | local | ad
    automation_password_set: bool = False
    # Web terminal for Admin uses root (credential asked or stored later)
    admin_terminal_user: str = "root"
    smtp_host: str = ""
    smtp_test_mail: str = ""
    assistant_enabled: bool = False
    assistant_ollama_mode: str = "direct"
    assistant_gateway_url: str = ""
    assistant_gateway_api_key_set: bool = False
    assistant_direct_host: str = ""
    assistant_direct_port: int = 11434
    assistant_model: str = ""


class AdminSettingsUpdate(BaseModel):
    app_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    automation_username: Optional[str] = Field(default=None, min_length=1, max_length=128)
    automation_user_kind: Optional[str] = Field(default=None, max_length=16)
    automation_password: Optional[str] = Field(default=None, min_length=1, max_length=512)
    smtp_host: Optional[str] = Field(default=None, max_length=255)
    smtp_test_mail: Optional[str] = Field(default=None, max_length=320)
    assistant_enabled: Optional[bool] = None
    assistant_ollama_mode: Optional[str] = Field(default=None, max_length=16)
    assistant_gateway_url: Optional[str] = Field(default=None, max_length=512)
    assistant_gateway_api_key: Optional[str] = Field(default=None, max_length=1024)
    assistant_direct_host: Optional[str] = Field(default=None, max_length=255)
    assistant_direct_port: Optional[int] = Field(default=None, ge=1, le=65535)
    assistant_model: Optional[str] = Field(default=None, max_length=128)


class MailSettingsPublic(BaseModel):
    """Operatörlerin Mail Config ekranında görmesi için (gizli bilgi yok)."""

    smtp_host: str = ""
    smtp_test_mail: str = ""


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=6, max_length=256)