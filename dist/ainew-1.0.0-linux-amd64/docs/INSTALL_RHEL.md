# RHEL 9 Kurulum Rehberi — AINE Altyapı Yönetim Platformu

Bu doküman, ürünü **yeni/boş bir RHEL 9 sunucusuna** kurmak için hazırlanmıştır.
Müşteri ortamlarında tekrarlanabilir kurulum için tasarlanmıştır.

## 1. Gereksinimler

| Kaynak | Minimum |
|---|---|
| İşletim sistemi | RHEL 9.x (x86_64) — Rocky/AlmaLinux 9 ile de uyumludur |
| CPU | 4 çekirdek |
| RAM | 8 GB (Ollama ile yerel LLM kullanılacaksa 16 GB+ önerilir) |
| Disk | 50 GB boş alan (`/var/lib/server_management` altında büyür) |
| Ağ | 80/443 (arayüz), 9090/9091 (Prometheus/Pushgateway) — dahili ağda açık olmalı |
| Yetki | root / sudo |

Ollama ile yerel LLM (opsiyonel AI Chat/Agent özellikleri) kullanılacaksa GPU önerilir
ama zorunlu değildir; CPU ile de (daha yavaş) çalışır.

## 2. Paketin sunucuya taşınması

İki dağıtım yöntemi desteklenir:

### A) Offline paket (internet erişimi olmayan / air-gapped sunucular)

Geliştirme ortamında üretilen `.tar.gz` dosyasını (bkz. `scripts/build-distribution.sh`)
USB, SCP veya dahili dosya paylaşımıyla sunucuya kopyalayın:

```bash
scp ainew-<versiyon>-linux-amd64.tar.gz root@<sunucu-ip>:/root/
ssh root@<sunucu-ip>
tar xzf ainew-<versiyon>-linux-amd64.tar.gz
cd ainew-<versiyon>-linux-amd64
```

Bu paket, önceden derlenmiş tüm Docker imajlarını (`images/*.tar.gz`) içerir —
kurulum sırasında internet/registry erişimi **gerekmez**.

### B) GitHub üzerinden (internet erişimi olan sunucular)

```bash
git clone <repo-url> ainew
cd ainew
```

Bu yolda `images/` dizini bulunmaz; `install-rhel.sh` otomatik olarak kaynak koddan
derler (Docker Hub'a erişim gerekir: Python/Node/Nginx/TimescaleDB/Redis/Prometheus
imajları çekilir).

## 3. Kurulum

```bash
sudo ./install-rhel.sh
```

Betik idempotent'tir — tekrar çalıştırıldığında mevcut `.env`/sertifika dosyalarını
bozmaz, sadece eksikleri tamamlar. Yaptıkları:

1. Docker CE + Compose plugin kurulumu (yoksa, `dnf` ile resmi Docker reposundan)
2. `/var/lib/server_management` altında veri dizinleri
3. `.env` dosyası: `SECRET_KEY`, `POSTGRES_PASSWORD`, `ADMIN_DEFAULT_PASSWORD`
   rastgele üretilir; `CORS_ORIGINS` sunucunun birincil IP'sine göre ayarlanır
4. Self-signed TLS sertifikası (`/var/lib/server_management/certs`) — 10 yıl geçerli
5. `firewalld` üzerinde 80/443/9090/9091 portlarının açılması
6. İmajların yüklenmesi (`docker load`, offline modda) veya derlenmesi (online modda)
7. `docker compose -f docker-compose.prod.yml up -d`
8. Sağlık kontrolü ve giriş bilgilerinin ekrana yazdırılması

Kurulum sonunda ekranda şu bilgiler görünür:

```
Arayüz     : https://<sunucu-ip>
Kullanıcı  : admin
Parola     : <otomatik üretilen parola>
```

**Tarayıcı "bağlantı güvenli değil" uyarısı verecektir** — bu normaldir, çünkü
sertifika self-signed'dır. Kurumsal bir CA sertifikanız varsa adım 5'i atlayıp
`/var/lib/server_management/certs/server.crt` ve `server.key` dosyalarının
üzerine kendi sertifikanızı koyup `docker compose -f docker-compose.prod.yml restart frontend`
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

## 7. Güncelleme (yeni sürüm)

1. Yeni sürümün paketini (`ainew-<yeni-versiyon>-linux-amd64.tar.gz`) sunucuya kopyalayın
2. Mevcut kurulumu durdurun: `docker compose -f docker-compose.prod.yml down`
3. Yeni paketi açıp `.env` dosyanızı **eski kurulumdan yeni dizine kopyalayın**
   (SECRET_KEY/parolalar korunmalı — yenisini `cp .env.example .env` ile üretmeyin!)
4. `sudo ./install-rhel.sh` — mevcut `.env` ve sertifikaları koruyarak yeni imajları
   yükler/derler ve servisleri ayağa kaldırır
5. Veritabanı şeması `Base.metadata.create_all` + idempotent `ALTER TABLE` mantığıyla
   otomatik güncellenir (backend ilk açılışta uygular); manuel migration adımı yoktur

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
