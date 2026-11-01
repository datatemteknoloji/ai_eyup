# OS logoları

`OsIcon.tsx` (`/assets/logos/<kind>-logo.<ext>`) tarafından kullanılır. Tek renkli SVG'ler
24×24 viewBox, `fill` kök `<svg>` üzerinde (debian/ubuntu/linux ile aynı biçim).

| Dosya | Kaynak ikon | Marka rengi (fill) |
|---|---|---|
| `almalinux-logo.svg` | simple-icons `almalinux` | `#0FA3E0` * |
| `rocky-logo.svg` | simple-icons `rockylinux` | `#10B981` |
| `centos-logo.svg` | simple-icons `centos` | `#9CCD2A` * |
| `fedora-logo.svg` | simple-icons `fedora` | `#51A2DA` |
| `rhcos-logo.svg` | simple-icons `redhatopenshift` ** | `#EE0000` |

\* simple-icons marka rengi AlmaLinux için `#000000`, CentOS için `#262577`; koyu arayüzde
görünmediği için açık tonlu resmî palet rengiyle değiştirildi (şekil değişmedi).
CentOS için resmî yeşil (`#9CCD2A`), AlmaLinux için açık mavi seçildi.

\** simple-icons'ta CoreOS / RHCOS ikonu yok. Red Hat CoreOS, OpenShift'in düğüm işletim sistemi
olduğundan Red Hat OpenShift işareti kullanıldı. Resmî bir RHCOS logosu eklenirse yalnızca
`rhcos-logo.svg` dosyasını değiştirmek yeterlidir.

Diğer dosyalar (`debian`, `ubuntu`, `linux`, `vmware`, `windows`, `oracle`, `redhat`, `suse`)
önceden mevcuttu; bu düzenlemede değiştirilmedi.

## Donanım üreticisi logoları

`components/hardware/hwUi.tsx` → `VendorLogo` (Donanım sayfası, `vendor` = `dell` | `hpe`) kullanır.

| Dosya | Kaynak ikon | Marka rengi (fill) |
|---|---|---|
| `dell-logo.svg` | simple-icons `dell` | `#0076CE` * |
| `hp-logo.svg` | simple-icons `hp` | `#0096D6` |

\* simple-icons rengi `#007DB8`; Dell'in resmî mavisi `#0076CE` kullanıldı (şekil değişmedi).
HPE sunucuları için klasik HP (daire) işareti kullanılır; Hewlett Packard Enterprise'ın kendi
logosu (yeşil dikdörtgen) simple-icons'ta yok. Resmî dosya gelirse yalnızca `hp-logo.svg` değiştirilir.
Paket/lisans notları aşağıdaki bölümle aynıdır (simple-icons 16.35.0, indirme 2026-11-01).

## Kaynak ve lisans

- Paket: [`simple-icons`](https://github.com/simple-icons/simple-icons) **16.35.0**
  (`npm pack simple-icons` ile `/tmp` altına indirildi; projeye bağımlılık **eklenmedi**).
- İndirme tarihi: 2026-10-14.
- Paket lisansı: **CC0-1.0**. Bu, tek tek markaların lisansı/ticari marka hakkı anlamına gelmez
  (bkz. paketin `DISCLAIMER.md`). simple-icons veri dosyasındaki ikon bazlı lisanslar:
  - Rocky Linux: CC-BY-SA-4.0 (kaynak: <https://github.com/rocky-linux/branding>)
  - Fedora: özel (<https://docs.fedoraproject.org/en-US/project/brand/>)
  - AlmaLinux (<https://almalinux.org>), CentOS (<https://wiki.centos.org/ArtWork/Brand/Logo>),
    Red Hat / OpenShift (<https://www.redhat.com/en/about/brand/new-brand/details>): ikon
    bazında lisans bilgisi yok; ilgili marka yönergelerine tabidir.
- Logolar yalnızca ilgili dağıtımı tanımlamak için kullanılır; marka sahipleriyle bağlantı ima etmez.
