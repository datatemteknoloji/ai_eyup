# Centrify / Delinea Server Suite — Zone Yönetimi Runbook

## Genel Bakış

Centrify (Delinea Server Suite), Linux/UNIX sunucularında Active Directory tabanlı merkezi kimlik ve erişim yönetimi sağlar. ainew platformu, Centrify zone modelini (roller, komutlar/right'lar, role assignment'lar, computer role'ler) WinRM üzerinden yönetir.

## Mimari

```
ainew Backend → WinRM (pywinrm, NTLM) → Windows Server (Access Manager) → ADEdit → Active Directory
```

- ainew doğrudan AD'ye bağlanmaz
- Tüm işlemler Access Manager kurulu Windows sunucu üzerinden yapılır
- PowerShell scriptleri parametre olarak kullanıcı girdisi alır (interpolasyon yok)

## Temel Kavramlar

### Zone
Sunucu gruplarını organize eden AD container. İki tip:
- **Hierarchical**: Alt zone destekler, parent'tan politika devralır
- **Classic**: Tek seviye, bağımsız politika

### Role
Yetki kümesi. Komut/right'lar role'e bağlanır, role kullanıcı/gruba atanır.
- **Sistem Rolü**: always_permit_login, always_deny_login gibi yerleşik roller
- **Özel Rol**: Yönetici tanımlı (sysadmin, dba-admin vb.)

### Command/Right
Belirli bir komutu belirli bir kullanıcı olarak çalıştırma hakkı.
- **match_type**: exact, glob, regex
- **run_as_user**: Komut hangi kullanıcı olarak çalışır (root, oracle vb.)
- **auth_type**: none (doğrudan), password (parola), mfa (çok faktörlü)

### dzdo
Centrify'ın sudo benzeri mekanizması. AD'deki role/right tanımlarını uygular.
- `dzdo -u oracle /u01/app/oracle/product/19c/bin/lsnrctl start`
- Yerel sudoers dosyası değil, merkezi AD politikası

### Role Assignment
Kullanıcı veya AD grubu → role ataması.
- **Zone scope**: Tüm zone sunucularında geçerli
- **Computer scope**: Belirli sunucu/computer role'de geçerli

### Computer Role
Sunucu grupları. Role assignment'ı belirli sunucu grubuna daraltmak için kullanılır.

## Operasyonel Prosedürler

### Yeni Rol Oluşturma
1. Zone seçin
2. Roller tabında "sağ tık → Kopyala" veya İşlemler panelinden "create_role" operasyonu
3. Onay beklenir (dört göz prensibi — kendi isteğinizi kendiniz onaylayamazsınız)
4. Onaylanan operasyon WinRM üzerinden AD'ye yazılır

### Komut Tanımlama
1. Komutlar tabında "Yeni Komut" butonu
2. Şablondan başlayabilirsiniz (18 yerleşik şablon)
3. Beyaz liste kontrolü yapılır (izin verilen path'ler)
4. Onay gerekir

### Rol Klonlama
1. Kaynak rolü sağ tıklayın → "Kopyala"
2. Hedef zone ve yeni ad belirleyin
3. Komutlar otomatik kopyalanır
4. Onay sonrası AD'ye yazılır

### Rol Üzerine Yazma (Overwrite)
1. Hedef rolü sağ tıklayın → "Üzerine Yaz"
2. Kaynak rolü seçin
3. Diff önizlemesini inceleyin (eklenen/silinen/değişmeyen komutlar)
4. Etkilenen atama sayısını kontrol edin
5. Gerekçe girin
6. Onay sonrası uygulanır

## Sorun Giderme

### Circuit Breaker Açık
**Belirti**: Tüm Centrify işlemleri "Circuit breaker açık" hatası verir
**Neden**: 2 ardışık WinRM kimlik doğrulama hatası
**Çözüm**:
1. Service account parolasını doğrulayın
2. Windows sunucuya RDP ile bağlanıp service_centrify hesabını kontrol edin
3. AD'de hesabın kilitli olup olmadığını kontrol edin
4. Düzeldikten sonra: ainew → Centrify sayfası → "Circuit Reset" butonu

### Senkronizasyon Eski
**Belirti**: "Son sync: X saat önce" uyarısı
**Neden**: WinRM bağlantı sorunu veya Access Manager servis kesintisi
**Çözüm**:
1. Circuit breaker durumunu kontrol edin
2. "Senkronize Et" butonuyla manuel sync deneyin
3. Windows sunucuda ADEdit'in çalışır durumda olduğunu doğrulayın

### Drift Tespit Edildi
**Belirti**: Drift sekmesinde uyarı
**Neden**: AD'de ainew dışında yapılan değişiklik
**Çözüm**:
1. Drift detayını inceleyin (hangi alan değişmiş)
2. Değişiklik istenen bir durum mu kontrol edin
3. Değilse: ainew'den düzeltme operasyonu oluşturun
4. İstenense: "Kabul Et" ile drift'i onaylayın

### Operasyon Başarısız
**Belirti**: İşlemler panelinde "failed" durumlu operasyon
**Neden**: WinRM hatası, AD izin sorunu, nesne bulunamadı
**Çözüm**:
1. Operasyon detayında hata mesajını okuyun
2. Geçici hata (bağlantı) ise: "Yeniden Dene" butonu
3. Kalıcı hata (izin, nesne yok) ise: Sorunu çözüp yeni operasyon oluşturun

## Güvenlik Kontrol Listesi

- [ ] Service account parolası her 90 günde değiştirilmeli
- [ ] Circuit breaker eşiği (2 fail) AD lockout threshold'undan düşük olmalı
- [ ] Komut beyaz listesi tanımlı olmalı (açık bırakılmamalı)
- [ ] Kritik komutlar (shutdown, passwd, firewall) MFA gerektirmeli
- [ ] Tüm yazma operasyonları dört göz onayından geçmeli
- [ ] Audit log düzenli incelenmeli
- [ ] Drift event'leri 24 saat içinde ele alınmalı

## Monitoring

### Health Endpoint
`GET /api/v1/centrify-mgmt/health` — JSON formatında sağlık durumu

### Prometheus Metrikleri
`GET /api/v1/centrify-mgmt/metrics` — Prometheus text format

| Metrik | Açıklama | Alert Eşiği |
|--------|----------|-------------|
| centrify_up | Modül durumu | 0 = critical |
| centrify_circuit_open | Circuit breaker | 1 = critical |
| centrify_auth_fail_count | Auth hata sayacı | ≥1 = warning |
| centrify_zone_count | Zone sayısı | 0 = warning |
| centrify_operations_pending | Bekleyen onay | ≥10 = warning |
| centrify_operations_failed | Başarısız operasyon | ≥5 = warning |
