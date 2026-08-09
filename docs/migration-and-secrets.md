# Taşıma (DB yedek) ve secret yönetimi

Bu doküman ainew tam veritabanı taşıması ile `SECRET_KEY` / `.env` sırlarının nasıl birlikte yönetileceğini sabitler.

## Kurulum (yeni ortam)

1. `install-rhel.sh` veya `./scripts/dev-setup.sh` çalıştırın.
2. `.env.example` içindeki `GENERATE_WITH_*` / `CHANGE_ME*` değerleri **otomatik** `openssl rand` ile değiştirilir.
3. Üretilen `.env` dosyasını güvenli yedekleyin (`chmod 600`).
4. Backend, placeholder `SECRET_KEY` ile **ayağa kalkmaz** (`ALLOW_INSECURE_SECRETS=1` geçici kaçış, önerilmez).

İlgili anahtarlar:

| Anahtar | Rol |
|--------|-----|
| `SECRET_KEY` | JWT + Fernet (credential, vCenter, OCP token, MFA, …) |
| `POSTGRES_PASSWORD` | ainew TimescaleDB |
| `AINEW_BRIDGE_SECRET` | ainew ↔ Dropt köprü |
| `DROPT_POSTGRES_PASSWORD` | Level 1 Dropt DB |

## Canlı ortamda zayıf / placeholder key

Sadece `.env` satırını değiştirmek **şifreli alanları bozar**.

```bash
# SECRET_KEY: DB re-encrypt + .env + backend recreate
./scripts/rotate-secrets.sh

# + Postgres rol parolası
./scripts/rotate-secrets.sh --postgres
```

Script `.env` yedeği alır (`*.bak-rotate-*`). Sonrasında tüm kullanıcı oturumları düşer — yeniden giriş gerekir.

## Tam DB taşıma (Settings → Yedek / Taşıma)

Tam zip (`ainew.sql` + opsiyonel `dropt.sql`) **ciphertext** taşır.

### Kaynak

1. Settings → **Veritabanı yedeği** → zip indir  
2. `.env` yedeği alın (en azından `SECRET_KEY`, `AINEW_BRIDGE_SECRET`, DB parolaları)

### Hedef

1. Temiz kurulum yapın  
2. Hedef `.env` içinde **yeni rastgele `SECRET_KEY` üretmeyin** — kaynaktaki `SECRET_KEY` (ve bridge) değerlerini yapıştırın  
3. Servisleri ayağa kaldırın  
4. Settings → zip **doğrula** → fingerprint **eşleşiyor** olmalı  
5. Onay metni (secret değil): `VERITABANI GERI YUKLE`  
6. Restore sonrası gerekirse backend/worker restart; admin login + bir SSH/vCenter smoke test

Fingerprint eşleşmiyorsa restore’a zorlamayın (veya bilinçli riskle `require_fingerprint_match=false` — şifreli alanlar açılamayabilir).

### Config JSON yedeği (eski “Yapılandırma Yedek”)

Ayarlar + credential plaintext taşır; hedef kendi `SECRET_KEY` ile yeniden şifreler. Envanter / audit / hypervisor kayıtları **yoktur** — tam DB zip kullanın.

## update-rhel.sh davranışı

- Eksik Dropt anahtarlarını doldurur.
- `SECRET_KEY` / `POSTGRES_PASSWORD` hâlâ placeholder ise **sessizce değiştirmez**; `rotate-secrets.sh` uyarısı basar.

## İç hostname (OpenShift / AD)

Compose `extra_hosts` kullanmayın. Kurulum sunucusunun `/etc/hosts` dosyasına yazın;
backend/dropt bu dosyayı `/host-etc-hosts` olarak okur (`docs/deployment.md`).


- [ ] Kaynak ve hedef `SECRET_KEY` aynı (tam DB move)
- [ ] `.env` git’e commit edilmedi (`chmod 600`)
- [ ] Zip doğrulama fingerprint eşleşiyor
- [ ] Onay: `VERITABANI GERI YUKLE`
- [ ] Restore sonrası login + credential smoke
