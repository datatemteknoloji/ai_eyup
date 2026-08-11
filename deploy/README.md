# deploy/

Hand-authored production deployment assets. These are **templates** consumed by
[`scripts/build-distribution.sh`](../scripts/build-distribution.sh) — don't run them
directly from here; run the generated bundle in `dist/ainew-<version>-linux-amd64/`
(or the extracted Release tarball) instead. Bind mounts are relative to `backend/`,
`frontend/`, `prometheus/` sitting next to the compose file, which only exist once
the bundle is assembled.

| File | Purpose |
|---|---|
| `docker-compose.prod.yml` | Offline stack template (pinned images, `pull_policy: never`, Dropt include). `build-distribution.sh` copies this to the package root as **`docker-compose.yml`** |
| `docker-compose.build.yml` | Optional online build overlay (registry required) — not used by default install |
| `install-rhel.sh` | RHEL installer: requires `images/*.tar.gz`, `docker load`, `up -d --no-build`; creates Docker data-root/tmp if missing |
| `update-rhel.sh` | In-place upgrade: backs up `.env` + DB + previous image tags, loads new images, retargets `BACKEND_IMAGE`/`FRONTEND_IMAGE`, restarts — never touches `data/` |
| `rollback-rhel.sh` | Roll back to the last (or specified) pre-update backup; optional `--restore-db` |
| `nginx.prod.conf` | Nginx config for the frontend container: HTTP→HTTPS redirect, TLS termination, API/WebSocket proxying to the backend |
| `install-ollama-runtime.sh` | Standalone Ollama runtime installer (image + models) for an already-installed system — merges/verifies `.part*` archives, extracts model packages, restarts the `ollama` profile |
| `install-ollama-model.sh` | Adds a **single additional** Ollama model (chat or embedding) to an existing install, idempotently |

## Publishing a new version (GitHub Release)

Preferred path (build already done, or after `build-distribution.sh`):

```bash
./scripts/build-distribution.sh          # → dist/ainew-<ver>-linux-amd64.tar.gz
./scripts/publish-github-release.sh      # commit (safe set) + tag + push + gh release upload
```

Or bump `VERSION` + `CHANGELOG.md`, build, and publish in one go:

```bash
./scripts/release.sh 1.0.9.23 "Kısa özet"   # optional: --with-ollama / --bundle-ollama
```

Customer download is the **Release asset** `ainew-<version>-linux-amd64.tar.gz`
(plus `.sha256`). Large image trees are **not** required in git for install;
CI does not pack `dist/` from the repository on tag push.

## Building and installing a release

```bash
# From repo root, on a build machine with Docker + buildx:
./scripts/build-distribution.sh

# Copy the resulting tar to the target host (or download from GitHub Releases):
scp dist/ainew-<version>-linux-amd64.tar.gz root@<host>:/root/
ssh root@<host>
tar xzf ainew-<version>-linux-amd64.tar.gz
cd ainew-<version>-linux-amd64
sudo ./install-rhel.sh
```

## Upgrading / rolling back on a customer host

```bash
# Upgrade (run from the NEW package directory)
tar xzf ainew-<version>-linux-amd64.tar.gz
cd ainew-<version>-linux-amd64
sudo ./update-rhel.sh --install-dir /data

# Roll back application images to the previous version
cd /data
sudo ./rollback-rhel.sh

# Roll back images + database to the pre-update snapshot
sudo ./rollback-rhel.sh --restore-db
```

Full walkthrough: [../docs/INSTALL_RHEL.md](../docs/INSTALL_RHEL.md).

## Image parts (`.part01`, …)

Image archives over ~90MB may be split into `*.tar.gz.part01`, `.part02`, …
(`build-distribution.sh`). `install-rhel.sh` reassembles them before `docker load`.

## Ollama (optional local LLM / RAG embedding)

Default release tarball is **without** Ollama images (smaller offline app stack).

Optional variants / flows:

| Mode | How |
|---|---|
| Marker download at install | `build-distribution.sh --with-ollama` → `*-with-ollama.tar.gz`; install may fetch once from `ollama-runtime-v1` |
| Fully embedded | `--bundle-ollama` (~+3.5GB): Ollama image + `nomic-embed-text` inside the package |
| Air-gap files | `sudo ./install-rhel.sh --ollama-files /path/to/files` |
| After install | `install-ollama-runtime.sh` / `install-ollama-model.sh` |

Chat LLMs are not auto-downloaded by install unless you use a dedicated model
release (e.g. [`ollama-gpt-oss-20b-v1`](https://github.com/datatemteknoloji/ai_eyup/releases/tag/ollama-gpt-oss-20b-v1)):

```bash
mkdir ollama-gpt-oss-20b && cd ollama-gpt-oss-20b
gh release download ollama-gpt-oss-20b-v1 --repo datatemteknoloji/ai_eyup
# scp/USB to target, then:
sudo ./install-ollama-model.sh --model gpt-oss:20b --from ./ollama-gpt-oss-20b --set-default
```

See [INSTALL_RHEL.md](../docs/INSTALL_RHEL.md) §5.

## Why these live outside the root `docker-compose.yml`

The root [`docker-compose.yml`](../docker-compose.yml) is for **local development
only** — live-mounts, `network_mode: host`, no TLS / pinned customer images.
`deploy/` keeps the production path reviewed and reproducible; the customer
package exposes it as `docker-compose.yml` at the bundle root.
