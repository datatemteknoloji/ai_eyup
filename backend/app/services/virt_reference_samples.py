"""Offline referans paketleri için ÖRNEK şablonlar (format belgesi).

Gerçek içerik değildir — operatör kendi VMSA / KB / yükseltme matrisi
verisini bu şemaya dönüştürüp yükler. Ürün anahtarları:
esxi | vcenter | olvm_engine | olvm_host | ocp_virt | openshift
"""

SAMPLES = {
    "cve_feed": {
        "source": "ÖRNEK — kurum içi VMSA/RHSA dışa aktarımı",
        "advisories": [
            {
                "id": "VMSA-YYYY-NNNN",
                "cve": ["CVE-YYYY-NNNNN"],
                "severity": "critical",
                "cvss": 9.8,
                "title": "Örnek: vCenter Server heap-overflow",
                "workaround": "Varsa geçici çözüm",
                "products": [
                    {"product": "vcenter", "affected": [">=8.0,<8.0.3"], "fixed": "8.0 U3b", "fixed_build": "24262322"},
                    {"product": "esxi", "affected": [">=7.0,<8.0"], "fixed": "7.0 U3s"},
                ],
            }
        ],
    },
    "kb_feed": {
        "source": "ÖRNEK — kurum içi bilinen sorun listesi",
        "articles": [
            {
                "id": "KB-ORNEK-1",
                "title": "Örnek: Belirli sürümde HA ajanı yeniden başlıyor",
                "severity": "medium",
                "products": [{"product": "esxi", "affected": [">=8.0.2,<8.0.3"]}],
                "event_patterns": ["fdm.*restart", "HA agent.*unreachable"],
                "symptoms": ["vSphere HA agent unreachable"],
                "resolution": "8.0 U3'e yükseltin veya geçici çözümü uygulayın.",
            }
        ],
    },
    "upgrade_matrix": {
        "source": "ÖRNEK — kurum yükseltme standardı",
        "products": {
            "esxi": {
                "target": "8.0.3",
                "eol": [{"version": "7.0", "eol_date": "2025-10-02"}],
                "paths": [{"from": "7.0", "to": "8.0.3", "via": None,
                           "notes": "Önce vCenter 8.0.3'e yükseltin; vLCM image ile."}],
            },
            "vcenter": {"target": "8.0.3", "eol": [{"version": "7.0", "eol_date": "2025-10-02"}], "paths": []},
            "olvm_engine": {"target": "4.5.5", "eol": [], "paths": []},
            "olvm_host": {"target": "4.5.5", "eol": [], "paths": []},
        },
        "hardware": [
            {"vendor": "Dell Inc.", "model": "PowerEdge R630", "max_version": "7.0.3",
             "notes": "Broadcom HCL'de 8.x desteklenmiyor (örnek)"},
        ],
    },
}


def sample_with_meta(kind: str):
    """Örnek + zorunlu üstveri: sürüm, üretim tarihi (bugün) ve içerik SHA-256'sı.

    Bağlantı (`source_url`) örneklere KONMAZ — uydurma bağlantı üretilmez; operatör yalnız resmi üretici
    alan adlarındaki (https) gerçek bağlantıları ekleyebilir.
    """
    import copy
    from datetime import date
    if kind not in SAMPLES:
        return None
    from app.services.virt_reference_checks import compute_checksum
    d = copy.deepcopy(SAMPLES[kind])
    d["version"] = "ornek-1"
    d["generated_at"] = date.today().isoformat()
    d["_aciklama"] = ("Zorunlu: generated_at (YYYY-AA-GG). İsteğe bağlı: sha256 = bu dosyadan 'sha256' alanı çıkarılıp "
                      "anahtarlar sıralı, boşluksuz (separators=(',',':')), ensure_ascii=False JSON'un SHA-256'sı. "
                      "Kayıtlara 'source_url' yalnız resmi üretici alan adlarından (https) eklenebilir.")
    d["sha256"] = compute_checksum(d)
    return d
