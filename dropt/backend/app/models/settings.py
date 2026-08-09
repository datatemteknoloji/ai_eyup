from typing import Optional

from sqlmodel import Field, SQLModel


class AppSetting(SQLModel, table=True):
    __tablename__ = "app_settings"

    key: str = Field(primary_key=True, max_length=128)
    value: str = Field(default="", max_length=2048)


APP_NAME_KEY = "app_name"
AUTOMATION_USERNAME_KEY = "automation_username"
AUTOMATION_USER_KIND_KEY = "automation_user_kind"
AUTOMATION_PASSWORD_KEY = "automation_password"
SMTP_HOST_KEY = "smtp_host"
SMTP_TEST_MAIL_KEY = "smtp_test_mail"

ASSISTANT_ENABLED_KEY = "assistant_enabled"
ASSISTANT_OLLAMA_MODE_KEY = "assistant_ollama_mode"
ASSISTANT_GATEWAY_URL_KEY = "assistant_gateway_url"
ASSISTANT_GATEWAY_API_KEY = "assistant_gateway_api_key"
ASSISTANT_DIRECT_HOST_KEY = "assistant_direct_host"
ASSISTANT_DIRECT_PORT_KEY = "assistant_direct_port"
ASSISTANT_MODEL_KEY = "assistant_model"
