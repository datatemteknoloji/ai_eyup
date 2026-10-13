"""B9: LLM'e giden yedek verisinin kapsamı (tek kaynak). Hafif modül — API ve sohbet araçları ortak kullanır."""
from __future__ import annotations

# LLM'e giden yedek verisi YALNIZ bu alanlardır (VM/iş/depo ADI + durum/RPO özeti). Kimlik bilgisi, endpoint,
# ham API yanıtı, oturum mesajı ve ID'ler gönderilmez (test_backup_dilim_d::test_llm_egress_*). Harici (uzak) LLM
# açıksa bu adlar kurum dışına çıkar; arayüz (Yedek & DR entegrasyon sayfası) bunu uyarır.
LLM_EGRESS_FIELDS = ("vm.name", "vm.cluster", "vm.state", "vm.match_confidence", "vm.last_restore_point_at",
                     "vm.rpo_age_min", "vm.target_rpo_min", "vm.rpo_state", "vm.stale",
                     "job.name", "job.last_run_at", "repository.name", "repository.used_pct", "repository.online",
                     "summary.counts")
