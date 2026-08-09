# RAG seed (kurulumla gelen / elle bırakılan dokümanlar)

Bu dizin uygulama köküne göredir:

```text
{kurulum}/docs/rag_seed/     örn. /dttadvance/app/docs/rag_seed
```

Backend açılışında (idempotent) Chroma **runbook** koleksiyonuna yüklenir.
Chroma indeksi ayrı kalır (`/app/chroma` volume).

## Nasıl kullanılır?

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

`docker-compose.yml` içinde:

`./docs/rag_seed:/app/docs/rag_seed:ro`

Env (opsiyonel): `RAG_SEED_PATH=/app/docs/rag_seed`
