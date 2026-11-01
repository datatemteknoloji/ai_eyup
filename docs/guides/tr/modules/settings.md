# ainew — Ayarlar ve yönetim GUIDE

Ayarlar (`/settings`), kullanıcılar (`/users`), denetim (`/audit`). Çoğu sekme admin.

## Ayarlar sekmeleri

| Sekme | İşlem |
|-------|--------|
| Linux SSH | Kimlik, varsayılan, uygula |
| WinRM | Windows kimlik |
| AI | Ollama / `REMOTE_LLM_*`, model |
| Marka | Uygulama adı, logo, şirket adı, giriş ekranı alt başlığı, başlığı ve açıklaması ile alt bilgi metni (giriş ekranına yansır; boş bırakılan alan varsayılan metni kullanır) |
| RAG | Runbook / incident / metrik gömme |
| İzleme | Prom / Pushgateway, job adları |
| Güvenlik | Oturum, politika, AD ve SSO (OIDC: Issuer, Client ID/Secret, grup→rol eşleme, «Yapılandırmayı test et») |
| Gelişmiş | Saklama, sohbet/LLM/RAG kapıları ve süreleri (önbellek, ilerleme göstergesi, varlık/sayım kapıları, veriye dayalılık modu, LLM zaman aşımı, RAG alaka eşiği), işçi sayıları |
| Hakkında | Sürüm, **ürün GUIDE PDF** |
| Platform / yedek / güncelleme / tehlikeli | İşletim |

## Kullanıcılar

Rol + **modül kutuları**. Admin bypass. `custom_reports` / `applications` / `knowledge` ayrı atama.

## Denetim

`/audit` ainew; Level 1 admin izi `/level1/audit`.

## GUIDE indirme

Hakkında: dil TR/EN, paket Tamamı veya modül (Linux, Windows, Sanallaştırma, oVirt, OpenShift, Exadata, Level 1, Entegrasyonlar, Yönetici/AI, Ayarlar). Yazdır → PDF. Canlı VM listesi değildir.
