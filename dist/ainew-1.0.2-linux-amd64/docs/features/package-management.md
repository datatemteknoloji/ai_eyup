# Package & Repository Management

ainew provides two complementary tools for managing software packages across your Linux fleet:

1. **Package Manager** — deploy RPM/DEB files directly to servers, check and apply OS updates
2. **Repository Manager** — create and maintain local Yum/APT repositories served over HTTP

---

## Package Manager

### What it does

- Upload RPM or DEB files to the management server
- Deploy uploaded packages to a list of servers via SSH (`yum install` / `apt install`)
- Trigger OS-wide upgrades (`yum upgrade -y` / `apt upgrade -y`)
- Check for pending updates across all servers
- Analyze failed deployments with AI

### How-to: Deploy a package

1. Open **Package Manager** in the sidebar
2. Click **Dosya Yükle** (Upload File) and select an `.rpm` or `.deb`
3. The file is stored on the management host under `/app/uploads/`
4. Select target servers from the list
5. Click **Dağıt** (Deploy)

ainew creates a deployment job and SSHes into each server in parallel to run:
- RPM: `yum localinstall -y /tmp/<package>.rpm`
- DEB: `dpkg -i /tmp/<package>.deb`

**Job progress** is polled in real time. Failed jobs show error output. Click **Hata Analiz Et** to ask the AI for a diagnosis.

### How-to: Check and apply OS updates

1. Go to **System Update** in the sidebar
2. Click **Güncelleme Kontrol Et** (Check Updates)
3. ainew SSHes into each server and runs `yum check-update` or `apt list --upgradeable`
4. Results show pending package count per server
5. Click **Güncelleme Planı Oluştur** (Create Update Plan) to schedule updates

Update plans support:
- **Pre-update VM snapshots** — automatically snapshot VMs before updating (requires ESXi integration)
- **Snapshot retention** — how long to keep pre-update snapshots
- **Parallel execution** — configurable number of servers updated simultaneously

### AI error analysis

When a package deployment fails, click **Hata Analiz Et** on the failed job. ainew sends the error output to Ollama and returns:
- Probable cause (e.g. "dependency conflict: package X requires libfoo >= 2.0")
- Suggested fix (e.g. "install libfoo-2.1 first, then retry")

---

## Repository Manager

### What it does

- Create local Yum (RPM) or APT (DEB) repositories on the management host
- Sync packages from upstream mirrors or local uploads
- Generate client `.repo` / `sources.list` configs
- Push configs to servers via SSH (so servers pull updates from your local repo instead of the internet)

This is useful in air-gapped environments where servers can't reach the internet directly.

### How-to: Create a Yum repository

1. Open **Repositories** in the sidebar
2. Click **+ Yeni Repo** (New Repository)
3. Select type: **Yum** (for RHEL/CentOS) or **APT** (for Debian/Ubuntu)
4. Configure:
   - **Name:** display label
   - **Base URL:** upstream mirror URL (e.g. `https://mirror.example.com/centos/8/BaseOS/x86_64/`)
   - **Local path:** where to store synced packages on the management host
5. Click **Kaydet** (Save) then **Senkronize Et** (Sync)

Syncing runs `reposync` (Yum) or `apt-mirror` (APT). Progress is shown in real time.

### How-to: Push repo config to servers

1. Open a repository
2. Click **Client Config**
3. Select target servers
4. Click **Config Gönder** (Push Config)

ainew generates the `.repo` file (Yum) or `sources.list` entry (APT) and SSHes it into `/etc/yum.repos.d/` or `/etc/apt/sources.list.d/` on each server.

After pushing, servers pull packages from your local repo:
```bash
# On the managed server — this now hits your local mirror
yum update -y
```

### Repository file serving

The management host serves repo files over HTTP at:
```
http://<management-host>:8000/repos/<repo-name>/
```

This is a direct static file mount via FastAPI's `StaticFiles`. No authentication is required for package downloads (repos are read-only and typically LAN-accessible only).

---

## Explanation: Why a local mirror?

In large environments (100+ servers), having every server pull packages directly from the internet:
- Consumes significant upstream bandwidth
- Creates single points of failure (if the upstream mirror is down, no updates)
- Makes patching slower (parallel downloads from one upstream)
- Is impossible in air-gapped networks

A local mirror centralizes the download once, then serves packages at LAN speed to all servers. The trade-off is disk space on the management host (~20–100 GB per repo) and the operational burden of keeping the mirror current.

---

## Related

- [Package Management API](../api-reference.md#package-management)
- [Repository Management API](../api-reference.md#repository-management)
- [System Updates API](../api-reference.md#system-updates)
