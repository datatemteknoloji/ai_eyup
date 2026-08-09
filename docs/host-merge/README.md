# Dropt → Host merge pack

Bu klasör, Dropt Ops Portal’ı **başka bir uygulamaya gömmek** için hedef ortamdaki Cursor’a verilecek pakettir.

## Dosyalar (hedefe kopyala)

| Dosya | Rol |
|--------|-----|
| **`DROPT-OPS-HANDBOOK.pdf`** | Tüm operasyonlar + kurallar + playbook (19 sayfa) — ana el kitabı |
| **`DROPT-OPS-HANDBOOK.md`** | Aynı içerik Markdown (Cursor’un okuması için tercih edilir) |
| `dropt-host-merge-manifest.json` | Yapılandırılmış merge manifest |
| `dropt-host-merge.mdc` | Hedef `.cursor/rules/` altına kopyala (`alwaysApply: true`) |
| `capabilities.json` | Asistan ops kataloğu (backend ile senkron kopya) |
| `generate_ops_handbook.py` | Handbook yeniden üretim scripti |

## Hedef Cursor’a örnek prompt

```text
@DROPT-OPS-HANDBOOK.md
@DROPT-OPS-HANDBOOK.pdf
@dropt-host-merge-manifest.json
@dropt-host-merge.mdc
@capabilities.json

Dropt Ops Portal'ı bu uygulamaya gömüyoruz.
El kitabı + manifest + kurallara göre TÜM operasyonların eksiksiz olduğundan emin ol.
Eksik wizard, API wiring, settings paneli, Centrify/HPSA/ASM/DNS checklist veya
embedded console akışı varsa tamamla.
- Login yok (bizde var)
- Sunucu listesi vCenter; çift tık → Dropt ops console
- Ayarlar: general/account yok; automation/mail/assistant/repos/centrify/backup Dropt submenu
- MFA/oturumlar bizde yoksa üst Ayarlar'a taşı
Önce auth bridge + server identity mapping planı çıkar, sonra gap listesi üret ve uygula.
```

## Handbook yeniden üretmek

```bash
python3 docs/host-merge/generate_ops_handbook.py
```

Kaynak: `dropt-host-merge-manifest.json` + `backend/app/assistant/capabilities.json` + `.cursor/rules/dropt-*.mdc`

## Not

Cursor için **MD + JSON + MDC** PDF’ten daha güvenilir parse edilir. PDF’i insan incelemesi / ek referans olarak verin; agent’a mutlaka MD/JSON’u da `@` ile verin.
