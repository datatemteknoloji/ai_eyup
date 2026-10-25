# Yönetici Raporu — sayfa yeniden tasarımı

Onaylandı (25 Ekim 2026). Bu dosya tasarımın kaynağıdır. Faz 1 veri kuralları `docs/plans/executive-reports.md` içinde durur; çelişirse bu dosya yalnız yönetici sayfası ve yönetici paketi için geçerlidir.

Kullanıcı uygulama yöneticisi değildir. OpenShift, sanallaştırma ve Linux ekiplerinin üstündeki firma yetkilisidir. İlk ekranda, kaydırmadan, şunların özeti görünür: kritik risk var mı, açık kritik kaç gündür açık, önümüzdeki aylarda ne geliyor, yatırım gerekecek mi, kaynak nerede boşa gidiyor, geçen aya göre iyiye mi gidiyoruz. Okuma hedefi 60 saniye.

## Kilitlenen okuma

- Tek sayfa `/executive` olur. `/executive/reports` oraya yönlenir. İkisi de yalnız son kilitli paketi okur. Açılışta canlı hesap yapan yönetici ekranı kalmaz.
- Dashboard, ekip raporları (`/infra-reports`, `/linux/reports`, `/windows/reports`, `/exadata/reports`), özel raporlar ve sohbet aynı kalır. Kod, formül, katalog, çıktı ve ekran değişmez.
- Yönetici paketi mevcut motorların hesap fonksiyonlarını salt okur çağırabilir. İmza ve davranış değişmez. Değişiklik gerekiyorsa fonksiyon yönetici modülünde yazılır.
- Test: aynı girdiyle `report_engine` ve `platform_report_engine` JSON'u değişiklikten önce ve sonra birebir aynıdır. Ekip raporundaki bir sorun (Linux raporundaki eski not formülü dahil) düzeltilmez; final raporda «Ekip raporları için not» altında listelenir.
- Yeni sağlık notu yalnız yönetici modülündedir. `health_score.py` dashboard ve ekip raporlarında durur.
- Durum: skor 75 ve üstü Normal, 55–74 Dikkat, 54 ve altı Kritik. İzlenen varlık yoksa İzleme yok. Veri yoksa Ölçülemedi. Harf notu ana ekranda yok; skor yalnız detay ve (i) içindedir.
- Ek kural: alanda en az bir varlıkta açık kritik varsa alan en az Dikkat olur; ortalama ne olursa olsun. Bu cümle (i) içindedir.
- Dönem: içinde bulunulan ay son `executive_bundle`. Geçmiş ay `executive_monthly`. «Şimdi yenile» yalnız güncel paketi üretir.
- Ana ekranda ham log, IP, kullanıcı adı ve user-agent yok. Varlık adı yalnız detay panelinde ve atıl kaynak ilk 10 tablosunda.
- Model rakam yazmaz. `{kapali_vm}` gibi yer tutucu yazar. Backend `display` değerini basar. Mevcut sayı kapısı sonucu denetler. Geçmezse şablon cümle, «şablon» işaretiyle `summary` kolonuna yazılır. Sayfa model çağırmaz.
- Grafik Recharts. Yeni kütüphane yok. Runway, çubuk üzerinde erken–geç aralık çizgisidir.
- Exadata bu sayfada yok. Kartlar OpenShift, sanallaştırma, Linux, Windows.
- Kapsam rozeti 12 bölüm sayar: özet, dört alan, kapasite, yatırım, takvim, risk, atıl kaynak, olay, veri kapsamı.
- OpenShift notu bu turda küme olaylarından hesaplanır. OpenShift senkronuna ve yeni API çağrısına dokunulmaz. Kartta ve (i) içinde şu cümle durur: «Bu not küme olaylarından hesaplanıyor. Red Hat'in önerdiği alert tabanlı ölçüm henüz toplanmıyor; not gerçekte olduğundan kötü görünebilir.»
- Önizleme modu ve ayrı önizleme düğmesi yoktur. Aşağıdaki demo kart kuralı geçerlidir.

## Sorun

Mevcut sayfa veri dökümüdür: ham log satırları (kullanıcı adı, IP, user-agent), değişken adları (`hosts_needed`, `wasted_vcpu`, `powered_off`, `auto_closed`), sayı listesi halinde şablon («Atıl kaynak: 29, 126, 5848, 403,4.»), ham olay sayıları, grafik yok, ekip bazında görünüm yok, detaya inilemiyor. Veri hazırlığı paneli sayfanın üstünü kaplıyor. «Altyapı raporları» her kartta sanallaştırma rapor sayfasına gider.

## Kapsam sınırı

Yalnız yönetici modülü değişir. Ekip raporlarına, özel raporlara, dashboard'a ve sohbete dokunulmaz.

Yönetici paketinin bugünkü üç ürünü (`report_engine`, `platform_report_engine`, yönetici paketi) ve iki ekranı (`/executive` canlı özet, `/executive/reports` kilitli paket) bu işte şöyle kapanır: yönetici modülünde tek sayfa, tek kilitli kaynak, tek not fonksiyonu. Ekip raporları kendi formülleriyle kalır.

## Mimari (UI'dan önce)

1. **Tek sayfa, tek kaynak.** Sayfa yalnız `executive_bundle` (`status=locked`) okur. `/executive` bu sayfadır. `/executive/reports` yönlenir. Açılışta `executive_summary` canlı hesaplanmaz.
2. **Tek not fonksiyonu.** Yönetici paketi ve sayfa aynı fonksiyonu çağırır. Formül: varlık (node, host veya sunucu) bazında tekilleştirilmiş ceza `min(100, 30×kritik + 12×uyarı)`; varlık skoru `100 − ceza`; platform notu varlık skorlarının ortalaması. Bilgi cezaya girmez. Popülasyon boşsa veya izleme yoksa skor yok, etiket İzleme yok veya Ölçülemedi. Açık kritik varlık, ortalamadan bağımsız, alanı en az Dikkat yapar. (i): «Bu durum altyapı sağlığını gösterir, ekip performansını değil.» Ayrıca notun yönetici raporuna özgü olduğu ve ekip raporlarındaki nottan farklı olabileceği yazılır. Eski formül (ceza popülasyona bölünür) ile yeni formülün canlı dağılımı final rapora konur.
3. **Riskler bulgu modelinden.** «Öncelikli riskler» ve A1'deki ilk beş, ham `system_events` başlığından değil `infra_findings` açık bulgularından gelir. Sıra kural tabanlıdır: şiddet × açık kalma süresi × etki. Ham olay yalnız tekilleştirilmiş günlük trend içindir.
4. **Aylık kilit.** Zamanlayıcı günlük `executive_bundle` üretmeye devam eder (güncel durum). Ay döndüğünde önceki ayın paketi `executive_monthly` olarak kilitlenir; `save_monthly_snapshot` zamanlayıcıya bağlanır. Ay-ay fark yalnız iki `executive_monthly` arasındadır. Canlı olaylardan geçen ay doldurulmaz.
5. **AI özeti üretimde.** Metin, zamanlayıcı ve «Şimdi yenile» sırasında yer tutucu ile üretilir, sayı kapısından geçer, `summary` kolonuna yazılır. Sayfa yalnız okur. Kapıdan geçmezse şablon cümle yazılır ve şablon diye işaretlenir.
6. **OpenShift pakette.** Ekip kataloğu beklenmez. Paket alert, node durumu ve envanteri son senkron tablolarından toplar. Bu turda not küme olaylarındandır. Yeni dış çağrı yok.
7. **Detay pakette.** JSON toplamların yanında detay listelerini taşır: cluster ve depolama satırları, alan bazında varlık listesi (ilk N), ilk 10 atıl öğe, risk detayları, günlük seriler. Boyut sınırı ve ilk N yapılandırılabilir.

## Değişmez kurallar

0. Yönetici sayfasından başka modül sayfasına bağlantı yok. `/infra-reports`, `/linux/reports`, `/windows/reports`, `/exadata/reports`, `/custom-reports` dahil. Test: render edilen sayfada bu route'lara giden `href` yok. Mevcut «Altyapı raporları» bağlantıları kalkar. Detay aynı sayfada, sağdan açılan paneldedir.
1. Sayılar backend'dedir. AI yalnız yer tutucu yazar.
2. Ham log, kullanıcı adı, IP, user-agent ve hostname listesi ana ekranda yok (test).
3. Ekranda değişken veya anahtar adı yok (test: render edilen metinde `snake_case` yok). Her sayı Türkçe etiket ve birimle.
4. Sayı biçimi `tr-TR`: `533.816`, `403,4 GB`, `%72`. Büyük değer okunur birimle: `5,7 TB`.
5. Ham olay sayısı ana ekranda yok. Olay bilgisi tekilleştirilmiş sorun sayısı ve trendidir.
6. Durum dili: Normal / Dikkat / Kritik / İzleme yok / Ölçülemedi. A–F ana ekranda yok.
7. Ana ekranda teknik terim yok (p95, N+1, Firing, Theil–Sen; datastore yerine «depolama alanı»). Teknik açıklama (i) ve detaydadır.
8. Her kart yöntem rozeti ve (i) taşır. AI metni `AiBlock` içindedir.
9. Grafikler Recharts. Açık ve koyu temada okunur.
10. Sayfa açılışta hesaplamaz.

Sentetik kayıt (`fake_seed` / `synthetic`, ad `ZZ-FAKE` ile başlar, entegrasyon türü `_demo` ile biter) yönetici paketinin bütün alanlarından dışlanır. Silinmez.

Para yalnız `cost_config` doluysa yazılır. Varsayılan 50 / 20 / 0,5 TL yazılmaz.

## Sayfa düzeni

### 1. Üst bar

Başlık «Yönetici Raporu», ay seçici, üretim zamanı, «Şimdi yenile», PDF, CSV. Kapsam rozeti: «12 bölümden 5'i ölçülebildi». Tıklanınca sayfanın sonundaki Veri kapsamı bölümüne gider.

### 2. Yönetici özeti bandı

Sol: AI özeti, 3–5 cümle, sade Türkçe, yer tutucudan basılmış. Üretilemediyse şablon cümleler. Sağda dört kutu:

| Kutu | İçerik |
|---|---|
| Kritik durumdaki alan | Kritik alan / izlenen alan. İzleme yok paydada değildir. Örnek: «1 / 3 alan» |
| En yakın kapasite eşiği | En erken eşiğe varacak cluster, kaynak, aralık. Örnek: «office · bellek · 4–7 ay» |
| Geri kazanılabilir kaynak | vCPU, RAM, disk. Örnek: «126 vCPU · 403,4 GB RAM · 5,7 TB» |
| 30 günden uzun açık kritik sorun | Adet |

Ölçülemeyen kutu «—» ve kısa neden («geçmiş veri yetersiz»). Demo sayı bu kutulara girmez.

### 3. Alan kartları

Yan yana: OpenShift, Sanallaştırma (vCenter ve OLVM), Linux, Windows. Windows izlenmiyorsa kart «İzleme yok»dur ve risk sayılır.

Her kartta durum etiketi, tek cümle neden, üç mini metrik, son 30 gün tekilleştirilmiş kritik+uyarı sparkline (günlük özet), geçen aya göre ok. İki `executive_monthly` yoksa ok yerine «ilk ay». «Detay» aynı sayfada sağ paneli açar: varlık tablosu (ad, durum, açık kritik/uyarı, en yüksek kullanım) ve son 30 gün grafiği. Veri pakettendir. Başka sayfaya bağlantı yok.

Mini metrik örnekleri: Sanallaştırma → cluster sayısı, en yüksek bellek doluluğu, açık kritik sorun. OpenShift → cluster/node, açık kritik uyarı, en yoğun node. Linux → izlenen sunucu, kritik sorunlu sunucu, en yüksek bellek. OpenShift kartında küme olayı cümlesi durur.

### 4. Kapasite

Eşiğe kalan süre: her cluster veya depolama alanı bir satır. Yatay eksen ay. Satırda tipik nokta ve en erken–en geç aralık. 3, 6 ve 12. ayda dikey referans. En yakından uzağa. Düşük güven soluk ve «düşük güven».

Şu anki doluluk: cluster bazında bellek ve CPU yatay çubuk, eşik çizgisi (%85 bellek, %80 CPU).

Kısa satır: «Bir sunucu arızalanırsa kalan kapasite yetmeyen cluster: …».

Yatırım kutusu: «Önümüzdeki 12 ayda ek sunucu ihtiyacı: 0» ve neden («tüm cluster'larda eşiğe 12 aydan fazla» veya «tahmin aralığı 12 ayı aşıyor»). Para yalnız maliyet parametresi varsa.

OpenShift node ve Linux disk ölçülemediyse grafik altında tek satır: «OpenShift node ve Linux disk tahmini için veri yok» ve Veri kapsamına giden sayfa içi bağlantı.

### 5. Yaklaşan takvim (12 ay)

Ay ekseninde kapasite eşiği aralıkları, destek bitişi, garanti bitişi. Kaynağı olmayan kategori gri şerit ve «veri yok». Altında liste: tarih veya aralık, alan, olay, etki. Destek ve garanti, demo bayrağı kapalıyken ve gerçek kayıt yokken «veri yok»tur. Demo bayrağı açıksa bu takvim dilimi demo kart kuralına girer; kilitli pakete ve ay-ay farka girmez.

### 6. Öncelikli riskler (ilk 5)

Tablo: Alan, risk cümlesi, etki, kaç gündür açık, önerilen aksiyon. Aksiyon kural tabanlıdır. Satır aynı sayfada detay açar: etkilenen varlıklar, ilk görülme, kanıt özeti. Ham mesaj, IP ve kullanıcı adı yok. «Kaç gündür» 7, 30 ve 90 günde renkli etiket. Sıra şiddet × yaş × etkidir; kural (i) içindedir. Demo bulgu bu tabloya girmez.

### 7. Atıl kaynak

Kategori çubuğu: Kapalı VM, Atıl VM, Aşırı boyutlu, Eski snapshot, Yetim disk. Sekmeler vCPU, RAM, disk. İlk 10, detay panelinde: ad, cluster, kategori, geri kazanılabilir miktar, kaç gündür. VM adı gösterilir. IP ve kullanıcı gösterilmez. Not: «Bu değerler ayrılmış kaynaktır, gerçek tüketim değildir.» Maliyet parametresi yoksa para yok.

### 8. Olay ve operasyon

Dönem boyunca günlük tekilleştirilmiş kritik ve uyarı, alan bazında yığılmış çubuk veya çizgi. En çok tekrar eden beş kaynak sade adla («office cluster vCenter olayları»), adet ve trend. Ham mesaj yok. Manuel veya kural kapanışı yoksa: «Olaylar otomatik kapatılıyor; çözüm süresi ölçülemiyor» ve otomatik kapanan adet. Ortalama yazılmaz.

### 9. Veri kapsamı

Sayfanın en altı. Varsayılan kapalı. Tablo: Bölüm, durum, eksik olan, nasıl tamamlanır. Metrik adları yalnız satır açılınca. Örnekler: yaşam döngüsü için referans paketi; Linux disk için node_exporter; mevsimsellik için «70/395 gün, kendiliğinden tamamlanır» ve tahmini tarih.

## Şablon cümle

Cümle anlam taşır. Sayı listesi değildir.

- «Kapalı durumdaki 29 VM toplam 126 vCPU, 403,4 GB RAM ve 5,7 TB disk ayırıyor.»
- «En yakın kapasite eşiği office cluster'ında: bellek 4–7 ay içinde %85'e ulaşabilir.»
- «Önümüzdeki 12 ay için ek sunucu ihtiyacı görünmüyor.»
- «Bu ay OpenShift alanında 2 node'da kritik uyarı açık.»

Her bölümün en az bir cümlesi vardır. Ölçülemeyen bölüm: «X ölçülemedi çünkü Y.»

## Rapor gerçekleri

- B1 satırı: ad, kaynak türü (bellek, CPU, disk), şu anki doluluk, eşik, tipik / en erken / en geç ay, güven. Yalnız «3 clusters» yetmez.
- Alan: durum, neden cümlesinin anahtarları, üç mini metrik, son 30 gün günlük sorun serisi.
- Risk: ilk beş satır (alan, risk anahtarı, etki, açık gün, aksiyon anahtarı) ve detay listesi.
- Atıl kaynak: kategori toplamları ve ilk 10 öğe.
- Olay: günlük seri (alan × şiddet) ve en çok tekrar eden beş sade kaynak.
- Takvim: tarih veya aralık, kategori, alan.
- Sentetik kayıt bu alanların hepsinden dışlanır.
- Sayılar `display` dizisinde `tr-TR` biçimiyle gider.

## Demo kart (önizleme modu yok)

Ayrı düğme veya mod kurulmaz. Yedek ve donanım kartları:

- `BACKUP_DEMO_ENABLED` açıksa yedek kartı mevcut `veeam_demo` sağlayıcının sayısını gösterir. Kapalıysa veya gerçek Veeam yoksa Ölçülemedi.
- `HW_DEMO_ENABLED` açıksa donanım ve garanti kartı mevcut `hw_demo` sağlayıcının sayısını gösterir. Kapalıysa veya gerçek OME/OneView yoksa Ölçülemedi.
- Sayı demo sağlayıcıdan gelir. Uydurulmaz.
- Demo kart: kesikli turuncu çerçeve, «DEMO» filigranı, «Örnek veri» etiketi. Filigran her zaman görünür.
- Gerçek bölüm gerçek veriyle kalır. Aynı kartta demo ve gerçek sayı karışmaz (test).
- Demo sayı KPI, AI özeti, risk listesi, kilitli paket, ay-ay fark, PDF ve CSV'ye girmez (test).

## PDF ve CSV

PDF A4 yatay, iki sayfa. Sayfa 1: üst bar, özet bandı, alan kartları, kapasite. Sayfa 2: takvim, riskler, atıl kaynak, olay; sonda veri kapsamı ve yöntem notları. Grafikler yazdırma CSS'i ile görünür. CSV sayıların Türkçe etiketli halidir. İkisinde de demo sayı yoktur. Anahtar adı yoktur.

Dar ekran 1366 px: kartlar alt alta, yatay kaydırma yok. İlk ekran 1920×1080: özet bandı ve alan kartları kaydırmadan görünür.

## Kabul

- [ ] Başka modül sayfasına `href` yok. Detay sayfa içi panelde.
- [ ] Tek sayfa, kaynak kilitli paket. Açılışta canlı hesap yok. `/executive/reports` yönlenir.
- [ ] Sayfa ve paket notu tek fonksiyondan. Ekip raporu ve dashboard JSON'u aynı girdiyle değişmez.
- [ ] Açık kritik varlık alanı en az Dikkat yapar. Cümle (i) içindedir.
- [ ] Riskler `infra_findings`. Ham olay başlığı ve oturum satırı risk değildir.
- [ ] Ay dönümünde `executive_monthly` kilitlenir. Ay-ay fark yalnız ondan. Saat taklidiyle test.
- [ ] AI özeti üretimde yazılır. Sayfa model çağırmaz. Yer tutucu + sayı kapısı.
- [ ] Ham log, IP, kullanıcı adı, user-agent yok. `snake_case` anahtar yok. Sayılar `tr-TR` ve birimli.
- [ ] Runway cluster bazında aralıklı. Düşük güven ayırt edilir.
- [ ] Alan kartı: durum, neden, üç metrik, sparkline, detay paneli. OpenShift küme olayı cümlesi kartta ve (i) içinde.
- [ ] Risk tablosunda kaç gündür açık var. Atıl kaynak grafiği ve ilk 10 var.
- [ ] Olay grafiği tekilleştirilmiş sorun sayısı. Ham olay adedi ana ekranda yok.
- [ ] Veri kapsamı en altta, varsayılan kapalı. Şablon cümle anlamlı.
- [ ] PDF iki sayfa, grafikler dahil.
- [ ] Demo kart: bayrak kapalıyken Ölçülemedi; açıkken sağlayıcı sayısı, turuncu çerçeve, DEMO filigranı, Örnek veri. Demo KPI, özet, risk, kilit, ay-ay fark ve dışa aktarıma girmez. Aynı kartta karışmaz.
- [ ] Açık ve koyu tema okunur. 1366 px'te yatay kaydırma yok.

## Çalışma sırası

Mimari 1–7, sonra rapor gerçeklerinin genişlemesi, sonra UI. Her adımda commit. Testler yeşil olmadan sonraki adıma geçilmez. Tek ajan. Dur ve sor: yeni grafik kütüphanesi, yeni dış çağrı, veri silen migration.

Bitince her bölümün ekran görüntüsü alınır (açık tema, 1920×1080) ve final rapora eklenir.

## Sonraki iş — OpenShift alert toplama

Bu tura girmez. Final raporda ayrı öneri olarak durur.

Kapsam: OpenShift notunun küme olayından çıkıp Red Hat'in önerdiği ölçüme geçmesi. Kaynak, Firing durumundaki monitoring alert'leridir. Silenced, Watchdog ve info dışarıdadır. Bugün bu alert'lerin son senkron tablosu yoktur; küme olayı (`openshift_collector`, `platform=openshift`) notu şişirebilir, not gerçekten kötü görünebilir. Toplamak yeni bir senkron ve büyük olasılıkla yeni bir API çağrısıdır. Onay olmadan çağrı açılmaz. Karttaki uyarı cümlesi o iş bitene kadar kalır.
