# Windows Sunucu Yönetimi ve AIOps

> **Diataxis:** How-to + Reference

Windows sunucular WMI/PowerShell yerine **WinRM** (Windows Remote Management)
üzerinden yönetilir — SSH'nin Linux tarafındaki karşılığı. Bu doküman WinRM
bağlantısı kurmayı, canlı metrikleri, event log toplamayı ve Windows AIOps
sohbetini kapsar.

## Nasıl yapılır: Bir Windows sunucusuna bağlanma

1. **Windows Yönetimi → Sunucular** sayfasında sunucuyu ekleyin (IP + işletim
   sistemi `windows` olarak işaretli).
2. Sunucu satırında **Kimlik Bilgisi Kaydet** ile WinRM kullanıcı adı/şifresini
   girin:

   | Alan | Varsayılan | Açıklama |
   |---|---|---|
   | `port` | `5985` | HTTP WinRM portu (HTTPS için `5986` + `use_https: true`) |
   | `use_https` | `false` | Trafiği şifrelemek için `true` yapın (sertifika gerekir) |
   | `username` / `password` | — | Local admin veya domain hesabı; şifre DB'de şifreli saklanır |

   Kaynak: `backend/app/api/windows.py` (`WinRMCredentials`, `save_credentials`).
3. **Bağlantıyı Test Et** (`POST /api/v1/windows/servers/{id}/test-connection`) —
   başarılıysa sunucu `ai_ready=true` ve `status=ONLINE` olur.
4. Birden çok sunucu için tek tek girmek yerine **Global Kimlik Bilgisi**
   tanımlayıp `apply` ile toplu uygulayabilirsiniz
   (`GET/POST /api/v1/windows/global-credential`, `POST .../apply`).

### WinRM gereksinimleri (hedef Windows sunucuda)

WinRM servisi etkin ve dinlemede olmalı:

```powershell
Enable-PSRemoting -Force
winrm quickconfig -q
Set-Item WSMan:\localhost\Service\AllowUnencrypted -Value $true   # sadece HTTP/test için
```

Üretimde `use_https: true` + geçerli sertifika önerilir.

## Nasıl yapılır: Windows Exporter (Prometheus) kurulumu

Fiziksel/VM ayrımı olmadan, bir Windows sunucusunun **Prometheus** tarafından
scrape edilebilmesi için `windows_exporter` kurulması gerekir:

- Tek sunucu: `POST /api/v1/windows/servers/{id}/exporter/install`
- Toplu kurulum: `POST /api/v1/windows/exporter/install-all` (paralel, worker
  sayısı `bulk_ssh_workers` ayarına göre ölçeklenir)
- Durum kontrolü: `GET /api/v1/windows/servers/{id}/exporter/status`

Kurulumdan sonra sunucu Prometheus hedeflerine otomatik eklenir ve normal
node/windows_exporter tabanlı metrik akışına girer (fiziksel host ise).
**VM ise** Prometheus'a hiç sorgu atılmaz — bkz.
[Metrik Mimarisi](../explanation-metrics-architecture.md).

## Referans: Canlı metrikler (`/windows/live-metrics`)

`GET /api/v1/windows/live-metrics` tüm "AI Ready" Windows sunucularından WinRM
üzerinden CPU/RAM/Disk kullanımını **paralel** toplar — Prometheus/node_exporter
gerektirmez, doğrudan canlı sorgu yapar.

**Performans notu:** Bu uç nokta 20 saniyelik TTL'li bir **cache + single-flight
lock** ile korunur (`_LIVE_METRICS_CACHE`, `backend/app/api/windows.py:34-36`).
Frontend sayfayı 30 saniyede bir polluyor; cache olmadan her poll binlerce
WinRM bağlantısı açardı. Ölçülen etkisi: soğuk çağrı ~5.9s, sıcak (cache
içi) çağrı ~0.8s (bkz. `.gstack/benchmark-reports/`).

## Referans: Event Log toplama

`backend/app/services/windows_log_collector.py` — Windows Event Log'ları WinRM
üzerinden toplar ve `system_events` tablosuna yazar (`log_entry` tipi).
Ayarlanabilir parametreler (Ayarlar → Worker sayıları):

| Ayar | Varsayılan | Aralık |
|---|---|---|
| `windows_log_workers` | 20 | 1-64 |
| `windows_log_batch_size` | 500 | 50-5000 |

Toplama round-robin batch'ler halinde paralel çalışır (`ThreadPoolExecutor`) —
sıralı WinRM çağrısı yapmaz, bu yüzden yüzlerce Windows sunucusu olan
ortamlarda da toplama süresi doğrusal değil, worker sayısına bölünerek ölçeklenir.

## Referans: Windows AIOps (Ops / Chat / Events / Incidents / Analysis)

Linux AIOps ile aynı mimariyi paylaşır (bkz. [AIOps Pipeline](aiops.md)) —
platform parametresi `windows` olan aynı anomali tespiti, olay/insident
akışı ve RCA (Root Cause Analysis) araçları. Sohbet arayüzü
(`/windows/aiops/chat`) WinRM ile toplanan canlı bağlamı (servis durumu,
event log, performans) RAG olmadan doğrudan LLM'e context olarak enjekte eder
(`backend/app/api/windows_chat.py`).

## Referans: Windows üzerinde Ansible/AWX

`/windows/ansible` sayfası WinRM tabanlı Ansible ad-hoc komutları ve AWX job
şablonlarını tetikler. AWX entegrasyonu opsiyoneldir — `.env`'de AWX
URL/token tanımlı değilse ilgili uç noktalar `503 Service Unavailable` döner
(bu bir hata değil, "yapılandırılmamış" durumudur).

## Sorun giderme

| Belirti | Olası neden | Çözüm |
|---|---|---|
| Bağlantı testi başarısız | WinRM servisi kapalı/portu farklı | Hedefte `Enable-PSRemoting`, güvenlik duvarı 5985/5986 |
| Canlı metrikler 20+ saniyedir güncellenmiyor | Cache TTL'i içindesiniz (normal) | 20 saniye bekleyin veya sunucu ekleyip tekrar deneyin |
| `awx/templates` 503 dönüyor | AWX yapılandırılmamış | Beklenen davranış — AWX entegrasyonu opsiyonel |
| Event log toplama yavaş | `windows_log_workers` düşük, sunucu sayısı yüksek | Ayarlar → Worker sayılarını artırın (10k ölçek için bkz. [Ölçek ve Performans](../scale-and-performance.md)) |

## İlgili
- [Metrik Mimarisi (VM vs Fiziksel)](../explanation-metrics-architecture.md)
- [Ölçek ve Performans](../scale-and-performance.md)
- [AIOps Pipeline](aiops.md)
- [Server Management](server-management.md) (Linux/SSH karşılığı)

---
Back to [Documentation Index](../index.md)
