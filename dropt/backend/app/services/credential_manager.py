from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class CredentialCryptoError(Exception):
    pass


class CredentialManager:
    """Encrypt/decrypt automation secrets with Fernet (AES-128-CBC + HMAC). Never log plaintext."""

    def __init__(self, key: str | None = None) -> None:
        raw = (key if key is not None else get_settings().fernet_key).strip()
        try:
            self._fernet = Fernet(raw.encode("utf-8") if isinstance(raw, str) else raw)
        except Exception as exc:
            raise CredentialCryptoError(
                "FERNET_KEY geçersiz. Geçerli bir Fernet anahtarı kullanın."
            ) from exc

    def encrypt(self, plaintext: str) -> str:
        if plaintext is None:
            raise CredentialCryptoError("Şifrelenecek veri boş olamaz")
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise CredentialCryptoError("Kimlik bilgisi çözülemedi") from exc

    def encrypt_optional(self, plaintext: str | None) -> str | None:
        if plaintext is None or plaintext.strip() == "":
            return None
        return self.encrypt(plaintext)

    def decrypt_optional(self, token: str | None) -> str | None:
        if not token:
            return None
        return self.decrypt(token)
