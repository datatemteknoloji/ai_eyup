# ainew — Linux GUIDE

Bu kılavuz **Linux modülü** ve Linux’u ilgilendiren sayfaları anlatır: sunucular, metrik, paket/yama, repo, Ansible, Linux AIOps, SSH kimlikleri, fiziksel host kaydı ve (day-2 için) Level 1.

Sanallaştırma dashboard’u, Windows ve OpenShift menüleri burada yoktur.

---

## Amaç

SSH ile RHEL/Ubuntu benzeri host’ları envantere almak, metrik izlemek, paket/yama/repo ve Ansible çalıştırmak, doğal dil ile teşhis etmek.

**RBAC:** `linux`. Fiziksel ekleme: `integrations`. SSH kimlik: admin Ayarlar. Level 1: `level1`.

---

## Mimari

```diagram
  Ayarlar → Linux SSH          Entegrasyonlar → Fiziksel hostlar
              │                              │
              └──────────┬───────────────────┘
                         ▼
                   /servers  (Linux envanter)
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
           SSH 22    node_exporter  Level 1
           Paramiko   → Prometheus   Dropt :8001
                         │
                    metric_sync
                         ▼
                    metric_data
                         │
              /linux/dashboard  /metrics  /linux/chat
```

Backend `network_mode: host` ile hedefe SSH açar. Konuk VM’ler hypervisor senkronundan `servers`’a düşebilir; fiziksel kayıt entegrasyondandır.

---

## Menüler (Linux grubu)

| Menü | Yol | Ne yapılır |
|------|-----|------------|
| Dashboard | `/linux/dashboard` | Filo sağlık / özet |
| Linux sunucuları | `/servers` | Liste, ekleme, kimlik, AI-ready, terminal, komut |
| Canlı metrik | `/metrics` | CPU, bellek, disk grafikleri |
| Paket & yama | `/packages` | Paket envanteri ve işlem |
| Sistem güncelle | `/system-update` | OS güncelleme |
| Local Repo | `/repositories` | İç RPM/DEB repo |
| Ansible/AWX | `/ansible` | Oyun kitabı / AWX |
| Altyapı raporları | `/linux/reports` | Linux raporları |
| Asistan | `/linux/chat` | “disk dolu”, systemd, named host |
| Komuta merkezi | `/linux/ops` | AIOps özet (kritik rozet) |
| Olaylar | `/linux/events` | Event |
| Incident | `/linux/incidents` | Incident / RCA |
| Analiz | `/linux/analysis` | Analiz araçları |

---

## Linux’u ilgilendiren diğer sayfalar

| Yer | Yol | Neden Linux |
|-----|-----|-------------|
| Ayarlar → Linux SSH | `/settings` | Kullanıcı, anahtar, sudo, varsayılan kimlik |
| Entegrasyonlar → Fiziksel hostlar | `/integrations/physical-hosts` | SSH hedefi ekleme |
| Level 1 | `/level1` … | Disk, LVM, ASM, kullanıcı, servis — **Talep → Preview → Apply** |
| Dashboard (genel) | `/dashboard` | Linux metrikleri kaynak widget’ına girer |
| Kullanıcılar | `/users` | `linux` / `level1` kutusu |

Level 1, `/packages` sayfasının yerine geçmez (farklı motor, Dropt DB).

```diagram
  Linux /packages     = ainew paket motoru
  Level 1 paket/disk  = Dropt sihirbaz + iş kuyruğu
```

---

## Tipik akış

1. Ayarlar → Linux SSH kimliği  
2. Fiziksel host veya `/servers`  
3. node_exporter + Ayarlar → İzleme (Linux Prom job)  
4. `/metrics` veya `/linux/chat` (“sunucu X disk”)  
5. Yama: Sistem güncelle / Paketler  
6. Day-2 LVM: Level 1 → Preview → Apply → İşler  

---

## Sistem / kurulum notu (Linux operatörü)

ainew yönetim hostu Docker Compose ile kurulur (`install-rhel.sh`). Hedef Linux’lar konteyner olmak zorunda değildir; SSH yeter. Ayrıntı Ana GUIDE’dedir.

---

## Limitler

AI-ready olmayan host asistan hedefi olmayabilir. Filo taraması cap + onay. Prometheus scrape sohbet ile değişmez. Windows WinRM bu kılavuzun dışındadır.
