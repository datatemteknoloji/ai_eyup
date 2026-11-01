| kullanıcı | modüller | soru | kural | sızıntı | süre | sonuç |
|---|---|---|---|---|---|---|
| virtualization_user | applications,knowledge,monitoring,virtualization | Kaç VM var? | kural=evet (beklenen evet) | sızıntı=yok | 0.42s | GEÇTİ |
  - cevap: **Toplam VM: 1552** Kapsam: tüm platformlar (5 hypervisor) Dağılım: açık **1466** · kapalı **86** · askıda **0** · toplam **1552** | Hypervisor | Tür | Toplam |
| virtualization_user | applications,knowledge,monitoring,virtualization | OpenShift'te kaç node var? | kural=hayır (beklenen hayır) | sızıntı=yok | 0.62s | GEÇTİ |
  - cevap: Bu soru, yetkiniz olmayan modül(ler) için: **openshift**. Yalnızca size atanmış modüllerin verisini sorgulayabilirsiniz. Erişim için yöneticinizden modül atamas
| openshift_user | applications,knowledge,monitoring,openshift | OpenShift'te kaç node var? | kural=evet (beklenen evet) | sızıntı=yok | 0.13s | GEÇTİ |
  - cevap: **Toplam node: 18** Kapsam: tüm OpenShift cluster'ları (2) | OpenShift cluster | Node | |---|---:| | ZZ-FAKE-OCP | 15 | | oVirt | 3 | _Kaynak: envanter veritaba
| openshift_user | applications,knowledge,monitoring,openshift | Kaç VM var? | kural=hayır (beklenen hayır) | sızıntı=yok | 0.14s | GEÇTİ |
  - cevap: Bu soru, yetkiniz olmayan modül(ler) için: **virtualization**. Yalnızca size atanmış modüllerin verisini sorgulayabilirsiniz. Erişim için yöneticinizden modül a
| linux_user | applications,knowledge,linux,monitoring | Kaç VM var? | kural=hayır (beklenen hayır) | sızıntı=yok | 0.15s | GEÇTİ |
  - cevap: Bu soru, yetkiniz olmayan modül(ler) için: **virtualization**. Yalnızca size atanmış modüllerin verisini sorgulayabilirsiniz. Erişim için yöneticinizden modül a
| linux_user | applications,knowledge,linux,monitoring | OpenShift'te kaç proje var? | kural=hayır (beklenen hayır) | sızıntı=yok | 0.13s | GEÇTİ |
  - cevap: Bu soru, yetkiniz olmayan modül(ler) için: **openshift**. Yalnızca size atanmış modüllerin verisini sorgulayabilirsiniz. Erişim için yöneticinizden modül atamas
| virtualization_user | applications,knowledge,monitoring,virtualization | Kaç cluster var? | kural=evet (beklenen evet) | sızıntı=yok | 1.33s | GEÇTİ |
  - cevap: **Sanallaştırma cluster sayısı: 6** Kapsam: tüm platformlar (5 hypervisor) | Hypervisor | Tür | Cluster | |---|---|---:| | Datatem OLVM | KVM / OLVM | 1 | | ZZ-

KALAN: 0
