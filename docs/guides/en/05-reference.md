## 14. Diagram index

Stack (2.1), ports (2.4), logical (4), metric/virt flow (6), **AI/model** (8), Level 1 (12.8), compose (10).

## 15. Design decisions

FastAPI, React, Timescale, Docker Compose, host-network SSH, tool-first fail-fast AI.

## 16. Limitations

oVirt is not its own sidebar/RBAC. Large-fleet dashboard widget can be slow. Frontend is baked. Prom chat is read-only. Level 1 ≠ Linux `/packages`. Runtime is Docker Compose (not podman-compose). Older “Ollama only” docs are outdated.

## 17. Future

Single tenant, single Compose. No HA claim. See `docs/scale-and-performance.md`.

## 18. Troubleshooting

Missing menu → Users/modules. PDF → pop-up + Print. Sync → FQDN. Chat → Settings AI. L1 → Dropt 8001. Metrics → exporters.

## 19. Developer

`Layout.tsx` · `backend/app/api/router.py` · `docs/guides/` · `docs/INSTALL_RHEL.md` · `scripts/build-distribution.sh`.

## 20. Glossary

ainew · Compose · Dropt · OLVM · Ollama · PromQL · RAG · REMOTE_LLM · Request/Preview/Apply · TimescaleDB.
