#!/usr/bin/env python3
"""Generate Dropt ops handbook Markdown + PDF for host-merge Cursor handoff."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
MANIFEST = OUT_DIR / "dropt-host-merge-manifest.json"
CAPS = ROOT / "backend/app/assistant/capabilities.json"
RULES_DIR = ROOT / ".cursor/rules"
FONT = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf"
FONT_MONO = "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf"

MD_OUT = OUT_DIR / "DROPT-OPS-HANDBOOK.md"
PDF_OUT = OUT_DIR / "DROPT-OPS-HANDBOOK.pdf"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text.strip()


def md_escape(s: str) -> str:
    return (s or "").replace("\r\n", "\n")


def build_markdown(manifest: dict, caps: dict) -> str:
    today = date.today().isoformat()
    lines: list[str] = []
    a = lines.append

    a("# Dropt Ops Portal — Operasyon & Host Merge El Kitabı")
    a("")
    a(f"**Sürüm:** handbook 1.0 · manifest {manifest.get('manifest_version')} · capabilities {caps.get('version')}")
    a(f"**Tarih:** {today}")
    a(f"**Kaynak:** `{manifest.get('source_root_hint', '/dttadvance/app')}`")
    a("")
    a("> Hedef ortamdaki Cursor: Bu belge + `dropt-host-merge-manifest.json` + `dropt-host-merge.mdc` + `capabilities.json` ile Dropt operasyonlarını eksiksiz göm. Eksik ops/ayar/API varsa tamamla.")
    a("")
    a("---")
    a("")
    a("## 1. Amaç ve birleştirme hedefleri")
    a("")
    a(md_escape(manifest.get("purpose", "")))
    a("")
    goals = manifest.get("merge_goals") or {}
    for key, title in [
        ("omit", "Omit (taşıma)"),
        ("keep_under_dropt_submenu", "Dropt submenu altında tut"),
        ("relocate_if_host_missing", "Host’ta yoksa üst Ayarlar’a taşı"),
        ("omit_security_if_host_has", "Host’ta varsa güvenlikten çıkar"),
        ("replace_with_host", "Host karşılığı ile değiştir"),
    ]:
        items = goals.get(key) or []
        if not items:
            continue
        a(f"### {title}")
        a("")
        for it in items:
            a(f"- `{it}`")
        a("")

    a("## 2. Mimari")
    a("")
    arch = manifest.get("architecture") or {}
    a(md_escape(arch.get("recommended_model", "")))
    a("")
    a("### Katmanlar")
    a("")
    for layer in arch.get("layers") or []:
        owns = ", ".join(f"`{x}`" for x in layer.get("owns") or [])
        a(f"- **{layer.get('id')}**: {owns}")
    a("")
    a("### Kritik entegrasyon noktaları")
    a("")
    for p in arch.get("critical_integration_points") or []:
        a(f"#### `{p.get('id')}`")
        a("")
        a(md_escape(p.get("detail", "")))
        a("")

    stack = manifest.get("tech_stack_source") or {}
    a("### Tech stack (kaynak)")
    a("")
    fe = stack.get("frontend") or {}
    be = stack.get("backend") or {}
    a(f"- Frontend: {fe.get('stack')} — `{fe.get('path')}`")
    a(f"- Backend: {be.get('stack')} — `{be.get('path')}`")
    a(f"- Deploy: {stack.get('deploy')}")
    a("")

    a("## 3. Auth & oturum")
    a("")
    auth = manifest.get("auth_and_session") or {}
    a(f"- Login route: `{auth.get('login_route')}` → **omit**")
    a(f"- Token: `{auth.get('token_storage')}`")
    a(f"- Session dosyası: `{auth.get('session') if False else 'frontend/src/session.ts'}`")
    hm = auth.get("host_merge") or {}
    a(f"- Host merge: login=`{hm.get('login_page')}`, gate=`{hm.get('require_auth')}`")
    a("")
    a(md_escape(hm.get("notes", "")))
    a("")

    a("## 4. Navigasyon (kaynak → host)")
    a("")
    a("| Path | Label key | Host merge |")
    a("|------|-----------|------------|")
    for nav in (manifest.get("navigation_source") or {}).get("app_shell_items") or []:
        a(
            f"| `{nav.get('path')}` | `{nav.get('label_key')}` | `{nav.get('host_merge')}` |"
        )
    a("")

    a("## 5. Sayfalar")
    a("")
    for page in manifest.get("pages") or []:
        a(f"### {page.get('id')}")
        a("")
        a(f"- **Route:** `{page.get('route')}`")
        a(f"- **Component:** `{page.get('component')}`")
        a(f"- **Kind:** `{page.get('kind')}`")
        a(f"- **Host merge:** `{page.get('host_merge')}`")
        if page.get("critical"):
            a("- **CRITICAL:** yes")
        if page.get("api"):
            a(f"- **API:** {', '.join(f'`{x}`' for x in page['api'])}")
        if page.get("notes"):
            a(f"- **Not:** {page['notes']}")
        details = page.get("details") or page.get("behaviors")
        if isinstance(details, dict):
            a("- **Detaylar:**")
            for k, v in details.items():
                a(f"  - `{k}`: {v}")
        if page.get("depends_on"):
            a(f"- **Bağımlılık:** {', '.join(f'`{x}`' for x in page['depends_on'])}")
        a("")

    a("## 6. Tüm operasyonlar (ServerOpsMenu)")
    a("")
    menu = manifest.get("ops_menu_source") or {}
    a(f"- Kaynak: `{menu.get('file')}`")
    a(f"- Deep link single: `{ (menu.get('deep_link_query') or {}).get('single') }`")
    a(f"- Deep link multi: `{ (menu.get('deep_link_query') or {}).get('multi') }`")
    a(f"- FS mode: `{ (menu.get('deep_link_query') or {}).get('fs_mode') }`")
    a(f"- Network tab: `{ (menu.get('deep_link_query') or {}).get('network_tab') }`")
    a(f"- ASM max nodes: {menu.get('asm_max_nodes')}")
    a("")
    a("Multi-server’da gizlenenler:")
    for k in menu.get("multi_forbidden") or []:
        a(f"- `{k}`")
    a("")

    for op in manifest.get("ops_wizards") or []:
        a(f"### {op.get('title_tr')} (`{op.get('id')}`)")
        a("")
        a(f"| Alan | Değer |")
        a(f"|------|-------|")
        a(f"| Menu key | `{op.get('menu_key')}` |")
        a(f"| Path | `{op.get('path')}` |")
        a(f"| Component | `{op.get('component')}` |")
        a(f"| Job module | `{op.get('job_module')}` |")
        a(f"| Capability | `{op.get('capability_id')}` |")
        a(f"| Multi-server | `{op.get('multi_server')}` |")
        a(f"| Host merge | `{op.get('host_merge')}` |")
        a(f"| Embedded console | `{op.get('embedded_in_console', True)}` |")
        if op.get("backend_module"):
            a(f"| Backend | `{op.get('backend_module')}` |")
        a("")
        if op.get("ops_api"):
            a("**Ops API:**")
            a("")
            for api in op["ops_api"]:
                a(f"- `{api}`")
            a("")
        if op.get("api_extra"):
            a("**Ek API:**")
            a("")
            for api in op["api_extra"]:
                a(f"- `{api}`")
            a("")
        if op.get("children"):
            a("**Alt menü:**")
            a("")
            for ch in op["children"]:
                a(
                    f"- `{ch.get('id')}` → `{ch.get('path')}` "
                    f"(capability `{ch.get('capability_id')}`, action `{ch.get('action')}`)"
                )
            a("")
        if op.get("side_effects"):
            a("**Yan etkiler / kurallar:**")
            a("")
            for s in op["side_effects"]:
                a(f"- {s}")
            a("")
        if op.get("partition_rules"):
            pr = op["partition_rules"]
            a("**Partition kuralları:**")
            a("")
            a(f"- Eşik: {pr.get('threshold')}")
            a(f"- Altı: {pr.get('below')}")
            a(f"- Üstü: {pr.get('at_or_above')}")
            a(f"- Başarı: {pr.get('success_criterion')}")
            a("")
        if op.get("ui_notes"):
            a("**UI:**")
            a("")
            for n in op["ui_notes"]:
                a(f"- {n}")
            a("")
        if op.get("notes"):
            a(f"**Not:** {op['notes']}")
            a("")
        if op.get("embedded_note"):
            a(f"**Embedded:** {op['embedded_note']}")
            a("")
        # Enrich from capabilities
        cap_id = op.get("capability_id")
        cap = next((c for c in caps.get("capabilities") or [] if c.get("id") == cap_id), None)
        if cap:
            a("**Asistan katalog özeti:**")
            a("")
            a(f"- {cap.get('summary_tr')}")
            a(f"- Title EN: {cap.get('title_en')}")
            if cap.get("required_inputs"):
                a(f"- Gerekli girdiler: {', '.join(cap['required_inputs'])}")
            if cap.get("checklist_tr"):
                a("- Checklist:")
                for c in cap["checklist_tr"]:
                    a(f"  - {c}")
            if cap.get("out_of_scope_tr"):
                a(f"- Kapsam dışı: {cap['out_of_scope_tr']}")
            if cap.get("keywords"):
                a(f"- Keywords: {', '.join(cap['keywords'][:20])}")
            a("")
        # Children capabilities
        for ch in op.get("children") or []:
            cid = ch.get("capability_id")
            ccap = next((c for c in caps.get("capabilities") or [] if c.get("id") == cid), None)
            if not ccap:
                continue
            a(f"#### Alt ops: {ccap.get('title_tr')} (`{cid}`)")
            a("")
            a(f"- Route: `{ccap.get('route')}`")
            a(f"- Özet: {ccap.get('summary_tr')}")
            if ccap.get("checklist_tr"):
                for c in ccap["checklist_tr"]:
                    a(f"  - {c}")
            if ccap.get("out_of_scope_tr"):
                a(f"- Kapsam dışı: {ccap['out_of_scope_tr']}")
            a("")

    a("## 7. Ayar panelleri")
    a("")
    for panel in manifest.get("settings_panels") or []:
        a(f"### {panel.get('id')} (tab=`{panel.get('tab')}`)")
        a("")
        a(f"- Host merge: `{panel.get('host_merge')}`")
        if panel.get("reason"):
            a(f"- Sebep: {panel['reason']}")
        if panel.get("api"):
            apis = panel["api"] if isinstance(panel["api"], list) else [panel["api"]]
            a(f"- API: {', '.join(f'`{x}`' for x in apis)}")
        if panel.get("notes"):
            a(f"- Not: {panel['notes']}")
        if panel.get("required_for"):
            a(f"- Gerekli olduğu ops: {', '.join(panel['required_for'])}")
        for st in panel.get("subtabs") or []:
            a(f"  - Subtab `{st.get('id')}`: host_merge=`{st.get('host_merge')}` — {st.get('component')}")
            if st.get("notes"):
                a(f"    - {st['notes']}")
            if st.get("api"):
                for api in st["api"]:
                    a(f"    - `{api}`")
        a("")

    a("## 8. Backend API router’lar")
    a("")
    a("| Module | Prefix | Host merge |")
    a("|--------|--------|------------|")
    for r in manifest.get("backend_api_routers") or []:
        a(f"| `{r.get('module')}` | `{r.get('prefix')}` | `{r.get('host_merge')}` |")
    a("")

    jm = manifest.get("job_modules") or {}
    a("## 9. Job modülleri")
    a("")
    a(f"- Registry: `{jm.get('registry')}`")
    a(f"- Contract: {', '.join(f'`{x}`' for x in jm.get('contract_per_module') or [])}")
    a(f"- Flow: {jm.get('flow')}")
    a("")
    a("Modüller:")
    a("")
    for m in jm.get("modules") or []:
        a(f"- `{m}`")
    a("")

    a("## 10. Asistan")
    a("")
    asst = manifest.get("assistant") or {}
    a(f"- Rol: {asst.get('role')}")
    a(f"- Katalog: `{asst.get('catalog')}`")
    a(f"- Router: `{asst.get('router')}`")
    a(f"- Analyze: `{asst.get('analyze_readonly')}`")
    a("")
    hm = asst.get("host_merge") or {}
    for k, v in hm.items():
        a(f"- **{k}:** {v}")
    a("")

    # Remaining capabilities not covered as ops (servers, jobs, etc.)
    op_cap_ids = set()
    for op in manifest.get("ops_wizards") or []:
        if op.get("capability_id"):
            op_cap_ids.add(op["capability_id"])
        for ch in op.get("children") or []:
            if ch.get("capability_id"):
                op_cap_ids.add(ch["capability_id"])
    a("### Katalogda ek (sorgu / menü) capability’ler")
    a("")
    for c in caps.get("capabilities") or []:
        if c.get("id") in op_cap_ids:
            continue
        a(f"#### `{c.get('id')}` — {c.get('title_tr')}")
        a("")
        a(f"- Route: `{c.get('route')}`")
        a(f"- Özet: {c.get('summary_tr')}")
        if c.get("checklist_tr"):
            for x in c["checklist_tr"]:
                a(f"  - {x}")
        a("")

    a("## 11. Cursor kuralları (kaynak metin)")
    a("")
    for rule_meta in manifest.get("cursor_rules_source") or []:
        path = ROOT / rule_meta["path"]
        if not path.exists():
            # try docs pack copy for host-merge rule
            alt = OUT_DIR / Path(rule_meta["path"]).name
            path = alt if alt.exists() else path
        a(f"### `{rule_meta.get('path')}`")
        a("")
        a(f"Topic: {rule_meta.get('topic')}")
        a("")
        if path.exists():
            body = strip_frontmatter(path.read_text(encoding="utf-8"))
            a("```")
            a(body)
            a("```")
        else:
            a("_Dosya bulunamadı._")
        a("")

    # Also include docs host-merge mdc
    host_mdc = OUT_DIR / "dropt-host-merge.mdc"
    if host_mdc.exists():
        a("### `docs/host-merge/dropt-host-merge.mdc` (hedefe kopyala)")
        a("")
        a("```")
        a(strip_frontmatter(host_mdc.read_text(encoding="utf-8")))
        a("```")
        a("")

    a("## 12. Host merge playbook")
    a("")
    for step in manifest.get("host_merge_playbook") or []:
        a(f"### Adım {step.get('step')}: {step.get('title')}")
        a("")
        for act in step.get("actions") or []:
            a(f"- {act}")
        a("")

    a("## 13. Yapma (do_not)")
    a("")
    for d in manifest.get("do_not") or []:
        a(f"- {d}")
    a("")

    a("## 14. Önce kopyalanacak dosyalar")
    a("")
    for f in manifest.get("files_to_copy_first") or []:
        a(f"- `{f}`")
    a("")

    a("## 15. Host ekibi dolduracak alanlar")
    a("")
    for k, v in (manifest.get("placeholders_for_host_team") or {}).items():
        a(f"- **{k}:** `{v}`")
    a("")

    a("## 16. Hedef Cursor’a örnek prompt")
    a("")
    a("```")
    a("@DROPT-OPS-HANDBOOK.md")
    a("@dropt-host-merge-manifest.json")
    a("@dropt-host-merge.mdc")
    a("@capabilities.json")
    a("")
    a("Dropt Ops Portal'ı bu uygulamaya gömüyoruz.")
    a("El kitabı + manifest + kurallara göre TÜM operasyonların eksiksiz olduğundan emin ol.")
    a("Eksik wizard, API wiring, settings paneli, Centrify/HPSA/ASM/DNS checklist veya")
    a("embedded console akışı varsa tamamla.")
    a("- Login yok (bizde var)")
    a("- Sunucu listesi vCenter; çift tık → Dropt ops console")
    a("- Ayarlar: general/account yok; automation/mail/assistant/repos/centrify/backup Dropt submenu")
    a("- MFA/oturumlar bizde yoksa üst Ayarlar'a taşı")
    a("Önce auth bridge + server identity mapping planı çıkar, sonra gap listesi üret ve uygula.")
    a("```")
    a("")
    a("---")
    a("")
    a("*Otomatik üretildi: `docs/host-merge/generate_ops_handbook.py`*")
    a("")
    return "\n".join(lines)


class HandbookPDF(FPDF):
    def header(self):
        self.set_font("DejaVu", "B", 9)
        self.set_text_color(80, 80, 80)
        self.cell(0, 6, "Dropt Ops Portal — Operasyon & Host Merge El Kitabi", align="L")
        self.ln(8)

    def footer(self):
        self.set_y(-12)
        self.set_font("DejaVu", "", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, f"Sayfa {self.page_no()}/{{nb}}", align="C")


def clean_pdf_text(s: str) -> str:
    # fpdf handles unicode with DejaVu; just normalize
    s = s.replace("\u00a0", " ")
    s = s.replace("→", "->").replace("—", "-").replace("–", "-")
    s = s.replace("≥", ">=").replace("≤", "<=").replace("•", "-")
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    return s


def write_pdf_from_markdown(md: str, out: Path) -> None:
    pdf = HandbookPDF(format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_font("DejaVu", "", FONT)
    pdf.add_font("DejaVu", "B", FONT_BOLD)
    pdf.add_font("DejaVuMono", "", FONT_MONO)
    pdf.add_page()
    pdf.set_text_color(20, 20, 20)
    usable = pdf.w - pdf.l_margin - pdf.r_margin

    def write(text: str, h: float = 5) -> None:
        pdf.set_x(pdf.l_margin)
        # Soft-wrap extremely long unbroken tokens for fpdf
        safe = text if text else " "
        if len(safe) > 200 and " " not in safe[80:]:
            chunks = [safe[i : i + 90] for i in range(0, len(safe), 90)]
            safe = " ".join(chunks)
        pdf.multi_cell(usable, h, safe)

    in_code = False
    for raw in md.splitlines():
        line = clean_pdf_text(raw.rstrip())
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            pdf.set_font("DejaVuMono", "", 7)
            write(line, 3.6)
            continue
        if line.startswith("# "):
            pdf.set_font("DejaVu", "B", 15)
            pdf.ln(2)
            write(line[2:], 7.5)
            pdf.ln(1)
        elif line.startswith("## "):
            pdf.set_font("DejaVu", "B", 12)
            pdf.ln(2)
            write(line[3:], 6.5)
            pdf.ln(1)
        elif line.startswith("### "):
            pdf.set_font("DejaVu", "B", 10.5)
            pdf.ln(1.5)
            write(line[4:], 5.5)
        elif line.startswith("#### "):
            pdf.set_font("DejaVu", "B", 9.5)
            pdf.ln(1)
            write(line[5:], 5)
        elif line.startswith("|"):
            pdf.set_font("DejaVuMono", "", 6.5)
            write(line[:220], 3.5)
        elif line.startswith("> "):
            pdf.set_font("DejaVu", "", 8.5)
            pdf.set_text_color(60, 60, 90)
            write(line[2:], 4.5)
            pdf.set_text_color(20, 20, 20)
        elif line.startswith("- ") or re.match(r"^\d+\. ", line) or line.startswith("  -"):
            pdf.set_font("DejaVu", "", 8.5)
            write(line, 4.5)
        elif line.strip() == "---":
            pdf.ln(1)
            y = pdf.get_y()
            pdf.set_draw_color(180, 180, 180)
            pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.ln(2)
        elif not line.strip():
            pdf.ln(1.5)
        else:
            pdf.set_font("DejaVu", "", 8.5)
            write(line, 4.5)

    pdf.output(str(out))


def main() -> None:
    manifest = load_json(MANIFEST)
    caps = load_json(CAPS)
    md = build_markdown(manifest, caps)
    MD_OUT.write_text(md, encoding="utf-8")
    write_pdf_from_markdown(md, PDF_OUT)
    print(f"Wrote {MD_OUT} ({MD_OUT.stat().st_size} bytes)")
    print(f"Wrote {PDF_OUT} ({PDF_OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
