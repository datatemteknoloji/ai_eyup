"""Sohbet kalite paketi (Sanallaştırma · OpenShift · Admin/Unified).

Bağımsız katman: Automic koduna dokunmaz, ondan import etmez.
Bağlanma noktaları (hepsi "bağlı değilse no-op"):
  - chat_orchestrator.run_turn  → tur izini bağlar, debug_trace olayını yayar
  - unified_tool_chat.run_read_only_tool_loop → araç sonuçlarını izler
  - hypervisor_intelligence.try_deterministic_answer → qa_rule yolunu izler
"""
