"""Ainew frontend HTTPS sertifikaları — DATA_DIR/certs/server.{crt,key}."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def certs_dir() -> Path:
    # Container içi bind: /app/certs → host ${DATA_DIR}/certs
    # DATA_DIR host yolu olabilir; container'da /app/certs tercih edilir.
    env = (os.environ.get("AINEW_CERTS_DIR") or "").strip()
    if env:
        return Path(env)
    app_certs = Path("/app/certs")
    if app_certs.is_dir() or os.access("/app", os.W_OK):
        return app_certs
    data = (os.environ.get("AINEW_DATA_DIR") or os.environ.get("DATA_DIR") or "").strip()
    if data:
        return Path(data) / "certs"
    return app_certs


def _paths() -> tuple[Path, Path, Path]:
    root = certs_dir()
    return root / "server.crt", root / "server.key", root / "tls.meta.json"


def _write_meta(data: dict) -> None:
    _, _, meta = _paths()
    try:
        meta.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def _read_meta() -> dict:
    _, _, meta = _paths()
    if not meta.is_file():
        return {}
    try:
        return json.loads(meta.read_text(encoding="utf-8"))
    except Exception:
        return {}


def generate_self_signed(*, days: int = 3650, cn: str | None = None) -> dict[str, Any]:
    root = certs_dir()
    root.mkdir(parents=True, exist_ok=True)
    crt_path, key_path, _ = _paths()
    cn = (cn or os.environ.get("PRIMARY_IP") or "localhost").strip() or "localhost"

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "TR"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ServerManagement"),
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
        ]
    )
    now = datetime.now(UTC)
    san: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.DNSName(cn) if not _looks_like_ip(cn) else x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ]
    if _looks_like_ip(cn):
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(cn)))
        except ValueError:
            pass
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    crt_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    try:
        os.chmod(key_path, 0o600)
        os.chmod(crt_path, 0o644)
    except OSError:
        pass
    _write_meta({"source": "self-signed", "generated_at": now.isoformat(), "cn": cn})
    return status()


def _looks_like_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def _load_cert(pem: bytes) -> x509.Certificate:
    return x509.load_pem_x509_certificate(pem)


def _load_key(pem: bytes):
    return serialization.load_pem_private_key(pem, password=None)


def _public_der(pub) -> bytes:
    return pub.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def install_uploaded(*, cert_pem: str, key_pem: str, chain_pem: str = "") -> dict[str, Any]:
    cert_raw = cert_pem.strip().encode("utf-8")
    key_raw = key_pem.strip().encode("utf-8")
    if chain_pem.strip():
        cert_raw = cert_raw + b"\n" + chain_pem.strip().encode("utf-8")

    try:
        leaf = cert_raw.split(b"-----END CERTIFICATE-----")[0] + b"-----END CERTIFICATE-----\n"
        cert = _load_cert(leaf)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Geçersiz sertifika: {exc}") from exc
    try:
        key = _load_key(key_raw)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Geçersiz private key: {exc}") from exc

    if _public_der(key.public_key()) != _public_der(cert.public_key()):
        raise ValueError("Sertifika ve private key eşleşmiyor")

    root = certs_dir()
    root.mkdir(parents=True, exist_ok=True)
    crt_path, key_path, _ = _paths()
    crt_path.write_bytes(cert_raw if cert_raw.endswith(b"\n") else cert_raw + b"\n")
    key_path.write_bytes(key_raw if key_raw.endswith(b"\n") else key_raw + b"\n")
    try:
        os.chmod(key_path, 0o600)
        os.chmod(crt_path, 0o644)
    except OSError:
        pass
    _write_meta(
        {
            "source": "uploaded",
            "uploaded_at": datetime.now(UTC).isoformat(),
            "subject": cert.subject.rfc4514_string(),
        }
    )
    return status()


def status() -> dict[str, Any]:
    crt_path, key_path, _ = _paths()
    out: dict[str, Any] = {
        "certs_dir": str(certs_dir()),
        "cert_present": crt_path.is_file(),
        "key_present": key_path.is_file(),
        "source": _read_meta().get("source", "unknown"),
        "subject": None,
        "not_after": None,
        "fingerprint_sha256": None,
        "https_port": 443,
        "writable": os.access(certs_dir(), os.W_OK) if certs_dir().exists() else False,
    }
    if not crt_path.is_file():
        return out
    try:
        pem = crt_path.read_bytes()
        leaf = pem.split(b"-----END CERTIFICATE-----")[0] + b"-----END CERTIFICATE-----\n"
        cert = _load_cert(leaf)
        out["subject"] = cert.subject.rfc4514_string()
        na = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after
        out["not_after"] = na.isoformat() if hasattr(na, "isoformat") else str(na)
        fp = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
        out["fingerprint_sha256"] = ":".join(fp[i : i + 2] for i in range(0, len(fp), 2))
        meta = _read_meta()
        if meta.get("source"):
            out["source"] = meta["source"]
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)[:200]
    return out


def reload_frontend_nginx() -> dict[str, Any]:
    """frontend container içinde nginx -s reload (Docker Engine API)."""
    import httpx

    sock = os.environ.get("DOCKER_SOCK") or "/var/run/docker.sock"
    name_hint = (os.environ.get("FRONTEND_CONTAINER_NAME") or "server_management_frontend").strip()
    last_err = ""
    try:
        transport = httpx.HTTPTransport(uds=sock)
        with httpx.Client(transport=transport, base_url="http://docker", timeout=20.0) as client:
            resp = client.get("/containers/json", params={"all": "false"})
            resp.raise_for_status()
            containers = resp.json()
            target = None
            for c in containers:
                names = [n.lstrip("/") for n in (c.get("Names") or [])]
                if name_hint in names or any(name_hint in n for n in names):
                    target = c["Id"]
                    break
                labels = c.get("Labels") or {}
                if "frontend" in (labels.get("com.docker.compose.service") or ""):
                    target = c["Id"]
            if not target and containers:
                for c in containers:
                    names = " ".join(c.get("Names") or []).lower()
                    if "frontend" in names:
                        target = c["Id"]
                        break
            if not target:
                return {"ok": False, "error": "Frontend container bulunamadı"}
            exec_body = {
                "AttachStdout": True,
                "AttachStderr": True,
                "Cmd": ["nginx", "-s", "reload"],
            }
            ex = client.post(f"/containers/{target}/exec", json=exec_body)
            ex.raise_for_status()
            exec_id = ex.json()["Id"]
            start = client.post(f"/exec/{exec_id}/start", json={"Detach": False, "Tty": False})
            start.raise_for_status()
            return {"ok": True, "container": name_hint, "detail": "nginx reload gönderildi"}
    except Exception as exc:  # noqa: BLE001
        last_err = str(exc)
        return {
            "ok": False,
            "error": last_err[:300],
            "hint": "Sertifika yazıldı; gerekirse: docker compose restart frontend",
        }
