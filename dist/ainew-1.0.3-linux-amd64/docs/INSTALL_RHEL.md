# RHEL 9 Kurulum Rehberi — Altyapı Yönetim Platformu

Bu doküman, ürünü **yeni/boş bir RHEL 9 sunucusuna** kurmak için hazırlanmıştır.
Müşteri ortamlarında tekrarlanabilir kurulum için tasarlanmıştır.

## 1. Gereksinimler

| Kaynak | Minimum |
|---|---|
| İşletim sistemi | RHEL 9.x (x86_64) — Rocky/AlmaLinux 9 ile de uyumludur |
| CPU | 4 çekirdek |
| RAM | 8 GB (Ollama ile yerel LLM kullanılacaksa 16 GB+ önerilir) |
| Disk | 50 GB boş alan (kurulumda seçeceğiniz kurulum dizini altında büyür, varsayılan `/opt/ainew`) |
| Ağ | 80/443 (arayüz), 9090/9091 (Prometheus/Pushgateway) — dahili ağda açık olmalı |
| Yetki | root / sudo |

Ollama ile yerel LLM (opsiyonel AI Chat/Agent özellikleri) kullanılacaksa GPU önerilir
ama zorunlu değildir; CPU ile de (daha yavaş) çalışır.

## 2. Paketin sunucuya taşınması

Üç dağıtım yöntemi desteklenir — hepsi de **tamamen air-gapped (internetsiz) sunucularda**
çalışır, çünkü önceden derlenmiş Docker imajları (`images/*.tar.gz`) her üç yöntemde de dahildir:

### A) Offline tek-dosya paket (USB / SCP / dahili dosya paylaşımı)

Geliştirme ortamında üretilen `.tar.gz` dosyasını (bkz. `scripts/build-distribution.sh`)
USB, SCP veya dahili dosya paylaşımıyla sunucuya kopyalayın:

```bash
scp ainew-<versiyon>-linux-amd64.tar.gz root@<sunucu-ip>:/root/
ssh root@<sunucu-ip>
tar xzf ainew-<versiyon>-linux-amd64.tar.gz
cd ainew-<versiyon>-linux-amd64
```

### B) `git clone` (GitHub'a erişimi olan ama başka registry/internet erişimi olmayan sunucular)

```bash
git clone <repo-url> ainew
cd ainew/dist/ainew-<versiyon>-linux-amd64
```

### C) GitHub "Download ZIP" (tarayıcıdan indirip elle taşıma)

GitHub reposunun "Code → Download ZIP" bağlantısından indirip, ZIP'i air-gapped sunucuya
elle (USB/SCP/dahili paylaşım) taşıyıp açın, sonra `dist/ainew-<versiyon>-linux-amd64/`
klasörüne girin.

> **Not:** `images/*.tar.gz` dosyalarından 90MB'ı aşanlar (GitHub'ın Git LFS'siz 100MB
> sınırı nedeniyle) `.part01`, `.part02`, ... şeklinde parçalara bölünmüş olarak depoda
> tutulur. `install-rhel.sh` bunları kurulumdan önce otomatik olarak birleştirir — elle bir
> işlem yapmanıza gerek yoktur. B ve C yöntemleri Git LFS **gerektirmez**.

## 3. Kurulum

```bash
sudo ./install-rhel.sh
```

Betik idempotent'tir — tekrar çalıştırıldığında mevcut kurulum dizinini/`.env`/sertifika
dosyalarını bozmaz, sadece eksikleri tamamlar. Yaptıkları:

1. Docker CE + Compose plugin kurulumu (yoksa, `dnf` ile resmi Docker reposundan)
2. **Kurulum dizini seçimi** — sizden bir mutlak yol ister (varsayılan `/opt/ainew`).
   Uygulama paketinin TAMAMI (kaynak/derleme dosyaları, imajlar, scriptler) VE tüm
   kalıcı veriler (DB, Redis, Chroma, yüklenen dosyalar, Prometheus, sertifikalar,
   Ollama modelleri) bu **tek** kök dizin altında toplanır — `/var/lib` gibi sistem
   dizinlerine dağılmaz. Paket, çalıştığınız yerden bu dizine kopyalanır (`<dizin>/data/`
   altında veriler). Yeniden çalıştırıldığında (bu dizinden) tekrar sorulmaz —
   `DATA_DIR` ortam değişkeniyle de önceden belirtilebilir (interaktif olmayan kurulumlar için).
3. `.env` dosyası: `SECRET_KEY`, `POSTGRES_PASSWORD`, `ADMIN_DEFAULT_PASSWORD`
   rastgele üretilir; `CORS_ORIGINS` sunucunun birincil IP'sine göre ayarlanır
4. Self-signed TLS sertifikası (`<kurulum-dizini>/data/certs`) — 10 yıl geçerli
5. `firewalld` üzerinde 80/443/9090/9091 portlarının açılması
6. İmajların yüklenmesi (`docker load`, offline modda) veya derlenmesi (online modda)
7. `docker compose -f docker-compose.prod.yml up -d`
8. Sağlık kontrolü ve giriş bilgilerinin ekrana yazdırılması

Kurulum sonunda ekranda şu bilgiler görünür:

```
Arayüz         : https://<sunucu-ip>
Kullanıcı      : admin
Parola         : <otomatik üretilen parola>
Kurulum dizini : /opt/ainew  (paket + .env)
Veri dizini    : /opt/ainew/data  (DB, Redis, Chroma, yüklenen dosyalar, Prometheus, sertifikalar, Ollama)
```

**Tarayıcı "bağlantı güvenli değil" uyarısı verecektir** — bu normaldir, çünkü
sertifika self-signed'dır. Kurumsal bir CA sertifikanız varsa adım 5'i atlayıp
`<kurulum-dizini>/data/certs/server.crt` ve `server.key` dosyalarının üzerine kendi
sertifikanızı koyup `docker compose -f docker-compose.prod.yml restart frontend`
çalıştırabilirsiniz.

## 4. İlk giriş sonrası yapılacaklar

1. `admin` / (otomatik üretilen parola) ile giriş yapın
2. **Ayarlar → Kullanıcılar** üzerinden admin parolasını değiştirin
3. **Ayarlar → Modüller** ile hangi kullanıcının hangi platforma (Linux/Windows/
   Virtualization) erişeceğini yapılandırın
4. Sunucu envanterini ekleyin (SSH/WinRM kimlik bilgileri)
5. `.env` dosyasını güvenli bir yere yedekleyin (`SECRET_KEY` ve DB parolasını içerir —
   kaybolursa mevcut kullanıcı parolaları/token'lar geçersiz olur)

## 5. Ollama (opsiyonel yerel LLM)

AI Chat / AI Agent özellikleri için varsayılan olarak dış bir Ollama sunucusuna
(`OLLAMA_URL`) bağlanılır. Aynı sunucuda yerel Ollama çalıştırmak isterseniz:

```bash
docker compose -f docker-compose.prod.yml --profile ollama up -d ollama
docker compose -f docker-compose.prod.yml exec ollama ollama pull llama3.2:3b
```

`.env` içindeki `OLLAMA_URL=http://127.0.0.1:11434` değerini bu durumda değiştirmenize
gerek yoktur (backend host network kullandığı için Ollama'ya localhost üzerinden erişir).

### Air-gapped (internet erişimi olmayan) sunucularda model taşıma

Modeller pakete/imaja gömülü değildir (multi-GB, imajı gereksiz büyütür). Bunun yerine:

```bash
# İnternet erişimi olan bir makinede, modelleri önceden indirip dışa aktarın:
ollama pull llama3.2:3b
ollama pull nomic-embed-text
./scripts/export-ollama-models.sh                # -> ollama-models.tar.gz

# Tarball'ı bu sunucuya taşıyın (scp/USB), sonra burada geri yükleyin:
./scripts/import-ollama-models.sh ollama-models.tar.gz
docker compose -f docker-compose.prod.yml --profile ollama up -d ollama
```

## 6. Bakım komutları

```bash
# Durum
docker compose -f docker-compose.prod.yml ps

# Loglar
docker compose -f docker-compose.prod.yml logs -f backend

# Yeniden başlatma
docker compose -f docker-compose.prod.yml restart backend

# Durdurma
docker compose -f docker-compose.prod.yml down

# Yedekleme (Postgres)
docker compose -f docker-compose.prod.yml exec db pg_dump -U postgres server_management > yedek_$(date +%F).sql
```

## 7. Güncelleme (yeni sürüm) ve geri alma (rollback)

Kalıcı veri (`DATA_DIR` — DB, Redis, sertifikalar, Ollama modelleri, yüklenen
dosyalar) **asla silinmez / üzerine yazılmaz**. Güncelleme sadece uygulama
dosyalarını ve Docker imaj etiketlerini değiştirir. Her güncellemeden önce
otomatik yedek alınır.

### 7.1 Güncelleme

```bash
# 1) Yeni paket sunucuya
scp ainew-1.0.1-linux-amd64.tar.gz root@<sunucu>:/root/
ssh root@<sunucu>
tar xzf ainew-1.0.1-linux-amd64.tar.gz
cd ainew-1.0.1-linux-amd64

# 2) Mevcut kurulumu güncelle (ör. /opt/ainew)
sudo ./update-rhel.sh --install-dir /opt/ainew
```

`update-rhel.sh` sırasıyla:

1. `$DATA_DIR/backups/pre-update-<eski>-to-<yeni>-<tarih>/` altına yedek alır  
   (`.env`, eski imaj etiketleri, Postgres dump)
2. Yeni paket dosyalarını kurulum dizinine kopyalar (`.env` ve `data/` korunur)
3. `.env` içindeki `BACKEND_IMAGE` / `FRONTEND_IMAGE` etiketlerini yeni sürüme çeker
4. `images/*.tar.gz` ile yeni imajları `docker load` eder (eski imajlar silinmez)
5. `docker compose up -d` + sağlık kontrolü

### 7.2 Geri alma (rollback)

```bash
cd /opt/ainew

# A) Sadece uygulama imajı eski sürüme dönsün (hızlı — genelde yeterli)
sudo ./rollback-rhel.sh

# B) İmaj + veritabanı da güncelleme anındaki hâline dönsün
#    (o andan sonraki TÜM DB değişiklikleri kaybolur — onay ister)
sudo ./rollback-rhel.sh --restore-db

# C) Belirli bir yedeğe dön
sudo ./rollback-rhel.sh --backup /opt/ainew/data/backups/pre-update-1.0.0-to-1.0.1-20260713-153000
```

**Ne zaman `--restore-db`?** Yeni sürüm DB şemasını ileri taşıdıktan sonra
eski imajın şemayla uyumsuz çalıştığı nadir durumlarda. Aksi halde imaj-only
rollback yeterlidir (yeni eklenen sunucu kayıtları vb. korunur).

### 7.3 Manuel kontrol

```bash
cd /opt/ainew
cat VERSION
grep -E 'BACKEND_IMAGE|FRONTEND_IMAGE' .env
docker compose -f docker-compose.prod.yml ps
curl -sf http://127.0.0.1:8000/ | jq .
ls -la data/backups/
```

### 7.4 Eski davranış (referans)

Eski dokümandaki “compose down → yeni paket aç → .env kopyala → install-rhel.sh”
yöntemi hâlâ çalışır ama yedek/rollback sağlamaz; yeni sürümlerde
`update-rhel.sh` / `rollback-rhel.sh` kullanın.

## 8. Bilinen sınırlamalar / güvenlik notları

- Backend, sunuculara SSH ile bağlanabilmek için Docker **host network** modunda
  çalışır — bu nedenle konteyner izolasyonu kısmi olduğundan sunucu güvenlik
  duvarı/erişim kontrolü önemlidir.
- Prometheus (9090) ve Pushgateway (9091) düz HTTP üzerinden, sunucunun tüm
  arayüzlerinde açıktır (arayüzdeki "Prometheus'ta Görüntüle" bağlantısı için).
  Mümkünse bu portları sadece yönetim ağından erişilebilir şekilde `firewalld`
  ile kısıtlayın (`firewall-cmd --zone=... --add-rich-rule=...`).
- PostgreSQL ve Redis portları sadece `127.0.0.1`'e bind edilir (dışarıya kapalı).
- Varsayılan Node Exporter dağıtım paketi sadece **amd64** içerir; ARM tabanlı
  yönetilen sunucular için `backend/static/node_exporter/arm64/` altına ilgili
  binary'nin eklenmesi gerekir.
