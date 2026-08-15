# RAG seed (kurulumla gelen / elle bırakılan dokümanlar)

Bu dizin uygulama köküne göredir:

```text
{kurulum}/docs/rag_seed/     örn. /data/app/docs/rag_seed
```

Container içinde: `/app/docs/rag_seed` (`RAG_SEED_PATH`).
Chunk/indeks: `{DATA_DIR}/chroma` → `/app/chroma` (kalıcı volume).

Paket (tar) bu dizini içerir. Backend **ilk açılışta** (ve her restart’ta, idempotent)
dosyaları Chroma **runbook** koleksiyonuna chunk’lar. Embedding için Ollama
`nomic-embed-text` gerekir; hazır değilse birkaç dakika yeniden dener.

## Gömülü runbook’lar

Linux / virt / OpenShift operasyon özetleri (`LINUX-*.md`, `VIRT-*.md`, `OCP-*.md`).
Vendor PDF’leri (Red Hat, Broadcom, …) lisansı gereği pakete konmaz — aşağıdaki gibi ekleyin.

## Nasıl eklenir?

1. PDF (veya `.md` / `.txt`) dosyalarını buraya koyun.
2. `manifest.json` içine kaydedin (önerilir) **veya** dosya adını title olarak kullanın.
3. Backend’i yeniden başlatın (veya bir sonraki startup seed’i).

Başlık standardı (öneri): `RHEL9-multipath`, `OCP4-pending-pods`, `VSPHERE-ha-drs`.

## manifest.json

```json
{
  "documents": [
    {
      "title": "RHEL9-storage-lvm-multipath",
      "file": "RHEL9-storage-lvm-multipath.pdf",
      "version": "1",
      "enabled": true
    }
  ]
}
```

- `version` değişince eski title silinir ve yeniden ingest edilir.
- `enabled: false` → atlanır.
- Manifest boş/`documents: []` iken dizindeki `.pdf`/`.md`/`.txt` taranır (title = dosya adı).

## Docker

`docker-compose.yml` / prod:

`./docs/rag_seed:/app/docs/rag_seed:ro`

Env: `RAG_SEED_PATH=/app/docs/rag_seed`
