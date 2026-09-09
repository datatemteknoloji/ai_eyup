# ainew — Windows GUIDE

Yalnızca **Windows Yönetimi** modülü: dashboard, sunucular, metrik, Event Log, Update, Ansible, rapor, Windows AIOps.

Linux SSH, Sanallaştırma ve OpenShift burada yoktur.

**RBAC:** `windows`. Kimlik: **Ayarlar → WinRM** (admin).

---

## Mimari

```diagram
  Ayarlar → WinRM
        │
        ▼
  /windows  (envanter)
        │
   ┌────┼────────────┐
   ▼    ▼            ▼
 WinRM  windows_     Event Log
 5985   exporter     senkron
        │
        ▼
   Prometheus → metric_data
        │
  /windows/dashboard
  /windows/live-metrics
  /windows/aiops/chat
```

---

## Menüler

| Menü | Yol | Ne yapılır |
|------|-----|------------|
| Dashboard | `/windows/dashboard` | Filo özeti |
| Windows sunucuları | `/windows` | Envanter, bağlantı, AI-ready |
| Canlı metrik | `/windows/live-metrics` | CPU / bellek / disk |
| Event Log | `/windows/events` | Windows olayları |
| Windows Update | `/windows/updates` | Güncelleme durumu / işlem |
| Ansible/AWX | `/windows/ansible` | Windows otomasyon |
| Raporlar | `/windows/reports` | Rapor |
| Asistan | `/windows/aiops/chat` | WinRM + log bağlamı |
| Komuta / olay / incident / analiz | `/windows/aiops/ops` … `/analysis` | AIOps |

---

## Tipik akış

WinRM kimlik → sunucu ekle (firewall 5985/5986) → Event Log veya asistan → Update sayfası.

---

## Limitler

Linux `/servers` Windows’u yönetmez. Level 1 sihirbazları Linux day-2 içindir. Exporter yoksa canlı metrik boş kalır.
