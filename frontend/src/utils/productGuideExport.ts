/** Ayarlar → ürün GUIDE: Markdown HTML'ini A4 yazdır / PDF. */

export type ProductGuideDoc = {
  title: string
  version: string
  html: string
  locale: 'tr' | 'en'
  filename?: string
}

function esc(s: unknown): string {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export function exportProductGuide(doc: ProductGuideDoc): void {
  const en = doc.locale === 'en'
  const title = esc(doc.title)
  const ver = esc(doc.version)
  const printWindow = window.open('', '_blank', 'width=920,height=740')
  if (!printWindow) {
    alert(en ? 'Allow pop-ups to save the PDF.' : 'PDF için açılır pencereye izin verin.')
    return
  }

  printWindow.document.write(`<!DOCTYPE html>
<html lang="${en ? 'en' : 'tr'}">
<head>
  <meta charset="UTF-8">
  <title>${title} v${ver}</title>
  <style>
    @page { size: A4; margin: 16mm 15mm 18mm 15mm; }
    * { box-sizing: border-box; }
    html, body {
      margin: 0; padding: 0;
      font-family: "Segoe UI", "Helvetica Neue", Helvetica, Arial, sans-serif;
      font-size: 10.5pt; line-height: 1.45; color: #1a2332;
      word-wrap: break-word; overflow-wrap: anywhere; hyphens: auto;
    }
    body { padding: 8mm 10mm 12mm; max-width: 190mm; }
    h1 { font-size: 17pt; color: #0f2a5c; margin: 0 0 4pt; font-weight: 700; page-break-after: avoid; }
    h2 {
      font-size: 12.5pt; color: #1d4ed8; margin: 16pt 0 6pt;
      border-bottom: 1.5pt solid #1d4ed8; padding-bottom: 3pt;
      page-break-after: avoid;
    }
    h3 { font-size: 11pt; color: #1e3a8a; margin: 12pt 0 5pt; page-break-after: avoid; }
    .sub { font-size: 9pt; color: #5b6573; margin-bottom: 12pt; }
    p, li { margin: 0 0 6pt; }
    ul, ol { padding-left: 16pt; margin: 0 0 8pt; }
    table {
      width: 100%; border-collapse: collapse; margin: 8pt 0 12pt;
      font-size: 9pt; table-layout: fixed; page-break-inside: avoid;
    }
    th, td {
      border: 0.6pt solid #c5d0de; padding: 4pt 6pt; vertical-align: top;
      overflow-wrap: anywhere; word-break: break-word;
    }
    th { background: #e8f0fe; color: #1e3a8a; text-align: left; font-weight: 600; }
    tr:nth-child(even) td { background: #f7f9fc; }
    code { font-family: Consolas, "Courier New", monospace; font-size: 9pt; background: #f1f5f9; padding: 0 3pt; }
    pre {
      border: 0.8pt solid #93c5fd; background: #eff6ff; padding: 8pt 10pt;
      font-size: 8.5pt; margin: 6pt 0 10pt; white-space: pre-wrap;
      overflow-wrap: anywhere; page-break-inside: avoid;
      font-family: Consolas, "Courier New", monospace;
    }
    pre.diagram {
      background: #f8fafc;
      border: 1pt solid #1e3a8a;
      white-space: pre;
      overflow-x: auto;
      overflow-wrap: normal;
      word-break: normal;
      font-size: 7.1pt;
      line-height: 1.2;
      letter-spacing: 0;
    }
    .diagram-label {
      display: block; font-weight: 700; color: #1e3a8a; margin-bottom: 6pt;
      font-family: "Segoe UI", sans-serif; font-size: 8.5pt;
    }
    hr { border: none; border-top: 0.6pt solid #cbd5e1; margin: 14pt 0; }
    .no-print { margin-bottom: 12pt; }
    @media print {
      body { padding: 0; max-width: none; }
      .no-print { display: none !important; }
    }
  </style>
</head>
<body>
  <div class="no-print">
    <button onclick="window.print()" style="background:#1d4ed8;color:#fff;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;">${en ? 'Save as PDF' : 'PDF olarak kaydet'}</button>
    <button onclick="window.close()" style="margin-left:8px;padding:8px 14px;border-radius:6px;border:1px solid #d1d5db;background:#f3f4f6;cursor:pointer;">${en ? 'Close' : 'Kapat'}</button>
  </div>
  <p class="sub">${en ? 'Product architecture &amp; capability guide' : 'Ürün mimari ve yetenek kılavuzu'} · ainew v${ver}</p>
  ${doc.html}
  <script>setTimeout(function(){ window.print(); }, 400);<\/script>
</body>
</html>`)
  printWindow.document.close()
}
