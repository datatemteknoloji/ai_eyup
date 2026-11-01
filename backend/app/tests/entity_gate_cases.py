"""Adım 4 — varlık çözümleyici kapısı için soru kümeleri (birim testler + scripts/diag_entity_gate.py ortak).

HARMLESS: kapı ASLA tetiklenmemeli (yanlış alarm = 0). Gerçek ad içerenler canlı DB'deki adlara göre,
yazılım/komut/IP/genel sorular ad bağımsız.
GHOST: envanterde olmayan, tip adıyla bağlı kimlik biçimli ad → "bulunamadı".
MULTI: aynı adla ≥2 kayıt (mtv-testserver, rhel8-10tst, datatemengine) → listele + sor.
NARROWED: aynı ad ama platform daraltmalı → kapı YOK (normal akış).
"""

HARMLESS = [
    # genel / sayım / liste
    "Toplam kaç VM var?", "Kapalı VM'leri listele", "Son 24 saatte silinen VM'ler hangileri?",
    "Restart sayısı en yüksek 5 pod hangisi?", "En çok CPU kullanan 5 VM hangisi?",
    "Hangi ESXi host'ta CPU yükü yüksek?", "Datastore doluluk oranı kritik olanları listele",
    "Linux sunucuda load average neden yüksek?", "Windows sunucuda C: diski ne kadar dolu?",
    "systemd'de failed olan servisler var mı?", "OpenShift'te kaç node var?", "Cluster node'larının durumu nasıl?",
    "VM'lerin aylık lisans maliyeti ne kadar?", "Snapshot'ı olan VM'ler hangileri?",
    "Sunucularımın hangileri kapalı?", "Hangi namespace'te en çok pod var?", "Kaç cluster var?",
    "Şu an kaç iş çalışıyor?", "Bunların hepsi Ready mi?", "Peki durumu ne?",
    # yazılım / komut / OS adı + tip adı (kimlik biçimli ama envanter adı değil)
    "node-exporter sunucuda çalışıyor mu?", "kube-apiserver pod'u neden restart ediyor?",
    "rhel-9.4 sunucuları listele", "RHEL8.10 sunucu kaç tane?", "python3.11 kurulu sunucular hangileri?",
    "nginx-1.24 çalışan sunucu var mı?", "windows-exporter host'ta kurulu mu?", "kube-system namespace'indeki podlar",
    "kube-public namespace'inde neler var?", "df -h komutu sunucuda ne gösterir?", "ssh-keygen ile ilgili bir sunucu var mı?",
    "systemd-resolved servisi hangi sunucuda hata veriyor?", "x86-64 sunucu sayısı kaç?", "ipv6 kapalı sunucular hangileri?",
    "tcp-wait durumundaki bağlantılar sunucuda nasıl görünür?", "log4j-2.17 kullanan VM var mı?",
    # IP / sayı / dosya
    "10.0.0.5 IP'li sunucu hangisi?", "192.168.1.241 sunucusu açık mı?", "8080 portu hangi sunucuda açık?",
    "/var/log/messages dosyası hangi sunucuda büyük?", "config.yaml dosyasını hangi sunucu kullanıyor?",
    # tip adı olmadan kimlik biçimli token
    "web-01 çalışıyor mu?", "ZZ-NOPE-1 nedir?", "db_prod_02 durumu ne?", "app-server-9 kaç CPU kullanıyor?",
    # İngilizce
    "How many VMs are powered off?", "List the hosts with high CPU", "Which cluster has the most nodes?",
    "Show me the datastore usage", "What is the status of the openshift cluster?",
    "Is the server up?", "List all namespaces", "how many nodes are in the cluster",
    # çoğul/yalın tip adları (bulunma hâli vb.)
    "Linux sunucularda disk doluluk oranı", "Sunucuda hangi servisler çalışıyor?", "Host'ta kaç VM var?",
    "VM'de disk kullanımı nasıl?", "Cluster'da kaç host var?", "Datastore'da boş alan ne kadar?",
    "Namespace'de kaç pod var?", "Node'da CPU kullanımı nasıl?",
    # eylem kalıpları değil, soru
    "kapalı VM'ler neden kapandı?", "silinen VM'ler kimler tarafından silindi?",
]

GHOST = [
    ("ZZ-NOPE-VM-999 VM'i hangi hostta?", "ZZ-NOPE-VM-999"),
    ("vcenter-yok.local hypervisor'ında kaç VM var?", "vcenter-yok.local"),
    ("FAKE-Cluster-9 cluster'ında kaç host var?", "FAKE-Cluster-9"),
    ("ZZ-NOPE-OCP cluster'ında kaç node var?", "ZZ-NOPE-OCP"),
    ("nonexistent-ns namespace'inde kaç pod var?", "nonexistent-ns"),
    ("ZZ-NOPE-HOST sunucusunun CPU kullanımı nedir?", "ZZ-NOPE-HOST"),
    ("zz-nope-host sunucusunun diski ne kadar dolu?", "zz-nope-host"),
    ("ZZ-NOPE-VM-123 VM'inin durumu ne?", "ZZ-NOPE-VM-123"),
    ("ZZ-NOPE-VM-124 VM'in IP adresi nedir?", "ZZ-NOPE-VM-124"),
    ("ZZ-NOPE-VM-125 VM nerede çalışıyor?", "ZZ-NOPE-VM-125"),
    ("ghost-vm-77 VM'i açık mı?", "ghost-vm-77"),
    ("ghostsrv_42 sunucusu çalışıyor mu?", "ghostsrv_42"),
    ("ghost-host-3 host'unun CPU'su kaç?", "ghost-host-3"),
    ("ghost-host-4 hostunun durumu ne?", "ghost-host-4"),
    ("nope-ds-01 datastore'unda boş alan ne kadar?", "nope-ds-01"),
    ("nope-ds-02 datastore'un doluluk oranı?", "nope-ds-02"),
    ("ZZ-NOPE-NODE-1 node'unun durumu nedir?", "ZZ-NOPE-NODE-1"),
    ("ZZ-NOPE-NODE-2 node'u Ready mi?", "ZZ-NOPE-NODE-2"),
    ("no-such-project namespace'inde hangi podlar var?", "no-such-project"),
    ("no-such-project2 projesinde kaç pod var?", "no-such-project2"),
    ("ZZ-NOPE-CLUSTER-3 cluster'ının node sayısı?", "ZZ-NOPE-CLUSTER-3"),
    ("ZZ-NOPE-CLUSTER-4 clusterında kaç VM var?", "ZZ-NOPE-CLUSTER-4"),
    ("What is the CPU usage of ZZ-NOPE-HOST-9 server?", "ZZ-NOPE-HOST-9"),
    ("Is ZZ-NOPE-VM-55 vm running?", "ZZ-NOPE-VM-55"),
    ("How many pods in nonexistent-ns-2 namespace?", "nonexistent-ns-2"),
    ("fake-vcenter-9.invalid vcenter'ında kaç VM var?", "fake-vcenter-9.invalid"),
    ("ZZ_NOPE_VM_77 VM'i hangi datastore'da?", "ZZ_NOPE_VM_77"),
    ("Winserver99 sunucusu çalışıyor mu?", "Winserver99"),
]

MULTI = [
    "mtv-testserver hangi hypervisor'da?", "mtv-testserver açık mı?", "datatemengine VM'i hangi platformda ve durumu ne?",
    "rhel8-10tst nedir, nerede çalışıyor?", "MTV-TESTSERVER kaç CPU kullanıyor?", "mtv-testserver VM'inin IP adresi nedir?",
    "datatemengine hangi cluster'da?", "rhel8-10tst VM'i açık mı?", "Is mtv-testserver running?",
    "datatemengine'in durumu nedir?",
]

NARROWED = [
    "office vCenter'daki mtv-testserver açık mı?", "OpenShift'teki mtv-testserver durumu ne?",
    "Datatem OLVM'deki datatemengine hangi host'ta?", "vmware üzerindeki rhel8-10tst açık mı?",
    "openshift virtualization'daki rhel8-10tst durumu?",
]
