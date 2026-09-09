# ainew — Exadata GUIDE

Modül `exadata`: Oracle Exadata DB Machine envanteri (rack, compute, storage cell), rapor ve AIOps.

## Menüler

| Menü | Yol | İşlem |
|------|-----|--------|
| Envanter | `/exadata` | Rack / node / cell |
| Raporlar | `/exadata/reports` | Altyapı raporları |
| AIOps | `/exadata/chat`, `/ops`, `/events`, `/incidents`, `/analysis` | Asistan ve operasyon |

Bağlantı: **Entegrasyonlar → Exadata envanteri** (`/integrations/exadata`).

## Limitler

Exadata, Linux SSH veya Level 1 ASM sihirbazının yerine geçmez. L1 ASM, hedef Linux host’ta disk işidir.
