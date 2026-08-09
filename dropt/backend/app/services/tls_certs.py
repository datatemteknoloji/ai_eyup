"""TLS certificate management on app install-dir volume (./certs)."""

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
    raw = (os.environ.get("PORTAL_CERTS_DIR") or "").strip()
    if raw:
        return Path(raw)
    return Path("/certs")


def _paths() -> tuple[Path, Path, Path, Path]:
    root = certs_dir()
    return root / "tls.crt", root / "tls.key", root / "https.enabled", root / "meta.json"


def https_enabled() -> bool:
    _, _, flag, _ = _paths()
    if not flag.is_file():
        return True
    return flag.read_text(encoding="utf-8").strip().lower() in {"1", "true", "yes", "on"}


def set_https_enabled(enabled: bool) -> None:
    root = certs_dir()
    root.mkdir(parents=True, exist_ok=True)
    _, _, flag, _ = _paths()
    flag.write_text("1\n" if enabled else "0\n", encoding="utf-8")


def _write_meta(meta: dict[str, Any]) -> None:
    _, _, _, meta_path = _paths()
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _read_meta() -> dict[str, Any]:
    _, _, _, meta_path = _paths()
    if not meta_path.is_file():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def generate_self_signed(*, days: int = 825, cn: str = "dropt.local") -> dict[str, Any]:
    root = certs_dir()
    root.mkdir(parents=True, exist_ok=True)
    crt_path, key_path, flag, _ = _paths()

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "TR"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "DrOPT Portal"),
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
        ]
    )
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=days))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.DNSName(cn),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
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
    if not flag.is_file():
        set_https_enabled(True)
    return status()


def _load_cert(pem: bytes) -> x509.Certificate:
    return x509.load_pem_x509_certificate(pem)


def _load_key(pem: bytes):
    return serialization.load_pem_private_key(pem, password=None)


def _public_der(key_or_cert_pub) -> bytes:
    return key_or_cert_pub.public_bytes(
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
    crt_path, key_path, _, _ = _paths()
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


def ensure_certs() -> None:
    crt, key, flag, _ = _paths()
    try:
        root = certs_dir()
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    if not crt.is_file() or not key.is_file():
        generate_self_signed()
    if not flag.is_file():
        set_https_enabled(True)


def status() -> dict[str, Any]:
    crt_path, key_path, _, _ = _paths()
    out: dict[str, Any] = {
        "https_enabled": https_enabled(),
        "certs_dir": str(certs_dir()),
        "cert_present": crt_path.is_file(),
        "key_present": key_path.is_file(),
        "source": _read_meta().get("source", "unknown"),
        "subject": None,
        "not_after": None,
        "fingerprint_sha256": None,
        "http_port": int(os.environ.get("DROPT_UI_HTTP_PORT") or 3000),
        "https_port": int(os.environ.get("DROPT_UI_HTTPS_PORT") or 443),
    }
    if not crt_path.is_file():
        return out
    try:
        pem = crt_path.read_bytes()
        leaf = pem.split(b"-----END CERTIFICATE-----")[0] + b"-----END CERTIFICATE-----\n"
        cert = _load_cert(leaf)
        out["subject"] = cert.subject.rfc4514_string()
        na = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after
        out["not_after"] = na.isoformat()
        fp = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
        out["fingerprint_sha256"] = ":".join(fp[i : i + 2] for i in range(0, len(fp), 2))
        meta = _read_meta()
        if meta.get("source"):
            out["source"] = meta["source"]
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)[:200]
    return out


def reload_frontend_nginx() -> dict[str, Any]:
    """Regenerate nginx conf + reload via Docker Engine API (unix socket)."""
    import httpx

    sock = os.environ.get("DOCKER_SOCK") or "/var/run/docker.sock"
    name_hint = (os.environ.get("FRONTEND_CONTAINER_NAME") or "").strip()
    last_err = ""
    script = (
        "CERT_DIR=/etc/nginx/certs; TEMPLATE=/etc/nginx/nginx.conf.template; "
        "OUT=/etc/nginx/conf.d/default.conf; "
        'HTTPS_ENABLED=$(tr -d "[:space:]" <"$CERT_DIR/https.enabled" 2>/dev/null || echo 1); '
        'if [ "$HTTPS_ENABLED" != "1" ] && [ "$HTTPS_ENABLED" != "true" ] && [ "$HTTPS_ENABLED" != "yes" ]; then '
        "awk '/#__HTTPS_BLOCK_START__/{skip=1;next}/#__HTTPS_BLOCK_END__/{skip=0;next}!skip{print}' "
        '"$TEMPLATE" >"$OUT"; else '
        "sed -e '/#__HTTPS_BLOCK_START__/d' -e '/#__HTTPS_BLOCK_END__/d' \"$TEMPLATE\" >\"$OUT\"; fi; "
        "nginx -t && nginx -s reload"
    )
    try:
        transport = httpx.HTTPTransport(uds=sock)
        with httpx.Client(transport=transport, base_url="http://docker", timeout=20.0) as client:
            resp = client.get("/containers/json", params={"all": "false"})
            resp.raise_for_status()
            containers = resp.json()
            target = None
            for c in containers:
                names = c.get("Names") or []
                joined = " ".join(names)
                image = c.get("Image") or ""
                if name_hint and name_hint in joined:
                    target = c["Id"]
                    break
                if "frontend" in joined.lower() or "frontend" in image.lower():
                    target = c["Id"]
            if not target:
                return {"ok": False, "detail": "frontend container bulunamadı"}
            create = client.post(
                f"/containers/{target}/exec",
                json={
                    "AttachStdout": True,
                    "AttachStderr": True,
                    "Cmd": ["sh", "-c", script],
                },
            )
            create.raise_for_status()
            exec_id = create.json()["Id"]
            start = client.post(f"/exec/{exec_id}/start", json={"Detach": False, "Tty": False})
            insp = client.get(f"/exec/{exec_id}/json")
            code = (insp.json() or {}).get("ExitCode", 1) if insp.status_code == 200 else 1
            if code == 0:
                return {"ok": True, "container": target[:12], "method": "docker_api_exec"}
            last_err = f"nginx reload exit={code} output={(start.text or '')[:300]}"
    except Exception as exc:  # noqa: BLE001
        last_err = str(exc)[:400]

    return {
        "ok": False,
        "detail": last_err or "frontend nginx reload başarısız — frontend’i yeniden başlatın",
    }
