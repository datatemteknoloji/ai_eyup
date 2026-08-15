# ainew — Chat ve RAG

## Nerede ne sorulur
- **Linux Chat:** SSH/systemd/disk; envanter listesi DB kısayolu.
- **Windows Chat:** WinRM.
- **Virt Chat:** vCenter + KubeVirt.
- **OpenShift Chat:** pod/node/project.
- **Tüm Altyapı:** çapraz özet; “listele” canlı tarama değildir.

## RAG
Kurulum `docs/rag_seed` PDF/md dosyalarını açılışta Chroma runbook’a chunk’lar.
Gömme (embedding) yerel Ollama `nomic-embed-text` ister. Chat modeli uzak gateway olabilir.
Ayarlar → RAG: ek PDF. Incident/event/bilgi bankası ayrı koleksiyon.

## İpuçları
Sunucu adı yazın. “Tüm sunucular” cap + onay. Uzak AI: zorunlu URL + model; anahtar isteğe bağlı.
