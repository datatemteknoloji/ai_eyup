/**
 * PDF Export Utility
 * html2canvas + jsPDF ile DOM elementini PDF olarak indirir.
 * Temiz beyaz arka plan üzerinde render edilir.
 */

export interface PdfExportOptions {
  filename?: string
  title?: string
  subtitle?: string
}

/**
 * Verilen DOM elementini PDF olarak indirir.
 * Element görünür olmalı; display:none ise çalışmaz.
 */
export async function exportElementToPdf(
  element: HTMLElement,
  options: PdfExportOptions = {}
): Promise<void> {
  const { default: html2canvas } = await import('html2canvas')
  const { default: jsPDF } = await import('jspdf')

  const filename = options.filename || `rapor_${new Date().toISOString().split('T')[0]}.pdf`

  // Geçici wrapper: beyaz arka plan üzerinde render et
  const wrapper = document.createElement('div')
  wrapper.style.cssText = `
    position: fixed;
    top: -9999px;
    left: -9999px;
    width: 900px;
    background: #ffffff;
    color: #111827;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-size: 13px;
    line-height: 1.6;
    padding: 32px;
    box-sizing: border-box;
  `

  // Başlık bloğu ekle
  if (options.title) {
    const header = document.createElement('div')
    header.style.cssText = `
      border-bottom: 2px solid #1d4ed8;
      padding-bottom: 16px;
      margin-bottom: 20px;
    `
    header.innerHTML = `
      <div style="font-size:20px;font-weight:700;color:#1e3a8a;">${options.title}</div>
      ${options.subtitle ? `<div style="font-size:12px;color:#6b7280;margin-top:4px;">${options.subtitle}</div>` : ''}
      <div style="font-size:11px;color:#9ca3af;margin-top:4px;">
        Oluşturulma: ${new Date().toLocaleString('tr-TR')} · ainew Platform
      </div>
    `
    wrapper.appendChild(header)
  }

  // İçerik klonu — karanlık renkleri açık renge çevir
  const clone = element.cloneNode(true) as HTMLElement
  _convertDarkToLight(clone)
  wrapper.appendChild(clone)

  document.body.appendChild(wrapper)

  try {
    const canvas = await html2canvas(wrapper, {
      scale: 2,
      useCORS: true,
      backgroundColor: '#ffffff',
      logging: false,
      width: 900,
    })

    const pdf = new jsPDF({
      orientation: 'portrait',
      unit: 'mm',
      format: 'a4',
    })

    const pageW = pdf.internal.pageSize.getWidth()
    const pageH = pdf.internal.pageSize.getHeight()
    const margin = 10
    const imgW = pageW - margin * 2
    const imgH = (canvas.height * imgW) / canvas.width

    let y = margin
    let remaining = imgH

    while (remaining > 0) {
      const sliceH = Math.min(pageH - margin * 2, remaining)
      const srcY = (imgH - remaining) * (canvas.height / imgH)
      const srcH = sliceH * (canvas.height / imgH)

      // Sayfa üzerindeki dilim
      const pageCanvas = document.createElement('canvas')
      pageCanvas.width = canvas.width
      pageCanvas.height = srcH
      const ctx = pageCanvas.getContext('2d')!
      ctx.drawImage(canvas, 0, srcY, canvas.width, srcH, 0, 0, canvas.width, srcH)

      const sliceData = pageCanvas.toDataURL('image/jpeg', 0.95)
      pdf.addImage(sliceData, 'JPEG', margin, y, imgW, sliceH)

      remaining -= sliceH
      if (remaining > 0) {
        pdf.addPage()
        y = margin
      }
    }

    pdf.save(filename)
  } finally {
    document.body.removeChild(wrapper)
  }
}

/**
 * Markdown metnini sade HTML'e çevirip yeni pencerede açar → tarayıcı PDF olarak kaydedebilir.
 * jsPDF alternatifsiz yaklaşım — daha iyi typography kontrolü.
 */
export function exportMarkdownToPrintWindow(
  markdown: string,
  options: PdfExportOptions = {}
): void {
  const title = options.title || 'Rapor'
  const filename = options.filename || `rapor_${new Date().toISOString().split('T')[0]}`

  // Basit markdown → HTML dönüştürücü (react-markdown yerine tarayıcıda)
  const html = markdownToHtml(markdown)

  const printWindow = window.open('', '_blank', 'width=900,height=700')
  if (!printWindow) { alert('Popup engelleyici kapalı değil, lütfen izin verin.'); return }

  printWindow.document.write(`<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <title>${title}</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      font-size: 13px;
      line-height: 1.65;
      color: #1f2937;
      background: #fff;
      padding: 40px 48px;
      max-width: 900px;
      margin: 0 auto;
    }
    .doc-header {
      border-bottom: 2px solid #1d4ed8;
      padding-bottom: 16px;
      margin-bottom: 28px;
    }
    .doc-header h1 { font-size: 20px; font-weight: 700; color: #1e3a8a; }
    .doc-header .meta { font-size: 11px; color: #9ca3af; margin-top: 5px; }
    h1 { font-size: 18px; font-weight: 700; color: #1e3a8a; margin: 20px 0 10px; }
    h2 { font-size: 15px; font-weight: 600; color: #1d4ed8; margin: 18px 0 8px; border-left: 3px solid #1d4ed8; padding-left: 10px; }
    h3 { font-size: 13px; font-weight: 600; color: #374151; margin: 14px 0 6px; }
    p { margin: 6px 0 10px; }
    ul, ol { margin: 6px 0 10px 20px; }
    li { margin: 3px 0; }
    strong { font-weight: 600; color: #111827; }
    em { font-style: italic; color: #374151; }
    code {
      background: #f3f4f6;
      border: 1px solid #e5e7eb;
      border-radius: 3px;
      padding: 1px 5px;
      font-family: 'Fira Code', 'Courier New', monospace;
      font-size: 11.5px;
      color: #be185d;
    }
    pre {
      background: #f3f4f6;
      border: 1px solid #e5e7eb;
      border-radius: 6px;
      padding: 12px 16px;
      margin: 10px 0;
      overflow: auto;
    }
    pre code { background: none; border: none; padding: 0; color: #1f2937; }
    table {
      width: 100%;
      border-collapse: collapse;
      margin: 12px 0;
      font-size: 12px;
    }
    th {
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      padding: 7px 10px;
      text-align: left;
      font-weight: 600;
      color: #1e40af;
    }
    td {
      border: 1px solid #e5e7eb;
      padding: 6px 10px;
      vertical-align: top;
    }
    tr:nth-child(even) td { background: #f9fafb; }
    blockquote {
      border-left: 3px solid #3b82f6;
      margin: 10px 0;
      padding: 6px 14px;
      background: #eff6ff;
      color: #374151;
    }
    hr { border: none; border-top: 1px solid #e5e7eb; margin: 18px 0; }
    .no-print { display: none; }

    @media print {
      body { padding: 20px; }
      .no-print { display: none !important; }
    }
  </style>
</head>
<body>
  <div class="doc-header">
    <h1>${title}</h1>
    <div class="meta">
      Oluşturulma: ${new Date().toLocaleString('tr-TR')} &nbsp;·&nbsp; ainew Platform
      ${options.subtitle ? `&nbsp;·&nbsp; ${options.subtitle}` : ''}
    </div>
  </div>

  <div class="no-print" style="margin-bottom:16px;display:flex;gap:8px;">
    <button onclick="window.print()" style="background:#1d4ed8;color:white;border:none;padding:8px 18px;border-radius:6px;cursor:pointer;font-size:13px;">
      🖨️ PDF Olarak Kaydet
    </button>
    <button onclick="window.close()" style="background:#f3f4f6;color:#374151;border:1px solid #d1d5db;padding:8px 14px;border-radius:6px;cursor:pointer;font-size:13px;">
      Kapat
    </button>
  </div>

  <div class="content">
    ${html}
  </div>

  <script>
    document.title = ${JSON.stringify(filename)};
    // Otomatik olarak print dialog aç (küçük gecikme ile)
    setTimeout(() => window.print(), 400);
  <\/script>
</body>
</html>`)
  printWindow.document.close()
}

/** Chat geçmişini (soru-cevap) tek PDF / yazdırma penceresinde açar. */
export function exportChatMessagesToPrintWindow(
  messages: Array<{ role: string; content: string; created_at?: string }>,
  options: PdfExportOptions = {},
): void {
  const parts: string[] = []
  for (const m of messages) {
    if (!m?.content?.trim()) continue
    const isUser = m.role === 'user'
    const label = isUser ? 'Soru' : 'Asistan'
    const when = m.created_at
      ? new Date(m.created_at).toLocaleString('tr-TR')
      : ''
    parts.push(
      `### ${label}${when ? ` — ${when}` : ''}\n\n${m.content.trim()}\n\n---\n`,
    )
  }
  if (parts.length === 0) {
    alert('Dışa aktarılacak mesaj yok')
    return
  }
  exportMarkdownToPrintWindow(parts.join('\n'), {
    title: options.title || 'AI Asistan Sohbeti',
    subtitle: options.subtitle || new Date().toLocaleString('tr-TR'),
    filename: options.filename || `ai_sohbet_${new Date().toISOString().slice(0, 10)}`,
  })
}

// ── Basit Markdown → HTML parser ──────────────────────────────────────────────

function markdownToHtml(md: string): string {
  let html = md
    // Headers
    .replace(/^#### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    // Bold & italic
    .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Code blocks
    .replace(/```[\w]*\n?([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
    // Inline code
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // Blockquote
    .replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>')
    // HR
    .replace(/^---+$/gm, '<hr>')
    // Tables
    .replace(/((?:\|.+\|\n?)+)/g, (table) => {
      const rows = table.trim().split('\n')
      if (rows.length < 2) return table
      const isSep = (row: string) => /^\|[\s|:-]+\|$/.test(row.trim())
      let tableHtml = '<table>'
      let inBody = false
      for (const row of rows) {
        if (isSep(row)) { tableHtml += '<tbody>'; inBody = true; continue }
        const cells = row.split('|').slice(1, -1).map(c => c.trim())
        const tag = !inBody ? 'th' : 'td'
        tableHtml += `<tr>${cells.map(c => `<${tag}>${c}</${tag}>`).join('')}</tr>`
      }
      tableHtml += '</table>'
      return tableHtml
    })
    // Unordered lists
    .replace(/((?:^[-*+] .+\n?)+)/gm, (block) => {
      const items = block.trim().split('\n').map(l => `<li>${l.replace(/^[-*+] /, '')}</li>`).join('')
      return `<ul>${items}</ul>`
    })
    // Ordered lists
    .replace(/((?:^\d+\. .+\n?)+)/gm, (block) => {
      const items = block.trim().split('\n').map(l => `<li>${l.replace(/^\d+\. /, '')}</li>`).join('')
      return `<ol>${items}</ol>`
    })
    // Paragraphs (double newline → <p>)
    .replace(/\n\n+/g, '</p><p>')
    // Single newlines
    .replace(/\n/g, '<br>')

  return `<p>${html}</p>`
}

// ── Koyu tema renk dönüştürücü ────────────────────────────────────────────────

function _convertDarkToLight(el: HTMLElement): void {
  const allEls = el.querySelectorAll('*') as NodeListOf<HTMLElement>
  const darkBgs = ['rgb(15, 23, 42)', 'rgb(30, 41, 59)', 'rgb(51, 65, 85)', '#0f172a', '#1e293b', '#334155']
  const lightColors = ['rgb(248, 250, 252)', 'rgb(241, 245, 249)', 'rgb(226, 232, 240)']

  const force = (e: HTMLElement) => {
    const cs = window.getComputedStyle(e)
    const bg = cs.backgroundColor
    const fg = cs.color

    if (darkBgs.some(d => bg.startsWith(d.substring(0, 10)))) {
      e.style.backgroundColor = '#ffffff'
    } else if (bg === 'transparent' || bg === 'rgba(0, 0, 0, 0)') {
      e.style.backgroundColor = 'transparent'
    }

    if (lightColors.some(l => fg.startsWith(l.substring(0, 10))) || fg === 'rgb(255, 255, 255)') {
      e.style.color = '#1f2937'
    }
  }

  force(el)
  allEls.forEach(force)
}
