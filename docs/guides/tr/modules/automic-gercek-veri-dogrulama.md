# Automic — gerçek veriyle doğrulama listesi (Adım 1c + altyapı)

Bu dosya Adım 1c maddeleri ile altyapı (R1–R6 / U1–U9) doğrulamalarını **tek yerde** toplar.
Her madde: ne doğrulanacak, nasıl, sonuç (boş — sahada doldurulur).

Kaynak: resmi 24.4 şema (`docs/official/24.4/`). Salt okuma; standby önerilir.

---

## 1. Kullanıcı kimliği

| # | Ne | Nasıl | Sonuç |
|---|----|-------|-------|
| 1.1 | `AH_USR_Idnr` = `OH_Idnr` (OType=USER) mi? | Örnek RunID: `SELECT AH_USR_Idnr FROM AH WHERE AH_Idnr=:r`; `SELECT OH_Idnr, OH_Name, OH_OType FROM OH WHERE OH_Idnr=:id`. AWI kullanıcı adıyla karşılaştır. | |
| 1.2 | Client uyumu (AH_Client vs OH_Client) | Aynı sorgu; eşleşmeyen oran collector uyarısıyla karşılaştır. | |

---

## 2. Durum kodları

| # | Ne | Nasıl | Sonuç |
|---|----|-------|-------|
| 2.1 | 1800–1899 / 1900–1999 / 1850–1851 grupları | `UC_SGRP` veya AWI Task Status; `docs/official/24.4/STATUS_CODES_SEARCH.md`. | |

---

## 3. Agent / HOST

| # | Ne | Nasıl | Sonuç |
|---|----|-------|-------|
| 3.1 | `HOST_Active` anlamı (1=bağlı?) | AWI agent listesi ile `SELECT HOST_OH_Idnr, HOST_Active, HOST_TcpIpAddr FROM HOST` karşılaştır. | |
| 3.2 | Yaşam sinyali = `MQSRV` Type=8 `LastUpdate`? | Agent adı: `SELECT MQSRV_Name, MQSRV_Type, MQSRV_LastUpdate FROM MQSRV WHERE MQSRV_Type=8`. AWI “last check” ile. | |
| 3.3 | `HOST_HostName` doluluk / anlam | `SELECT HOST_HostName, HOST_TcpIpAddr FROM HOST WHERE HOST_HostName IS NOT NULL`. | |
| 3.4 | `HOST_JobCnt` anlamı | **Ekranda/sohbette kullanılmıyor** (belirsiz). AWI “running jobs” ile karşılaştır; netleşince ayrı adımda eklenir. | |
| 3.5 | `HOST_Version` = agent sürümü | AWI agent properties. | |

---

## 4. Fiili agent vs grup

| # | Ne | Nasıl | Sonuç |
|---|----|-------|-------|
| 4.1 | Gruplu işte `AH_HGDst` dolu, `AH_HostDst` fiili agent mi? | Hostgroup’lu JOBS seç → `SELECT AH_HostDst, AH_HGDst FROM AH WHERE AH_Idnr=:r`. AWI Statistics. | |
| 4.2 | `EH_HostDst` / `EH_HGDst` aynı mantık | Aktif iş için EH. | |

---

## 5. Engine / MQSRV

| # | Ne | Nasıl | Sonuç |
|---|----|-------|-------|
| 5.1 | `MQSRV_Type` kodları (1 CP, 2 WP, 4 PWP, 8 Agent, 16 JWP, 32 REST, 64 JCP) | `SELECT MQSRV_Type, COUNT(*) FROM MQSRV GROUP BY MQSRV_Type`. AWI System Overview. | |
| 5.2 | Process “aktif” kodlaması | Şemada durum enum yok; varlık + `LastUpdate` tazeliği. Sahada eşik doğrula. | |
| 5.3 | `MQSRV_ConnCnt` = bağlantı sayısı? | CP satırı vs AWI. | |
| 5.4 | Engine sürümü MQSRV’de yok | Kurulumda girilen `ae_version` kullanılır — onayla. | |

---

## 6. Agent grupları

| # | Ne | Nasıl | Sonuç |
|---|----|-------|-------|
| 6.1 | `OHG` + `OHGF` (Type=H) üyelik | `OHGF_Type='H'` satırları AWI agent group members ile. | |
| 6.2 | Filtre satırları (Type=F) | İlk sürümde üyelik olarak saklanmıyor — gerekirse genişlet. | |

---

## 7. Client yetkileri (sonraya bırakıldı)

| # | Ne | Nasıl | Sonuç |
|---|----|-------|-------|
| 7.1 | `OHAA` / `HACL` | İlk sürümde **yok**. Şema: `docs/official/24.4/OHAA.md`, `HACL.md`. | |

---

## 8. AWI

| # | Ne | Nasıl | Sonuç |
|---|----|-------|-------|
| 8.1 | AWI sunucu envanteri DB’de yok | Elle tanım + HTTP sağlık. Onay. | |

---

## 9. Ekip / archive

| # | Ne | Nasıl | Sonuç |
|---|----|-------|-------|
| 9.1 | `OH_Archive1` / `OH_Archive2` kurumsal kullanımı | Örnek nesneler; ekip kuralı için uygun mu? | |
| 9.2 | Kullanıcı adındaki `/` sonrası = departman | Resmi alan değil; kurumda tutarlı mı? | |

---

## 10. Performans / satır sayıları

| # | Ne | Nasıl | Sonuç |
|---|----|-------|-------|
| 10.1 | HOST / MQSRV / OHG / OHGF satır sayıları | `SELECT COUNT(*) FROM HOST` (vb.). Eşik varsayılan 10.000. | |
| 10.2 | Küçük tablo tam okuma planı | `explain_plans` + `small_ref_tables` risk raporu. | |
