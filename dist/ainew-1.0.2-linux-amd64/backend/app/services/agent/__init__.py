"""
Agentic AI alt sistemi.

Bileşenler:
  - policy:       Sandbox / allowlist / denylist + risk sınıflandırma
  - executor:     SSH üzerinden güvenli komut çalıştırma (timeout, çıktı limiti, audit)
  - tools:        Tool registry (read-only otomatik, mutating onaylı)
  - llm:          Seçilebilir model ile tool-calling (Ollama /api/chat)
  - orchestrator: İteratif agent döngüsü + insan onayı için duraklatma
"""
