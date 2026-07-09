# deploy/

Hand-authored production deployment assets. These are **templates** consumed by
[`scripts/build-distribution.sh`](../scripts/build-distribution.sh) — don't run them directly from
here; run the generated bundle in `dist/ainew-<version>-linux-amd64/` instead (the compose file's
bind mounts are relative to `backend/`, `frontend/`, `prometheus/` sitting next to it, which only
exist once the bundle is assembled).

| File | Purpose |
|---|---|
| `docker-compose.prod.yml` | Production stack: pinned image versions, immutable backend image (no live source mount), HTTPS frontend, `localhost`-only DB/Redis binding, SELinux `:Z` bind-mount labels |
| `install-rhel.sh` | RHEL/Rocky/AlmaLinux 9 installer: Docker setup, data directories, random secret generation (`SECRET_KEY`, `POSTGRES_PASSWORD`, `ADMIN_DEFAULT_PASSWORD`), self-signed TLS, firewalld rules, `docker compose up -d` |
| `nginx.prod.conf` | Nginx config for the frontend container: HTTP→HTTPS redirect, TLS termination, API/WebSocket proxying to the backend |

## Building and installing a release

```bash
# From repo root, on a dev machine with Docker + buildx:
./scripts/build-distribution.sh

# Copy the resulting dist/ainew-<version>-linux-amd64.tar.gz to the target host:
scp dist/ainew-<version>-linux-amd64.tar.gz root@<host>:/root/
ssh root@<host>
tar xzf ainew-<version>-linux-amd64.tar.gz
cd ainew-<version>-linux-amd64
sudo ./install-rhel.sh
```

Full walkthrough, requirements, and maintenance commands: [../docs/INSTALL_RHEL.md](../docs/INSTALL_RHEL.md).

## Fully air-gapped install via `git clone` / "Download ZIP"

The generated `dist/ainew-<version>-linux-amd64/` bundle (including `images/*.tar.gz`) is
tracked in git — not the standalone `.tar.gz`/`.sha256` (those stay local-only, see
`.gitignore`). This lets a target host with **no internet/registry access at all** get a
working install straight from GitHub, either via `git clone` or the web UI's "Download ZIP":

```bash
git clone <repo-url>          # or unzip a "Download ZIP" archive
cd <repo>/dist/ainew-<version>-linux-amd64
sudo ./install-rhel.sh
```

Image archives over 90MB are split into `*.tar.gz.part01`, `.part02`, ... because GitHub
rejects files over 100MB without Git LFS (and LFS content isn't included in "Download ZIP"
archives, which defeats the point for air-gapped transfers). `install-rhel.sh` automatically
reassembles the parts before `docker load` — no manual step needed. `build-distribution.sh`
does this splitting automatically whenever it produces an image archive over the threshold.

Ollama models are never part of this bundle (multi-GB, unrelated to app versioning) — see
[INSTALL_RHEL.md](../docs/INSTALL_RHEL.md) for the separate `export/import-ollama-models.sh`
flow.

## Why these live outside `docker-compose.yml`

The root [`docker-compose.yml`](../docker-compose.yml) is for **local development only** — it
live-mounts `backend/app` for hot-reload, uses `network_mode: host`, and has no TLS or pinned
image versions. Shipping that file to a customer would mean an editable-in-place backend and no
HTTPS. `deploy/` exists so the production path is reviewed, versioned, and reproducible from git
instead of being a one-off manual build.
