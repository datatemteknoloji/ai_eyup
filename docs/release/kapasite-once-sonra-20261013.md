# Kapasite önce/sonra karşılaştırması — v1.0.9.41 ↔ güncel `main` (E2, E3, E6)

Tarih: 2026-10-13 · Salt okunur ölçüm; aynı veritabanı, aynı anda iki kod ağacı (`v1.0.9.41` etiketi ve `main`).
Kapsam: `build_capacity` (cluster sayıları, N+1, runway/tahmin), `simulate` (nereye sığar, en fazla N, sınırlayıcı), `host_failure_matrix` (N+1 tablosu).

## Ortam (ölçüm anındaki veri)

| Instance | Cluster | Platform | Not |
|---|---|---|---|
| 7 | Default | OLVM | tek host |
| 6 | oVirt | OpenShift Virt | 3 host |
| 2 | (cluster yok) · 192.168.1.101 | vCenter | bağımsız host (HA/admission control politikası yok) |

Profiller: 2 vCPU/8 GB/100 GB ×1 · 8/32/0 ×1 · 16/64/500 ×10 · 4/16/0 ×50 (3 cluster × 4 = 12 satır).

## Sonuç

| Bölüm | Karşılaştırılan | Fark |
|---|---|---|
| Cluster sayıları (bellek/CPU, HA rezervi, N+1 durumu, runway/tahmin) | 3 cluster | **0 fark** |
| N+1 (host arızası) tablosu | 3 cluster | **0 fark** |
| Nereye sığar / en fazla N / sınırlayıcı / karar | 12 satır | **0 fark** (karar, `max_fit`, `limiting` aynı) |

## Fark olan satırlar ve nedenleri

| Satır | Önce (v1.0.9.41) | Sonra (main) | Neden |
|---|---|---|---|
| 6/oVirt — 4 sonuç satırı | `cpu_request` alanı yok | `cpu_request` = oran 10, kaynak `default`, etiket "varsayılan değer 10 (HyperConverged okunamadı; ölçülmedi)" | **vCPU oranı (E6)**: oran artık etiketli gösteriliyor. HyperConverged bu ortamda okunamadığı için değer varsayılan (10) kaldı → sayısal sonuç değişmedi. |
| 7/Default ve 6/oVirt — (4,16,0)×50 satırında `placed[].vm` numaraları | 1,2,3,… | 1,10,11,12,… (ara sürüm) | **Yerleşim çekirdeği (E2)**: eşit boyutlu VM'lerde eşitlik bozucu metin sıralamasıydı. Kapasiteye etkisi yok (VM'ler özdeş) ama etiketler sıra dışıydı → **düzeltildi** (sayısal VM no doğal sırada); düzeltmeden sonra 0 fark. |

## Bu ölçümde SINANMAYANLAR (dürüst not)

- **Ayrılmış failover host (E3)** ve **HA slot (E3)**: ortamdaki tek vCenter girdisi HA politikası olmayan bağımsız host. Bu iki kural gerçek veriyle çalışmadı; yalnızca birim testleriyle (`test_dedicated_hosts_slots_e3.py`) doğrulandı. HA/slot politikalı bir vCenter cluster'ı eklendiğinde bu satırların değişmesi BEKLENİR (ayrılmış host yerleşime kapanır; boş slot yoksa "Sığmaz — HA slot").
- **vCPU oranı (E6)** gerçek HyperConverged okumasıyla çalışmadı (okunamadı → varsayılan etiketi).
- Yerleşim çekirdeği (E2) için vCenter çoklu host/datastore senaryosu bu ortamda yok; eşdeğerlik testleri (`test_placement_equivalence_e2.py`) dört yolun aynı kararı verdiğini doğrular.

## Yöntem

`git archive v1.0.9.41 backend/app` ayrı dizine açıldı; aynı betik (`build_capacity`, `simulate`, `host_failure_matrix`) iki ağaçta aynı DB ile çalıştırıldı, çıktılar derin karşılaştırıldı. Veritabanına yazma yapılmadı.
