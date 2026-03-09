# Server Management / AIOps Platform

Merkezi sunucu yönetimi, AI Chat asistanı, Prometheus metrikleri, RAG (runbook/incident/metrik) ve Linux MCP araçları.

## Gereksinimler

- Docker ve Docker Compose (veya Podman)
- (Opsiyonel) Ollama – AI Chat için; host'ta çalışıyor olmalı

## Tek komutla çalıştırma

```bash
# Tüm servisleri build edip başlat (arka planda)
./run.sh

# veya ön planda (logları görmek için)
./run.sh -f
```

İlk çalıştırmada image'lar build edilir; birkaç dakika sürebilir.

## Servisler

| Servis      | Port | Açıklama |
|------------|------|----------|
| **Frontend** | 3000 | React arayüz: http://localhost:3000 |
| **Backend**  | 8000 | FastAPI API (host network) |
| **PostgreSQL** | 5432 | TimescaleDB |
| **Redis**   | 6379 | Önbellek / kuyruk |
| **Prometheus** | 9090 | Metrikler |
| **Pushgateway** | 9091 | Push metrikleri |

## Ortam değişkenleri (opsiyonel)

Backend için `docker-compose.yml` içinde veya `.env` ile:

- `OLLAMA_URL` – Ollama adresi (varsayılan: http://127.0.0.1:11434). Uzaktan Ollama kullanıyorsanız: `http://<ollama-sunucusu-ip>:11434`
- `OLLAMA_DEFAULT_MODEL` – Chat modeli (örn. llama3.2:3b)
- `PROMETHEUS_URL` – Prometheus adresi
- `RAG_CHROMA_PATH` – RAG vektör veritabanı dizini

## Ollama (AI Chat için)

AI Chat'in yanıt verebilmesi için Ollama'nın çalışıyor olması gerekir.

### Sadece bu makinede (localhost)

```bash
ollama serve
ollama pull llama3.2:3b
ollama pull nomic-embed-text   # RAG için (opsiyonel)
```

### Dışarıdan / ağdaki başkalarının da kullanması

Ollama'yı **tüm ağ arayüzlerinde** dinletebilirsiniz; böylece aynı ağdaki diğer bilgisayarlar da bu sunucudaki Ollama'ya bağlanabilir.

**Seçenek 1 – Host'ta (sistemde kurulu Ollama):**

```bash
# 0.0.0.0 = tüm IP'lerde dinle (sadece güvendiğiniz ağda kullanın)
OLLAMA_HOST=0.0.0.0 ollama serve
```

Diğer makineler: `http://<bu-sunucunun-ip>:11434` (örn. `http://192.168.1.100:11434`).

**Seçenek 2 – Docker ile Ollama:**

```bash
# Ollama container'ını başlat (OLLAMA_HOST=0.0.0.0 ile aynı davranış)
docker compose --profile ollama up -d ollama
```

Yine `http://<sunucu-ip>:11434` adresinden erişilir. Backend aynı host'ta çalışıyorsa `OLLAMA_URL=http://127.0.0.1:11434` yeterli; backend farklı makinedeyse `OLLAMA_URL=http://<ollama-sunucusu-ip>:11434` verin.

**Backend'in kullandığı adres:** `OLLAMA_URL` ortam değişkeni (docker-compose veya `.env`). Örnek: `OLLAMA_URL=http://192.168.1.100:11434`.

**Bağlantı kurulamıyorsa (curl: Failed to connect):**

1. **Ollama sadece localhost'ta dinliyor olabilir.** Systemd ile kalıcı çözüm (sunucuda bir kez çalıştırın; proje dizininden veya `PROJE` yerine proje yolunu yazın):
   ```bash
   cd /path/to/ainew   # proje dizinine geçin
   sudo cp scripts/ollama-listen-all.conf /etc/systemd/system/ollama.service.d/ && sudo systemctl daemon-reload && sudo systemctl restart ollama
   ```
   Veya tek satırda tam yol: `sudo cp /path/to/ainew/scripts/ollama-listen-all.conf /etc/systemd/system/ollama.service.d/ && sudo systemctl daemon-reload && sudo systemctl restart ollama`
   Sonra `ss -tlnp | grep 11434` ile `0.0.0.0:11434` görünmeli.
2. **Ollama hiç çalışmıyorsa:** Docker: `docker compose --profile ollama up -d ollama` (proje dizininde). Host: `OLLAMA_HOST=0.0.0.0 ollama serve`.
3. **Firewall:** Dışarıdan hâlâ bağlanamıyorsanız 11434'ü açın: `sudo ufw allow 11434/tcp && sudo ufw status` veya `sudo firewall-cmd --add-port=11434/tcp --permanent && sudo firewall-cmd --reload`.

## Ansible/AWX Entegrasyonu (Opsiyonel)

**Toplu komut çalıştırma** ve **playbook yönetimi** için Ansible + AWX entegrasyonu mevcuttur.

### Ansible Ad-Hoc Komut (Yerelde)

Backend'de Ansible kurulu. Seçili sunucularda ad-hoc komut çalıştırabilirsiniz:

- **Ansible/AWX** sayfasından sunucu seçin
- Modül (shell, yum, apt vb.) + argümanları yazın
- "Komutu Çalıştır" ile tüm sunucularda aynı anda çalışır

**Örnek kullanımlar:**
- Module: `shell`, Args: `"uptime"`
- Module: `yum`, Args: `"name=vim state=present"`, Become: ✓
- Module: `service`, Args: `"name=nginx state=restarted"`, Become: ✓

### AWX Job Template (Playbook)

AWX URL/credential ayarlandığında AWX'teki job template'leri listeleyip çalıştırabilirsiniz.

1. `.env` veya docker-compose environment'a ekleyin:
   ```bash
   AWX_URL=https://awx.example.com
   AWX_USERNAME=admin
   AWX_PASSWORD=your-password
   AWX_VERIFY_SSL=true
   ```

2. **Ansible/AWX** sayfasından:
   - Job Template seçin
   - (Opsiyonel) Sunucu seçimi → limit parametresi
   - (Opsiyonel) Extra Vars (JSON)
   - "Job Başlat" → AWX'te job çalışır, durum takibi yapılır

**Faydaları:**
- Ansible ping ile SSH check (Global Credential uygulamada kullanılabilir)
- Toplu komut: tüm sunuculara aynı anda `uptime`, paket kurma, servis yönetimi
- AWX playbook: karmaşık otomasyon (örn: patch, backup, config deploy)

## Özellikler

- **Sunucular:** CRUD, health check, AI Ready, Node Exporter kurulumu
- **AI Chat:** Ollama, RAG (runbook / incident / metrik), Markdown + tablo, CSV indirme
- **Ansible/AWX:** Toplu komut çalıştırma (ad-hoc), playbook çalıştırma (AWX job template), SSH check
- **RAG:** Runbook ingest, incident/event indexleme, metrik açıklamaları; Ayarlar → RAG
- **Canlı metrikler:** Prometheus grafikleri
- **Hypervisor'lar:** oVirt / VMware entegrasyonu
- **Events / Incidents:** Olay ve incident yönetimi

## Dizin yapısı

```
ainew/
├── backend/          # FastAPI (app/api, app/services, app/models)
├── frontend/         # React + Vite + Tailwind
├── prometheus/       # prometheus.yml, targets
├── docs/             # RAG_KULLANIM.md vb.
├── docker-compose.yml
└── run.sh            # Tek komutla başlatma
```

## RAG kullanımı

- **Ayarlar → RAG:** Metrik açıklamalarını yükle, incident/event indexle
- **Chat:** RAG açık/kapalı toggle; tablolar Markdown + "CSV / Excel olarak indir"
- Detay: [docs/RAG_KULLANIM.md](docs/RAG_KULLANIM.md)

## Durdurma

```bash
docker-compose down
```

Veriler (PostgreSQL, Redis, Prometheus, Chroma) volume'larda kalır; tekrar `./run.sh` ile aynı verilerle devam edersin.
