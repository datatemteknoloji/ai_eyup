"""
Sistem Güncelleme Servisi - SSH tabanlı check/apply
"""
import io, time, logging, paramiko
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _get_management_ip() -> str:
    """
    Yönetim sunucusunun client'lardan erişilebilir IP adresini döner.
    Öncelik:
    1. MANAGEMENT_SERVER_IP ortam değişkeni / config
    2. Varsayılan ağ arayüzünden otomatik tespit (8.8.8.8'e bağlanarak)
    3. Fallback: 127.0.0.1
    """
    import socket
    from app.core.config import settings
    if settings.MANAGEMENT_SERVER_IP:
        return settings.MANAGEMENT_SERVER_IP
    # Dış ağa bağlanıyormuş gibi yaparak yerel IP'yi bul
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _resolve_creds(server, global_cred=None,
                   override_username=None, override_password=None,
                   override_sudo_password=None) -> dict:
    """
    Kimlik bilgisi önceliği:
    1. Plan'daki override (yetkili kullanıcı adımında girildi)
    2. Server'ın connection_config
    3. Global credential
    """
    cfg = server.connection_config or {}
    base_username = cfg.get("username") or (global_cred.username if global_cred else "root") or "root"
    base_password = cfg.get("password") or (global_cred.password if global_cred else None)
    base_key      = cfg.get("private_key") or (global_cred.private_key if global_cred else None)
    base_sudo     = cfg.get("sudo_password") or (global_cred.sudo_password if global_cred else None)

    # Override geçerliyse kullan
    username = override_username or base_username
    password = override_password or base_password
    # sudo password: override varsa onu kullan, yoksa override_password (kullanıcı şifresiyle sudo olabilir)
    sudo_pw  = override_sudo_password or (override_password if override_username else base_sudo) or base_password

    return {
        "host":          server.ip_address,
        "port":          int(cfg.get("port") or (global_cred.port if global_cred else 22) or 22),
        "username":      username,
        "password":      password,
        "private_key":   None if override_username else base_key,  # override varsa key kullanma
        "sudo_password": sudo_pw,
    }


def _make_client(creds: dict) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = None
    if creds.get("private_key"):
        for cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                pkey = cls.from_private_key(io.StringIO(creds["private_key"])); break
            except Exception:
                pass
    connected = False
    if pkey:
        try:
            client.connect(creds["host"], port=creds["port"], username=creds["username"],
                           pkey=pkey, timeout=10, allow_agent=False, look_for_keys=False)
            connected = True
        except Exception:
            pass
    if not connected and creds.get("password"):
        client.connect(creds["host"], port=creds["port"], username=creds["username"],
                       password=creds["password"], timeout=10, allow_agent=False, look_for_keys=False)
    return client


def _run(client, cmd, sudo_pass=None, timeout=600, priv_method="sudo"):
    """
    Komutu yetki yükseltme yöntemiyle çalıştırır.
    priv_method: sudo | dzdo | su | pbrun | direct
    """
    # PTY ile channel aç — sudo şifre prompt'unu doğru handle eder
    use_pty   = bool(sudo_pass and priv_method in ("sudo", "dzdo", "su"))
    tool_map  = {"sudo": "sudo", "dzdo": "dzdo", "su": "su", "pbrun": "pbrun"}
    tool      = tool_map.get(priv_method, "sudo")

    if priv_method == "direct":
        final_cmd = cmd
    elif priv_method in ("sudo", "dzdo"):
        if sudo_pass:
            # -S: şifreyi stdin'den oku, -k: cache sıfırla
            esc = cmd.replace("'", "'\\''")
            final_cmd = f"{tool} -k -S sh -c '{esc}'"
        else:
            final_cmd = f"{tool} -n sh -c '{cmd.replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'"
    elif priv_method == "su":
        if sudo_pass:
            esc = cmd.replace("'", "'\\''")
            final_cmd = f"su -c '{esc}' root"
        else:
            final_cmd = f"su -c '{cmd}' root"
    elif priv_method == "pbrun":
        final_cmd = f"pbrun sh -c '{cmd}'"
    else:
        final_cmd = cmd

    channel = client.get_transport().open_session()
    if use_pty:
        channel.get_pty(term="xterm", width=220, height=50)
    channel.exec_command(final_cmd)

    # Sudo şifresini stdin'e yaz
    if sudo_pass and priv_method in ("sudo", "dzdo"):
        try:
            channel.sendall((sudo_pass + "\n").encode())
        except Exception:
            pass

    # Timeout ile oku
    import select, time
    out_buf = b""
    err_buf = b""
    deadline = time.time() + timeout
    channel.setblocking(False)

    while True:
        if time.time() > deadline:
            channel.close()
            return 124, out_buf.decode("utf-8", errors="replace"), "TIMEOUT"
        if channel.exit_status_ready():
            # Son verileri oku
            while channel.recv_ready():
                out_buf += channel.recv(65536)
            while channel.recv_stderr_ready():
                err_buf += channel.recv_stderr(65536)
            break
        r, _, _ = select.select([channel], [], [], 0.5)
        if r:
            if channel.recv_ready():
                out_buf += channel.recv(65536)
            if channel.recv_stderr_ready():
                err_buf += channel.recv_stderr(65536)

    code = channel.recv_exit_status()
    channel.close()
    return code, out_buf.decode("utf-8", errors="replace"), err_buf.decode("utf-8", errors="replace")


def _run_streaming(client, cmd: str, sudo_pass=None, timeout=1800,
                    priv_method="sudo", on_line=None) -> tuple[int, str]:
    """
    Komutu çalıştırır ve çıktıyı satır satır on_line callback'e iletir.
    PTY kullanarak sudo şifresini handle eder.
    Döner: (exit_code, full_output)
    """
    import select, time as _time, re as _re

    # Komutu wrap et
    if priv_method in ("sudo", "dzdo") and sudo_pass:
        tool = priv_method
        safe_cmd = cmd.replace("'", "'\"'\"'")
        final_cmd = f"{tool} -k -S sh -c '{safe_cmd}'"
    elif priv_method == "direct":
        final_cmd = cmd
    else:
        final_cmd = cmd

    channel = client.get_transport().open_session()
    channel.get_pty(term="xterm-256color", width=220, height=50)
    channel.exec_command(final_cmd)

    # sudo şifresi gönder
    if sudo_pass and priv_method in ("sudo", "dzdo"):
        try:
            channel.sendall((sudo_pass + "\n").encode())
        except Exception:
            pass

    out_buf = b""
    line_buf = b""
    deadline = _time.time() + timeout
    channel.setblocking(False)
    ansi_escape = _re.compile(rb'\x1b\[[0-9;]*[a-zA-Z]|\x1b\([a-zA-Z]|\x1b[=>]|\r')

    while True:
        if _time.time() > deadline:
            channel.close()
            return 124, out_buf.decode("utf-8", errors="replace")

        if channel.exit_status_ready():
            # Son verileri oku
            while channel.recv_ready():
                data = channel.recv(65536)
                out_buf += data
                line_buf += data
            break

        r, _, _ = select.select([channel], [], [], 0.2)
        if r and channel.recv_ready():
            data = channel.recv(4096)
            if data:
                out_buf  += data
                line_buf += data
                # Satır satır işle
                while b'\n' in line_buf:
                    line, line_buf = line_buf.split(b'\n', 1)
                    clean = ansi_escape.sub(b'', line).decode("utf-8", errors="replace").strip()
                    if clean and on_line:
                        # Gürültülü satırları filtrele
                        low = clean.lower()
                        skip = any(low.startswith(s) for s in (
                            "[sudo]", "sudo:", "datatem", "updating subscription",
                        ))
                        if not skip:
                            on_line(clean)

    code = channel.recv_exit_status()
    channel.close()
    return code, out_buf.decode("utf-8", errors="replace")


def _detect_pkg_manager(client) -> str:
    """Paket yöneticisini tespit eder — sudo olmadan direkt exec."""
    _, stdout, _ = client.exec_command(
        "command -v dnf && echo DNF || command -v yum && echo YUM || command -v apt-get && echo APT || echo UNKNOWN",
        timeout=8, get_pty=False
    )
    out = stdout.read().decode("utf-8", errors="replace")
    stdout.channel.recv_exit_status()
    if "DNF" in out or "/dnf" in out:
        return "dnf"
    if "YUM" in out or "/yum" in out:
        return "yum"
    if "APT" in out or "/apt" in out:
        return "apt"
    return "unknown"


def check_available_updates(
    server,
    update_type: str,
    global_cred=None,
    repo_file_content: Optional[str] = None,
    repo_name: Optional[str] = None,
    override_username: Optional[str] = None,
    override_password: Optional[str] = None,
    override_sudo_password: Optional[str] = None,
    priv_method: str = "sudo",
) -> List[Dict]:
    """
    Güncellemeleri kontrol eder.
    check-update / apt list --upgradable sudo gerektirmez — normal kullanıcı çalıştırabilir.
    Sadece metadata refresh (makecache/apt update) gerekebilir.
    """
    creds = _resolve_creds(
        server,
        global_cred,
        override_username=override_username,
        override_password=override_password,
        override_sudo_password=override_sudo_password,
    )
    sudo  = creds.get("sudo_password")
    try:
        client = _make_client(creds)
        mgr    = _detect_pkg_manager(client)
        result = []
        tmp_repo_file = None

        if mgr in ("dnf", "yum"):
            repo_opts = ""
            # /tmp altında geçici reposdir kullan — sudo gerektirmez
            tmp_reposdir = None
            if repo_file_content and repo_name:
                tmp_reposdir = f"/tmp/ainew-check-{repo_name}"
                esc = repo_file_content.replace("'", "'\\''")
                _run(client, f"mkdir -p {tmp_reposdir} && echo '{esc}' > {tmp_reposdir}/{repo_name}.repo", timeout=10)
                tmp_repo_file = tmp_reposdir  # temizlik için
                # Sadece bu temp reposdir'i kullan; RHSM/diğer repoları devre dışı bırak
                repo_opts = f"--setopt=reposdir={tmp_reposdir}"
                base_opts = f"--color=never --disableplugin=subscription-manager --setopt=timeout=15 --setopt=retries=2"
            else:
                # Local repo seçilmedi: RHSM repolarını olduğu gibi kullan
                # subscription-manager plugin'i ETKİN bırak — RHSM repoları cert ile çalışır
                base_opts = "--color=never --setopt=timeout=20 --setopt=retries=2"

            # makecache — sudo gerekmez, başarısız olursa atla
            _run(client, f"{mgr} makecache -q {repo_opts} 2>/dev/null || true",
                 timeout=60, priv_method="direct")

            if update_type == "security":
                cmd = f"{mgr} check-update --security {base_opts} {repo_opts} 2>&1; true"
            elif update_type == "kernel":
                cmd = f"{mgr} check-update 'kernel*' {base_opts} {repo_opts} 2>&1; true"
            else:
                cmd = f"{mgr} list upgrades {base_opts} {repo_opts} 2>&1; true"

            code, out, _ = _run(client, cmd, timeout=120, priv_method="direct")

            if update_type == "security":
                result = _parse_dnf_check_update(out, is_security=True)
            elif update_type == "kernel":
                result = _parse_dnf_check_update(out, kernel_only=True)
            else:
                # dnf list upgrades çıktısı: "paket.arch  versiyon  repo"
                result = _parse_dnf_list_upgrades(out)

        elif mgr == "apt":
            if repo_file_content and repo_name:
                # /tmp altına yaz — sudo gerektirmez
                tmp_repo_file = f"/tmp/ainew-check-{repo_name}"
                esc = repo_file_content.replace("'", "'\\''")
                _run(client, f"mkdir -p {tmp_repo_file} && echo '{esc}' > {tmp_repo_file}/sources.list", timeout=10)
                _run(client, f"apt-get update -qq -o Dir::Etc::sourcelist={tmp_repo_file}/sources.list -o Dir::Etc::sourceparts=- 2>/dev/null", sudo_pass=sudo, timeout=60, priv_method=priv_method)
            else:
                _run(client, "apt-get update -qq 2>/dev/null", sudo_pass=sudo, timeout=60, priv_method=priv_method)
            _, stdout2, _ = client.exec_command(
                "apt list --upgradable 2>/dev/null | tail -n +2", timeout=30, get_pty=False
            )
            out2 = stdout2.read().decode("utf-8", errors="replace")
            stdout2.channel.recv_exit_status()
            result = _parse_apt_upgradable(out2, update_type)

        if tmp_repo_file:
            try:
                # tmp_repo_file artık /tmp/ainew-check-<name> dizini — rm -rf ile sil
                _run(client, f"rm -rf {tmp_repo_file}", timeout=10)
            except Exception:
                pass
        client.close()
        return result
    except Exception as exc:
        return [{"name": "ERROR", "error": str(exc), "is_security": False, "is_kernel": False}]


def _strip_ansi(text: str) -> str:
    """ANSI escape kodlarını temizler."""
    import re
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\([a-zA-Z]|\x1b[=>]', '', text)


def _parse_dnf_check_update(output, is_security=False, kernel_only=False):
    """dnf check-update çıktısını parse eder. ANSI kodları ve gürültülü satırları filtreler."""
    output = _strip_ansi(output)
    SKIP_PREFIXES = (
        "last metadata", "loading", "loaded", "obsoleting",
        "updating subscription", "red hat subscription", "subscription",
        "extra packages", "enabling ", "disabling", "importing",
        "[sudo]", "sudo:", "password", "warning:", "error:",
        "repolist:", "repo id", "---",
    )
    pkgs = []
    for line in output.splitlines():
        line = line.strip().replace("\r", "")
        if not line:
            continue
        low = line.lower()
        if any(low.startswith(p) for p in SKIP_PREFIXES):
            continue
        if any(x in low for x in ["metadata expiration", "loaded plugins", "no packages",
                                    "security", "notice:", "problem ", "curl error",
                                    "mirror", " obsolete", "packages excluded"]):
            continue
        parts = line.split()
        # dnf check-update çıktısı: "paket.arch  yeni_versiyon  repo"
        if len(parts) >= 2 and "." in parts[0] and not parts[0].startswith("."):
            name = parts[0].rsplit(".", 1)[0]
            if not name or len(name) < 2:
                continue
            is_kern = "kernel" in name.lower()
            if kernel_only and not is_kern:
                continue
            pkgs.append({
                "name":        name,
                "new_version": parts[1] if len(parts) > 1 else "",
                "repo":        parts[2] if len(parts) > 2 else "",
                "is_security": is_security,
                "is_kernel":   is_kern,
            })
    return pkgs


def _parse_dnf_list_upgrades(output: str) -> list:
    """
    `dnf list upgrades` çıktısını parse eder.
    Format: "paket.arch   versiyon   repo"
    Başlık satırları: "Upgraded packages:", "Last metadata..."
    """
    output = _strip_ansi(output)
    pkgs = []
    seen = set()
    SKIP = ("last metadata", "upgraded", "available", "installed", "loading",
            "updating subscription", "subscription", "[sudo]", "sudo:", "datatem")
    for line in output.splitlines():
        line = line.strip().replace("\r", "")
        if not line:
            continue
        low = line.lower()
        if any(low.startswith(s) for s in SKIP):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        # "NetworkManager.x86_64   1:1.54.0-4.el9_7   rhel-9-...-baseos-rpms"
        if "." not in parts[0]:
            continue
        full_name = parts[0]
        name = full_name.rsplit(".", 1)[0]
        if not name or name in seen:
            continue
        seen.add(name)
        version = parts[1] if len(parts) > 1 else ""
        repo    = parts[2] if len(parts) > 2 else ""
        is_kern = "kernel" in name.lower()
        pkgs.append({
            "name":        name,
            "new_version": version,
            "repo":        repo,
            "is_security": False,
            "is_kernel":   is_kern,
        })
    return pkgs


def _parse_apt_upgradable(output, update_type):
    pkgs = []
    for line in output.splitlines():
        parts = line.strip().split()
        if parts and "/" in parts[0]:
            name = parts[0].split("/")[0]
            is_kern = "linux-image" in name
            pkgs.append({"name": name, "new_version": parts[1] if len(parts) > 1 else "",
                         "is_security": "security" in line.lower(), "is_kernel": is_kern})
    return pkgs


def check_reboot_required(client, mgr) -> bool:
    code, out, _ = _run(client, "needs-restarting -r 2>/dev/null; echo RC:$?", timeout=10)
    if "RC:1" in out:
        return True
    code2, _, _ = _run(client, "test -f /var/run/reboot-required", timeout=5)
    return code2 == 0


def _write_job_log(job_id: int, log_text: str) -> None:
    """Job log'unu DB'ye doğrudan SQL ile yazar — connection overhead minimumda."""
    try:
        from app.core.config import settings
        import psycopg2
        conn = psycopg2.connect(settings.DATABASE_URL)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "UPDATE system_update_jobs SET log = %s WHERE id = %s",
            (log_text[-8000:], job_id)
        )
        cur.close()
        conn.close()
    except Exception as _e:
        logger.debug(f"_write_job_log error: {_e}")


def apply_updates_to_server(server, update_type, global_cred=None,
                             repo_file_content=None, repo_name=None,
                             override_username=None, override_password=None,
                             override_sudo_password=None, priv_method="sudo",
                             custom_packages=None, job_id: int = None,
                             extra_flags: str = ""):
    t0 = time.time()
    creds = _resolve_creds(server, global_cred,
                           override_username, override_password, override_sudo_password)
    sudo = creds.get("sudo_password")
    pm   = priv_method or "sudo"
    log_lines = []

    def log(msg):
        # ANSI kodlarını temizle
        import re as _re
        clean_msg = _re.sub(r'\x1b\[[0-9;?]*[a-zA-Z]|\x1b[=>]|\x08|\r', '', str(msg)).strip()
        if not clean_msg:
            return
        line = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {clean_msg}"
        log_lines.append(line)
        if job_id:
            _write_job_log(job_id, "\n".join(log_lines))

    try:
        client = _make_client(creds); mgr = _detect_pkg_manager(client)
        log(f"Bağlantı: {server.ip_address} ({mgr})")

        tmp_repo_file = None
        if repo_file_content and repo_name:
            tmp_repo_file = f"/etc/yum.repos.d/{repo_name}-update.repo" if mgr != "apt" \
                           else f"/etc/apt/sources.list.d/{repo_name}-update.list"
            escaped = repo_file_content.replace("'", "'\\''")
            _run(client, f"echo '{escaped}' | tee {tmp_repo_file} > /dev/null", sudo_pass=sudo, timeout=10)
            log(f"Geçici repo eklendi: {tmp_repo_file}")
            if mgr in ("dnf", "yum"):
                log("Repo metadata yenileniyor...")
                _run(client,
                     f"{mgr} makecache --disableplugin=subscription-manager -q 2>/dev/null || true",
                     sudo_pass=sudo, timeout=15)
                log("Metadata hazır")
            elif mgr == "apt":
                _run(client, "apt-get update -qq 2>/dev/null", sudo_pass=sudo, timeout=30)

        if mgr in ("dnf", "yum"):
            # Local repo seçildiyse sadece o repodan güncelle
            if repo_name:
                repo_opts = f"--disablerepo='*' --enablerepo='{repo_name}'"
                log(f"Sadece '{repo_name}' reposundan güncelleme yapılacak (diğer repolar devre dışı)")
            else:
                repo_opts = ""
                log("Tüm etkin repolardan güncelleme yapılacak")

            xf = extra_flags.strip()
            if xf:
                log(f"Ek parametreler: {xf}")

            if update_type == "security":
                cmd = f"{mgr} update --security -y {repo_opts} {xf} 2>&1"
            elif update_type == "kernel":
                cmd = f"{mgr} update 'kernel*' -y {repo_opts} {xf} 2>&1"
            elif update_type == "custom" and custom_packages:
                pkg_list = " ".join(custom_packages)
                cmd = f"{mgr} install -y {repo_opts} {xf} {pkg_list} 2>&1"
                log(f"Seçili {len(custom_packages)} paket yüklenecek")
            else:
                cmd = f"{mgr} update -y {repo_opts} {xf} 2>&1"
        elif mgr == "apt":
            if update_type == "security":
                cmd = "DEBIAN_FRONTEND=noninteractive apt-get install -y $(apt-get -s upgrade 2>/dev/null | grep security | awk '{print $2}') 2>&1"
            elif update_type == "kernel":
                cmd = "DEBIAN_FRONTEND=noninteractive apt-get install -y linux-image-generic 2>&1"
            elif update_type == "custom" and custom_packages:
                pkg_list = " ".join(custom_packages)
                cmd = f"DEBIAN_FRONTEND=noninteractive apt-get install -y {pkg_list} 2>&1"
                log(f"Seçili {len(custom_packages)} paket yüklenecek")
            else:
                cmd = "DEBIAN_FRONTEND=noninteractive apt-get upgrade -y 2>&1"
        else:
            raise RuntimeError("Paket yöneticisi bulunamadı")

        log(f"Güncelleme başlatılıyor ({update_type})...")
        # Streaming çalıştırma — her satır anında log'a yazılır
        code, out = _run_streaming(client, cmd, sudo_pass=sudo, timeout=1800,
                                    priv_method=pm, on_line=log)
        if code not in (0, 100):   # dnf exit 100 = updates available (normal)
            log(f"⚠️ exit={code}")
        else:
            log(f"✓ Tamamlandı (exit={code})")

        # Güncellenen paketleri dnf history ile al (en güvenilir yöntem)
        pkgs_updated = []
        if mgr in ("dnf", "yum") and code in (0, 100):
            try:
                # Son dnf işleminin güncellenen paketlerini listele
                _, hist_out, _ = client.exec_command(
                    "dnf history last 2>/dev/null | grep -E 'Upgrade|Install' | head -100",
                    timeout=15, get_pty=False
                )
                hist_text = hist_out.read().decode("utf-8", errors="replace")
                hist_out.channel.recv_exit_status()
                # Alternatif: dnf history info last
                if not hist_text.strip():
                    _, hist_out2, _ = client.exec_command(
                        "dnf history info last 2>/dev/null | grep -E '^ *Upgrade|^ *Install' | awk '{print $2, $3}' | head -100",
                        timeout=15, get_pty=False
                    )
                    hist_text = hist_out2.read().decode("utf-8", errors="replace")
                    hist_out2.channel.recv_exit_status()
                for line in hist_text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    if parts:
                        name = parts[0].rsplit(".", 1)[0] if "." in parts[0] else parts[0]
                        ver  = parts[1] if len(parts) > 1 else ""
                        if name and not name.startswith("#"):
                            pkgs_updated.append({"name": name, "version": ver})
            except Exception:
                pass
        elif mgr == "apt" and code == 0:
            # apt çıktısından "Setting up package" satırları
            for line in _strip_ansi(out).splitlines():
                if line.startswith("Setting up ") or line.startswith("Unpacking "):
                    parts = line.split()
                    if len(parts) >= 2:
                        pkgs_updated.append({"name": parts[1].split(":")[0],
                                              "version": parts[2].strip("()") if len(parts) > 2 else ""})

        # Reboot kontrolü: SADECE başarılı güncelleme sonrası kontrol et
        reboot_req = False
        if code in (0, 100) and pkgs_updated:
            reboot_req = check_reboot_required(client, mgr)
            if reboot_req:
                log("⚠️ Güncelleme tamamlandı — sistem yeniden başlatılması gerekiyor")
        if tmp_repo_file:
            _run(client, f"rm -f {tmp_repo_file}", sudo_pass=sudo, timeout=10)
        client.close()
        return {"status": "success" if code in (0, 100) else "failed", "log": "\n".join(log_lines),
                "packages_updated": pkgs_updated, "reboot_required": reboot_req,
                "duration": round(time.time() - t0, 1)}
    except Exception as exc:
        log(f"HATA: {exc}")
        return {"status": "failed", "log": "\n".join(log_lines), "packages_updated": [],
                "reboot_required": False, "duration": round(time.time() - t0, 1), "error": str(exc)}


def run_system_update_plan(plan_id: int) -> None:
    from app.core.database import ThreadSessionLocal as SessionLocal
    from app.models.system_update import SystemUpdatePlan, SystemUpdateJob
    from app.models.server import Server
    from app.models.credential import GlobalCredential
    from app.models.repository import RepoSource
    from app.services.repo_sync_service import generate_repo_file
    from app.core.config import settings as _cfg
    import socket

    db = SessionLocal()
    try:
        plan = db.query(SystemUpdatePlan).filter_by(id=plan_id).first()
        if not plan:
            return
        plan.status = "running"
        plan.started_at = datetime.now(timezone.utc)
        db.commit()

        global_cred = db.query(GlobalCredential).filter_by(is_default=True).first() \
                      or db.query(GlobalCredential).first()

        repo_file_content = repo_name = None
        if plan.repo_id:
            repo = db.query(RepoSource).filter_by(id=plan.repo_id).first()
            if repo:
                server_ip = _get_management_ip()
                repo_file_content = generate_repo_file(repo, server_ip, 8000)
                repo_name = repo.name

        jobs = db.query(SystemUpdateJob).filter_by(plan_id=plan_id).all()
        success_count = sum(1 for j in jobs if j.status == "success")
        fail_count = sum(1 for j in jobs if j.status == "failed")

        for job in jobs:
            if job.status in ("success", "skipped"):
                continue
            if job.status == "failed":
                continue

            server = db.query(Server).filter_by(id=job.server_id).first()
            if not server:
                job.status = "skipped"
                db.commit()
                continue

            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            job.log = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Güncelleme başlatılıyor...\n"
            db.commit()

            snap_log_lines = []
            if (plan.snapshot_mode or "skip") == "take":
                from app.services.snapshot_service import create_snapshot_for_server, server_can_snapshot
                if not server_can_snapshot(server):
                    # hypervisor_vm_id boş — vCenter taraması yapmadan atla
                    snap_log_lines.append(
                        f"[SNAPSHOT] ⊘ Atlandı: VM ID bilinmiyor (hypervisor sync gerekli)"
                    )
                    job.log = (job.log or "") + f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Snapshot atlandı (VM ID yok)\n"
                    db.commit()
                else:
                    job.log = (job.log or "") + f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Snapshot alınıyor...\n"
                    db.commit()
                    import concurrent.futures as _cf
                    with _cf.ThreadPoolExecutor(max_workers=1) as _snap_pool:
                        _snap_future = _snap_pool.submit(
                            create_snapshot_for_server, server, db,
                            source="system_update",
                            plan_id=plan.id,
                            retention=plan.snapshot_retention or "1w",
                            name_prefix=f"pre-update-p{plan.id}",
                        )
                        try:
                            snap_result = _snap_future.result(timeout=90)
                        except _cf.TimeoutError:
                            snap_result = {"success": False, "message": "Snapshot zaman aşımı (90s)"}
                    if snap_result.get("success"):
                        snap = snap_result.get("snapshot") or {}
                        snap_log_lines.append(
                            f"[SNAPSHOT] ✓ {snap.get('snapshot_name', 'snapshot')} alındı"
                        )
                    elif snap_result.get("skipped"):
                        snap_log_lines.append(
                            f"[SNAPSHOT] ⊘ Atlandı: {snap_result.get('message', 'VM bağlantısı yok')}"
                        )
                    else:
                        snap_log_lines.append(
                            f"[SNAPSHOT] ✗ Hata: {snap_result.get('message', 'bilinmiyor')}"
                        )

            result = apply_updates_to_server(
                server, plan.update_type, global_cred,
                repo_file_content, repo_name,
                override_username=plan.override_username,
                override_password=plan.override_password,
                override_sudo_password=plan.override_sudo_password,
                priv_method=plan.priv_method or "sudo",
                custom_packages=plan.custom_packages or [],
                job_id=job.id,
            )
            job.status           = result["status"]
            job.log              = "\n".join(snap_log_lines + [result.get("log", "") or ""]).strip()
            job.packages_updated = result.get("packages_updated", [])
            job.reboot_required  = result.get("reboot_required", False)
            job.completed_at     = datetime.now(timezone.utc)
            db.commit()

            if result["status"] == "success":
                success_count += 1
            else:
                fail_count += 1
            plan.completed_servers = success_count + fail_count
            db.commit()

        _finalize_plan_status(plan, jobs, db)

        try:
            _generate_ai_summary(plan_id, db)
        except Exception:
            pass
    except Exception as exc:
        logger.error(f"run_system_update_plan #{plan_id}: {exc}", exc_info=True)
        try:
            plan = db.query(SystemUpdatePlan).filter_by(id=plan_id).first()
            if plan:
                jobs = db.query(SystemUpdateJob).filter_by(plan_id=plan_id).all()
                for job in jobs:
                    if job.status == "running":
                        job.status = "failed"
                        job.completed_at = datetime.now(timezone.utc)
                        job.log = (job.log or "") + "\n[HATA] Plan beklenmedik şekilde sonlandı."
                _finalize_plan_status(plan, jobs, db)
        except Exception:
            pass
    finally:
        db.close()


def _finalize_plan_status(plan, jobs, db) -> None:
    """Plan durumunu job sonuçlarına göre kapatır."""
    success_count = sum(1 for j in jobs if j.status == "success")
    fail_count = sum(1 for j in jobs if j.status == "failed")
    plan.completed_servers = success_count + fail_count
    if fail_count == 0 and success_count > 0:
        plan.status = "completed"
    elif success_count == 0 and fail_count > 0:
        plan.status = "failed"
    elif success_count > 0 and fail_count > 0:
        plan.status = "partial"
    else:
        plan.status = "failed"
    plan.completed_at = datetime.now(timezone.utc)
    db.commit()


def recover_stuck_system_update_plans(db, max_minutes: int = 30) -> dict:
    """
    Uzun süredir 'running' kalan job/planları başarısız olarak işaretler.
    Backend yeniden başlatıldığında veya periyodik görevde çağrılır.
    """
    from app.models.system_update import SystemUpdatePlan, SystemUpdateJob
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_minutes)
    recovered_jobs = 0
    finalized_plans = 0

    stuck_jobs = db.query(SystemUpdateJob).filter(
        SystemUpdateJob.status == "running",
        SystemUpdateJob.started_at.isnot(None),
        SystemUpdateJob.started_at < cutoff,
    ).all()  # completed_at kontrolü yok — tutarsız state (running + completed_at set) de yakalanır

    for job in stuck_jobs:
        job.status = "failed"
        job.completed_at = datetime.now(timezone.utc)
        suffix = f"\n[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Sistem: {max_minutes} dk içinde tamamlanmadı — takılı iş durduruldu."
        job.log = ((job.log or "").rstrip() + suffix)[-8000:]
        recovered_jobs += 1
    if recovered_jobs:
        db.commit()

    running_plans = db.query(SystemUpdatePlan).filter(
        SystemUpdatePlan.status == "running",
    ).all()

    for plan in running_plans:
        jobs = db.query(SystemUpdateJob).filter_by(plan_id=plan.id).all()
        still_running = [j for j in jobs if j.status in ("running", "pending")]
        if still_running:
            continue
        _finalize_plan_status(plan, jobs, db)
        finalized_plans += 1

    return {
        "recovered_jobs": recovered_jobs,
        "finalized_plans": finalized_plans,
    }


def cancel_system_update_plan(plan_id: int, db) -> dict:
    """Çalışan planı iptal eder — running job'ları failed yapar."""
    from app.models.system_update import SystemUpdatePlan, SystemUpdateJob

    plan = db.query(SystemUpdatePlan).filter_by(id=plan_id).first()
    if not plan:
        return {"ok": False, "message": "Plan bulunamadı"}
    if plan.status != "running":
        return {"ok": False, "message": f"Plan '{plan.status}' durumunda — iptal edilemez"}

    jobs = db.query(SystemUpdateJob).filter_by(plan_id=plan_id).all()
    cancelled = 0
    for job in jobs:
        if job.status in ("running", "pending"):
            job.status = "failed"
            job.completed_at = datetime.now(timezone.utc)
            job.log = ((job.log or "").rstrip() + "\n[Kullanıcı] Güncelleme iptal edildi.")[-8000:]
            cancelled += 1
    _finalize_plan_status(plan, jobs, db)
    return {"ok": True, "cancelled_jobs": cancelled, "status": plan.status}


def resume_system_update_plan(plan_id: int) -> None:
    """Yalnızca bekleyen job'ları çalıştırır."""
    run_system_update_plan(plan_id)


def _generate_ai_summary(plan_id, db):
    from app.models.system_update import SystemUpdatePlan, SystemUpdateJob
    import requests, json
    plan = db.query(SystemUpdatePlan).filter_by(id=plan_id).first()
    jobs = db.query(SystemUpdateJob).filter_by(plan_id=plan_id).all()
    total_pkgs = sum(len(j.packages_updated or []) for j in jobs)
    reboot_count = sum(1 for j in jobs if j.reboot_required)
    fail_count   = sum(1 for j in jobs if j.status == "failed")
    prompt = f"""Sistem güncelleme tamamlandı. Türkçe özet (3-4 cümle):
Plan: {plan.name} | Tip: {plan.update_type} | Toplam sunucu: {plan.total_servers}
Başarılı: {plan.completed_servers - fail_count} | Başarısız: {fail_count}
Toplam güncellenen paket: {total_pkgs} | Reboot gereken: {reboot_count}"""
    try:
        from app.core.config import settings
        from app.models.app_settings import AppSettings as _AS
        model_row = db.query(_AS).filter_by(key="ollama_active_model").first()
        active_model = (model_row.value if model_row and model_row.value else None) or settings.OLLAMA_DEFAULT_MODEL
        r = requests.post(f"{settings.OLLAMA_URL}/api/generate",
                          json={"model": active_model, "prompt": prompt, "stream": False}, timeout=60)
        if r.status_code == 200:
            plan.ai_summary = r.json().get("response", "")
            db.commit()
    except Exception:
        pass
