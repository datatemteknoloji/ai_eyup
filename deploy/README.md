# deploy/

Hand-authored production deployment assets. These are **templates** consumed by
[`scripts/build-distribution.sh`](../scripts/build-distribution.sh) — don't run them directly from
here; run the generated bundle in `dist/ainew-<version>-linux-amd64/` instead (the compose file's
bind mounts are relative to `backend/`, `frontend/`, `prometheus/` sitting next to it, which only
exist once the bundle is assembled).

| File | Purpose |
|---|---|
| `docker-compose.prod.yml` | Offline stack şablonu (pinned images, `pull_policy: never`, Dropt include). `build-distribution.sh` bunu paket köküne **`docker-compose.yml`** adıyla koyar |
| `docker-compose.build.yml` | Optional online build overlay (registry required) — not used by default install |
| `install-rhel.sh` | RHEL installer: requires `images/*.tar.gz`, `docker load`, `up -d --no-build`; creates Docker data-root/tmp if missing |
| `update-rhel.sh` | In-place upgrade: backs up `.env` + DB + previous image tags, loads new images, retargets `BACKEND_IMAGE`/`FRONTEND_IMAGE`, restarts — never touches `data/` |
| `rollback-rhel.sh` | Roll back to the last (or specified) pre-update backup; optional `--restore-db` |
| `nginx.prod.conf` | Nginx config for the frontend container: HTTP→HTTPS redirect, TLS termination, API/WebSocket proxying to the backend |
| `install-ollama-runtime.sh` | Standalone Ollama runtime installer (image + models) for an already-installed system — merges/verifies `.part*` archives, extracts model packages, restarts the `ollama` profile |
| `install-ollama-model.sh` | Adds a **single additional** Ollama model (chat or embedding) to an existing install, idempotently, independent of what's already on disk — e.g. bolting `gpt-oss:20b` onto a system that only has `nomic-embed-text` |

## Publishing a new version (GitHub Release + CHANGELOG)

`scripts/release.sh` bumps `VERSION`, moves the `CHANGELOG.md` `[Unreleased]` section under a
new version heading, runs `build-distribution.sh`, and commits + tags — so the CHANGELOG (which
ships inside every package, for air-gapped customers) and the GitHub Release notes never drift
apart:

```bash
./scripts/release.sh 1.0.9.17 "Kısa özet" [--with-ollama]
git push && git push origin v1.0.9.17
gh release create v1.0.9.17 dist/ainew-1.0.9.17-linux-amd64.tar.gz* \
  --notes-file /tmp/ainew-release-notes-1.0.9.17.txt --title "ainew 1.0.9.17"
```

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

## Upgrading / rolling back on a customer host

```bash
# Upgrade (run from the NEW package directory)
tar xzf ainew-1.0.1-linux-amd64.tar.gz
cd ainew-1.0.1-linux-amd64
sudo ./update-rhel.sh --install-dir /data

# Roll back application images to the previous version
cd /data
sudo ./rollback-rhel.sh

# Roll back images + database to the pre-update snapshot
sudo ./rollback-rhel.sh --restore-db
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

## Ollama (optional local LLM / RAG embedding)

Two package variants are published per release: a plain one and an
`-with-ollama` one that auto-provisions Ollama + the `nomic-embed-text` RAG
embedding model from the separate, version-independent
[`ollama-runtime-v1`](https://github.com/datatemteknoloji/ai_eyup/releases/tag/ollama-runtime-v1)
release (downloaded once on install/update via the `WITH_OLLAMA` marker file,
then cached under `$DATA_DIR/.ollama-runtime-cache`). Chat LLMs are never
auto-downloaded by `install-rhel.sh`/`update-rhel.sh` — pull them separately
(online: `ollama pull <model>`) or air-gapped, via a pre-built model package.

For a large, pre-quantized chat model that's impractical to `ollama pull` on
an air-gapped host, [`ollama-gpt-oss-20b-v1`](https://github.com/datatemteknoloji/ai_eyup/releases/tag/ollama-gpt-oss-20b-v1)
bundles **`gpt-oss:20b`** (chat) + **`nomic-embed-text`** (embedding) as a
single downloadable set of parts:

```bash
mkdir ollama-gpt-oss-20b && cd ollama-gpt-oss-20b
gh release download ollama-gpt-oss-20b-v1 --repo datatemteknoloji/ai_eyup
# scp/USB the folder to the target host, then:
sudo ./install-ollama-model.sh --model gpt-oss:20b --from ./ollama-gpt-oss-20b --set-default
```

`install-ollama-model.sh` is idempotent and independent of what's already
installed (unlike the `--ollama-files` / `install-ollama-runtime.sh` flow,
which skips entirely once *any* model exists on disk) — safe to run against a
system that already has `nomic-embed-text` to add just the chat model, or
vice versa. Full walkthrough, including manual/air-gapped Ollama runtime
setup: see section 5 of [INSTALL_RHEL.md](../docs/INSTALL_RHEL.md).

## Why these live outside `docker-compose.yml`

The root [`docker-compose.yml`](../docker-compose.yml) is for **local development only** — it
live-mounts `backend/app` for hot-reload, uses `network_mode: host`, and has no TLS or pinned
image versions. Shipping that file to a customer would mean an editable-in-place backend and no
HTTPS. `deploy/` exists so the production path is reviewed, versioned, and reproducible from git
instead of being a one-off manual build.
