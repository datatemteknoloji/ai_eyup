## 3. Conceptual Architecture

### 3.1 Domain’ler (iş)

Dashboard · Yönetici / AI · Linux · Windows · Sanallaştırma · Exadata · OpenShift · Level 1 · Entegrasyonlar · Uygulamalar · Bilgi bankası · Özel raporlar · Denetim · Kullanıcılar · Ayarlar.

### 3.2 Building blocks

SPA · `/api/v1` · envanter/metrik store · AI (routing + tool + RAG) · Dropt iş motoru · Prometheus.

### 3.3 Dış sistemler

vCenter · oVirt/OLVM · Proxmox · Hyper-V · OpenShift API · SSH · WinRM · UCMDB · Ansible/AWX · Prometheus · isteğe bağlı AD/SSO · isteğe bağlı uzak LLM.

### 3.4 Aktörler

İnsan operatör, admin, senkron görevleri, Celery, Dropt worker, LLM.

---

## 4. Logical Architecture

```diagram
  ┌─────────────┐   JSON / SSE    ┌─────────────┐   SQL / Redis    ┌──────────┐
  │  Frontend   │ ──────────────► │  Backend    │ ───────────────► │  Store   │
  │  React+Nginx│ ◄────────────── │  FastAPI    │ ◄─────────────── │ Timescale│
  └─────────────┘   JWT cevap     │  /api/v1    │                  │ Redis    │
                                  └──────┬──────┘                  └──────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
              Integration           AI / LLM              Level 1
              SSH Paramiko          Ollama / uzak         Dropt API
              WinRM                 LangGraph ajan        ayrı DB
              vCenter SOAP          pgvector RAG
              oVirt REST            PromQL (salt okunur)
              OCP kube API
```

### 4.1 Frontend

React SPA, port **3000**. Nginx statik dosya + `/api/v1` vekili. Dil TR/EN. Üretim imajı **baked** — kaynak değişince rebuild.

### 4.2 Backend

Python FastAPI, port **8000**, `network_mode: host` (SSH NAT’siz). `backend/app/api/` REST; `services/` iş kuralı; `models/` ORM; `core/` JWT, şifreleme, config.

### 4.3 API

REST + sohbet **SSE**. JWT Bearer. Açık: `/api/v1/auth/*`, `/health`.

### 4.4–4.5 AuthZ

JWT + rol. Admin = tüm modüller. `user_modules` menüyü ve sohbet tool kapsamını keser. Level 1 denetim/ayar admin.

### 4.6 Database

Tek ainew DB: kullanıcı, sunucu, virt, `metric_data` (Timescale), olay, pgvector. Dropt: ayrı Postgres.

### 4.7–4.10 Entegrasyon, AI, job, izleme

Bağlayıcılar şifreli kimlik kullanır. Arka plan: health, metric sync, anomali, VM senkron, Celery. Prometheus scrape sohbet ile değişmez.

---

## 5. Component Architecture

| Bileşen | Sorumluluk |
|---------|------------|
| `Layout.tsx` / `pages/` | Sol menü ve ekranlar |
| `app/api` | HTTP, doğrulama, rol |
| `app/services` | SSH, virt, AIOps, ajan, NLQ |
| `app/models` / `core` | Şema, JWT, Fernet |
| Celery worker | Filo / uzun iş |
| Dropt | Level 1 sihirbaz + SSH job |
| Nginx frontend | SPA + API proxy |
| Timescale / Redis / Prom / Ollama | Durum, kuyruk, metrik, çıkarım |

---

## 6. Data Architecture

```diagram
  node_exporter / windows_exporter
              │  scrape
              ▼
         Prometheus
              │  metric_sync
              ▼
         metric_data (Timescale)
              │
              ▼
     Dashboard / Linux-Windows sohbet

  vCenter / OLVM / diğer hypervisor API
              │  sync-vms
              ▼
     servers + virt_* tablolar
              │
              ▼
     Sanallaştırma dashboard / rapor / virt sohbet
```

Sahiplik: ainew DB ≠ Dropt DB ≠ Prometheus TSDB. Redis: iptal bayrağı, kuyruk. Saklama: Ayarlar (tipik 30 gün).

---

## 7. Integration Architecture

| Sistem | Nereden bağlanır | Protokol |
|--------|------------------|----------|
| vCenter | Entegrasyonlar → vCenter/OLVM | HTTPS/SOAP 443 |
| oVirt / OLVM | Aynı sayfa, tip `kvm` | REST 443 |
| Proxmox | Aynı sayfa | REST 8006 |
| Hyper-V | Aynı sayfa | WinRM 5985 |
| OpenShift / KubeVirt | Entegrasyonlar → OpenShift | kube API |
| Linux | Ayarlar → SSH + `/servers` | SSH 22 |
| Windows | Ayarlar → WinRM | 5985/5986 |
| UCMDB | Entegrasyonlar → UCMDB | import |
| Ansible/AWX | Linux/Windows Ansible menüsü | API |
| Prometheus | Ayarlar → İzleme | PromQL okuma |
| Dropt | `DROPT_API_URL` | REST :8001 |

`hostname` görünen ad olabilir; bağlantı için **çözümlenebilir IP/FQDN** gerekir.

---

## 8. AI Architecture — model nasıl çalışır

Sohbet bir “sohbet botu” değildir. Soru **yönlendirilir**; yanıt tool, canlı bağlayıcı ve (varsa) bilgi bankası ile üretilir.

```diagram
                    UYGULAMA / ENVANTER / METRİK
                           │
                           ▼
                 Senkron + connector katmanı
                 (DB, vCenter, SSH, OCP, …)
                           │
                           ▼
                    ainew bilgi katmanı
                           │
                 ┌─────────┴─────────┐
                 ▼                   ▼
          RAG (runbook /          Tool sonuçları
          incident / metrik       (isimli varlık)
          açıklaması)
                 │                   │
                 └─────────┬─────────┘
                           ▼
                     Context Builder
                           │
  KULLANICI SORUSU ───────►│
                           ▼
                    Intent / Routing
                    (modül, kapsam, platform)
                           │
               ┌───────────┼───────────┐
               ▼           ▼           ▼
            RAG Docs    Tool Calls   Live Data
                           │
                    vCenter / OLVM /
                    SSH / WinRM /
                    OpenShift / PromQL
                           │
                           ▼
                     LLM (üretim)
                  Ollama  veya  REMOTE_LLM
                           │
                           ▼
                        YANIT (SSE)
```

### 8.1–8.2 LLM ve yönlendirme

- **Yerel:** `OLLAMA_URL` (varsayılan `http://127.0.0.1:11434`), model sohbet ekranından veya Ayarlar’dan  
- **Uzak:** Ayarlar → AI → `REMOTE_LLM_URL` + model; OpenAI uyumlu geçit  
- Embedding (RAG): `nomic-embed-text` — Ollama gerekir (chat uzak olsa bile)  
- Fail-fast: uzak kopunca sessiz local yok  

### 8.3–8.5 Prompt, context, tool

Sistem istemi + RBAC kapsamı + seçili sunucu/hypervisor adı + tool çıktısı + isteğe bağlı RAG chunk. Ajan (`/agent`) LangGraph; yıkıcı araç **onay** ister.

### 8.6–8.9 Retrieval ve cevap

Önce DB / senkron tablo; canlı API tek adlı varlık. “Tüm sunucular” cap + onay. Cevap SSE; iptal edilebilir; admin token görebilir.

### 8.10–8.11 Token ve hata

Açık hata mesajı. Prometheus: yalnızca sorgu.

**Sohbet yüzeyleri**

| Yer | Yol |
|-----|-----|
| Tüm altyapı | `/chat` |
| Linux | `/linux/chat` |
| Windows | `/windows/aiops/chat` |
| Sanallaştırma | `/virt/chat` |
| Exadata | `/exadata/chat` |
| OpenShift | `/openshift/chat` |
| Ajan | `/agent` |

---

## 9. Security Architecture

JWT · modül RBAC · Fernet ile kimlikler · CORS · backend host ağında `:8000` (üretimde güvenlik duvarı / ters vekil). GUIDE sır dökmez. Level 1: ainew JWT → Dropt token (`AINEW_BRIDGE_SECRET`).

---

## 10. Deployment Architecture

```diagram
                    ┌─ docker compose up -d ─┐
                    │                        │
                    ▼                        ▼
            ainew yığını              Dropt yığını
         (include dropt yml)         (ayrı network)
                    │                        │
                    ▼                        ▼
              DATA_DIR/                 DATA_DIR/dropt/
```

Geliştirme: `docker-compose.yml` (backend source mount). Üretim: `docker-compose.prod.yml` + `install-rhel.sh`. Test ayrı ürün profili değildir; aynı şablon farklı host/secret.

**Docker mı Podman mı?** Desteklenen **çalıştırma** Docker Compose’tur. Offline imajlar `docker load` veya `podman load` ile yüklenebilir. Compose’u podman-compose ile “resmi destek” iddiası yoktur. OpenShift’e ainew’in kendisini operator olarak kurmak yoktur; ainew **OpenShift’i yönetir**.

---

## 11. Operational Architecture

Log: konteyner stdout. Health: `GET /health`. Metrik sync + AIOps anomali (Z-score/IQR).

| Belirti | İlk bakış |
|---------|-----------|
| UI eski | `docker compose build frontend && up -d` |
| API değişmedi | `docker restart server_management_backend` |
| Sohbet LLM | Ayarlar → AI; Ollama / uzak URL |
| VM yok | Entegrasyonlar → hypervisor; FQDN; senkron |
| Level 1 iş yok | Dropt :8001, köprü, eşleme |
| Metrik boş | exporter + Prom job (sohbet değil) |
