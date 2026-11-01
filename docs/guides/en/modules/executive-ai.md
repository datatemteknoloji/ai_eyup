# ainew — Executive & AI GUIDE

Modules `executive` and `ai_automation`.

| Menu | Path | Actions |
|------|------|---------|
| Executive summary | `/executive` | Cross-platform summary |
| Unified assistant | `/chat` | Cross-domain tools |
| Agent | `/agent` | LangGraph; mutations approved |

Platform chats stay under their modules. Local Ollama or remote LLM; fail-fast. Prometheus: PromQL only. RAG is Settings → RAG, not this GUIDE. Chat PDF can export the page or selected Q&A. The executive view does not replace Level 1 Preview/Apply.

## All-environment Ready Reports (`/executive/infra-reports`)

A card grid in the Executive module, separate from `/executive` (11 reports): Executive Summary, Capacity, Capacity Forecast, Risk, Riskiest Assets, Operations, Availability (SLA), Patch and Compliance, Reclaim, Monitoring Coverage, Migration (VMware → OpenShift). Each report spans Virtualization, OpenShift, Linux, Windows and Exadata, but an area is included **only where it is meaningful for that report**. The coverage table is fixed in code (`services/exec_catalog_reports.py` → `MATRIX`); an excluded area is written to the report **with its reason** (e.g. Forecast: Windows and Exadata are out of scope because no usage series is collected). Missing data shows "Not measurable"; no number is invented. Synthetic (ZZ-FAKE) sources are excluded. The area grade uses the `exec_health` formula (it can differ from the team-report grade). Backup (Veeam) is not part of these reports. No LLM. Generation can take 1–10 s.
