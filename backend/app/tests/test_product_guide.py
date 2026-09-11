"""Ürün GUIDE — paketler, Level 1 içeriği, HTML kaçış."""
from app.services.product_guide import (
    PACKS,
    assemble_markdown,
    build_product_guide,
    list_packs,
    markdown_to_html,
    resolve_guide_root,
)


def test_guide_root_has_tr_en():
    root = resolve_guide_root()
    assert (root / "tr" / "01-overview.md").is_file()
    assert (root / "en" / "modules" / "level1.md").is_file()


def test_catalog_packs_order():
    ids = [p["id"] for p in list_packs("tr")]
    assert ids == [
        "full", "linux", "virtualization", "windows", "openshift", "ai-architecture",
    ]


def test_ai_architecture_pack_has_update_mandate():
    _, md = assemble_markdown("ai-architecture", "tr")
    assert "GÜNCELLEME ZORUNLU" in md
    assert "route_unified" in md
    assert "module_orchestrator" in md
    assert "# 1. AI System Inventory" in md
    assert "# 21. Architecture Diagrams" in md
    assert "```mermaid" in md
    assert "```diagram" in md
    assert len(md) > 20000
    _, md_en = assemble_markdown("ai-architecture", "en")
    assert "MUST UPDATE" in md_en
    assert "route_unified" in md_en
    assert "# 1. AI System Inventory" in md_en
    assert "# 21. Architecture Diagrams" in md_en
    assert len(md_en) > 20000


def test_full_tr_contains_level1_and_menus():
    title, md = assemble_markdown("full", "tr")
    assert "Yetenek" in title or "GUIDE" in title
    assert "Level 1" in md
    assert "/level1" in md
    assert "Talep ID" in md
    assert "/integrations/hypervisors" in md
    assert "oVirt" in md


def test_openshift_pack_covers_ovirt():
    _, md = assemble_markdown("openshift", "tr")
    assert "oVirt" in md or "OLVM" in md
    assert "/openshift" in md
    assert "kvm" in md


def test_virt_pack_is_virt_menus_only():
    _, md = assemble_markdown("virtualization", "tr")
    assert "/hypervisors" in md
    assert "/infra-reports" in md
    assert "/virt/chat" in md


def test_diagram_fence_renders():
    html = markdown_to_html("```diagram\n  A\n  │\n  ▼\n  B\n```")
    assert 'class="diagram"' in html
    assert "│" in html or "&#" in html


def test_markdown_table_and_escape():
    html = markdown_to_html("| A | B |\n|---|---|\n| x | <script> |")
    assert "<table>" in html
    assert "&lt;script&gt;" in html
    assert "<script>" not in html


def test_mermaid_becomes_diagram_pre():
    html = markdown_to_html("```mermaid\nflowchart LR\n  A --> B\n```")
    assert 'class="diagram"' in html
    assert "A --&gt; B" in html or "A --> B" in html


def test_build_product_guide_unknown_pack():
    try:
        build_product_guide("no-such-pack", "tr")
        assert False
    except KeyError:
        pass


def test_all_packs_assemble():
    for pid in PACKS:
        title, md = assemble_markdown(pid, "tr")
        assert title
        assert len(md) > 80
        title_en, md_en = assemble_markdown(pid, "en")
        assert title_en
        assert len(md_en) > 80
        doc = build_product_guide(pid, "tr")
        assert "<h" in doc["html"]
        assert doc["pack"] == pid
