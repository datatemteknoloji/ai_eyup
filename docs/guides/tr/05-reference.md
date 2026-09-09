## 14. Architecture Diagrams (indeks)

Bu belgede: yığın (bölüm 2.1), konteyner/port (2.4), veri dizini (2.7), logical (4), metrik/virt akış (6), **AI/model** (8), Level 1 (12.8), compose (10).

---

## 15. Design Decisions

**FastAPI** — HTTP + Python SSH/AI. **React** — menü, tablo, SSE. **Timescale** — envanter + seri + pgvector tek DB. **Docker Compose** — tek host, air-gap tar. Host network: SSH için ödün. **AI:** veri içeride, tool gerçeği okur, mutasyon onaylı, fail-fast.

---

## 16. Limitations

oVirt ayrı sol menü/RBAC değildir. Dashboard kaynak grafiği çok büyük filoda yavaşlayabilir. Frontend baked. Prom sohbeti yazmaz. Level 1 ≠ Linux `/packages`. Resmi çalıştırma Docker Compose’tur (podman-compose iddiası yok). Eski `docs/architecture.md` “yalnızca Ollama” ifadesi güncel değildir.

---

## 17. Future

Tek tenant, tek compose. HA/multi-tenant iddiası yok. `docs/scale-and-performance.md`.

---

## 18. Troubleshooting

Menü yok → Kullanıcılar / modül. PDF → pop-up + Yazdır. Sync → FQDN/kimlik. Chat → Ayarlar AI. L1 → Dropt 8001. Metrik → exporter. Yanlış DB’ye bağlanmayın.

---

## 19. Developer Guide

Menü: `frontend/src/components/Layout.tsx`. API: `backend/app/api/router.py`. Modül: `backend/app/models/module.py`. L1: `frontend/src/pages/level1/`, `dropt/`. GUIDE: `docs/guides/`. Dağıtım: `scripts/build-distribution.sh`. Kurulum: `docs/INSTALL_RHEL.md`.

---

## 20. Glossary

| Terim | Anlam |
|-------|--------|
| ainew | Bu ürün |
| Compose | Docker Compose yığını |
| Dropt | Level 1 sidecar |
| OLVM | Oracle Linux Virtualization Manager (oVirt) |
| Ollama | Yerel LLM sunucusu |
| PromQL | Prometheus sorgu dili |
| RAG | Vektör bilgi bankası |
| REMOTE_LLM | Uzak OpenAI uyumlu geçit |
| Talep / Preview / Apply | Level 1 iş akışı |
| TimescaleDB | Postgres zaman serisi |
