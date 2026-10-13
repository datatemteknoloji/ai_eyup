# Automic maskeleme politikası

## Karar

LLM kurum içinde (`llm_deployment=internal`) çalışsa bile gizli bilgiler **hiçbir koşulda** LLM'e, UI'a, sohbet geçmişine veya loglara gitmez.

## Uygulama noktaları (önce maskele)

| Çıkış | Nerede |
|-------|--------|
| Modül DB | Collector rapor alıntısı, OT script sürümü |
| LLM | Sohbet araç metni + insight metrik JSON |
| Audit | `_audit` → `redact_secrets` / `mask_obj(SECRETS_ONLY)` |
| UI | Rapor/cache sorguları; sohbet bileşenleri (maskeli structured) |

## Kurallar

| | |
|--|--|
| Her zaman | Şifre, token, API key, private key, `PWD=`/`password=`/`user/pass@host`, Authorization |
| Maskelenmez | Automic `NAME/DEPARTMENT` |
| Ayar (varsayılan: göster) | `masking.mask_ip`, `masking.mask_hostname` |
| LLM konumu | `llm_deployment`: `internal` \| `external` — external’da UI uyarısı + audit `llm_deployment_change` |

Kod: `backend/app/services/automic/masking.py`.
