/** Ayarlar → Mimari GUIDE: A4 yazdırma/PDF. Metin taşmaz (@page + wrap). */

export type ArchGuideSnapshot = {
  version: string
  generated_at: string
  counts: Record<string, number>
  examples: Record<string, string[]>
  hypervisors: Array<{ name: string; type: string; status?: string | null }>
  hottest_datastore?: { name: string; usage_pct: number; free_gb?: number | null } | null
}

function esc(s: unknown): string {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function joinEx(list: string[] | undefined, empty: string): string {
  if (!list?.length) return empty
  return list.map(esc).join(', ')
}

function n(c: Record<string, number>, key: string): string {
  const v = c[key]
  return typeof v === 'number' ? String(v) : '0'
}

function fmtWhen(iso: string, locale: string): string {
  try {
    return new Date(iso).toLocaleString(locale === 'en' ? 'en-GB' : 'tr-TR')
  } catch {
    return iso
  }
}

export function exportArchitectureGuide(snapshot: ArchGuideSnapshot, locale: 'tr' | 'en' = 'tr'): void {
  const c = snapshot.counts || {}
  const ex = snapshot.examples || {}
  const en = locale === 'en'
  const when = fmtWhen(snapshot.generated_at, locale)
  const empty = en ? 'not yet inventoried' : 'henüz envanterde yok'
  const linuxEx = joinEx(ex.linux, empty)
  const vmEx = joinEx(ex.vms, empty)
  const hostEx = joinEx(ex.esxi_hosts, empty)
  const dsEx = joinEx(ex.datastores, empty)
  const hypEx = joinEx(ex.hypervisors, empty)
  const hot = snapshot.hottest_datastore

  const q1 = en
    ? `Example: “Which VMs are on ${hostEx.split(',')[0] || 'the ESXi host'} and what is host CPU?”`
    : `Örnek: “${hostEx.split(',')[0] || 'ESXi host'} üzerindeki VM’ler hangileri, host CPU’su nedir?”`
  const q2 = hot
    ? (en
      ? `Example: “${esc(hot.name)} is ${hot.usage_pct}% full — which VMs use it and when does it fill?”`
      : `Örnek: “${esc(hot.name)} %${hot.usage_pct} dolu — hangi VM’ler kullanıyor, ne zaman dolar?”`)
    : (en
      ? 'Example: “Which datastore will reach 90% first on the 7-day trend?”'
      : 'Örnek: “7 günlük trende göre hangi datastore önce %90’a ulaşır?”')
  const q3 = en
    ? `Example: “Compare CPU of ${linuxEx.split(',')[0] || 'a Linux host'} with the Windows estate.”`
    : `Örnek: “${linuxEx.split(',')[0] || 'Linux host'} CPU’sunu Windows filosu ile karşılaştır.”`

  const title = en
    ? `ainew Architecture Guide v${esc(snapshot.version)}`
    : `ainew Mimari GUIDE v${esc(snapshot.version)}`

  const hypRows = (snapshot.hypervisors || []).map(h =>
    `<tr><td>${esc(h.name)}</td><td>${esc(h.type)}</td><td>${esc(h.status || '—')}</td></tr>`
  ).join('') || `<tr><td colspan="3">${esc(empty)}</td></tr>`

  const body = en ? `
  <h2>1. Purpose</h2>
  <p>ainew is a self-hosted infrastructure operations platform: inventory, metrics, AIOps and natural-language assistants for Linux, Windows, virtualization, OpenShift and Exadata. Inference stays local (Ollama) or on an admin-configured remote gateway — it does not silently fall back.</p>

  <h2>2. This environment (live)</h2>
  <p class="note">Figures below are taken from the database at generation time. They change as inventory syncs.</p>
  <table>
    <tr><th>Layer</th><th>Count</th><th>Sample names</th></tr>
    <tr><td>Physical Linux hosts</td><td>${n(c, 'linux_hosts')}</td><td>${linuxEx}</td></tr>
    <tr><td>Windows hosts</td><td>${n(c, 'windows_hosts')}</td><td>${joinEx(ex.windows, empty)}</td></tr>
    <tr><td>VMs</td><td>${n(c, 'vms')} (${n(c, 'vms_powered_on')} powered on)</td><td>${vmEx}</td></tr>
    <tr><td>ESXi / hypervisor hosts</td><td>${n(c, 'esxi_hosts')}</td><td>${hostEx}</td></tr>
    <tr><td>Datastores</td><td>${n(c, 'datastores')}</td><td>${dsEx}</td></tr>
    <tr><td>Clusters</td><td>${n(c, 'clusters')}</td><td>${joinEx(ex.clusters, empty)}</td></tr>
    <tr><td>vCenter / hypervisor mgr.</td><td>${n(c, 'hypervisors')}</td><td>${hypEx}</td></tr>
    <tr><td>OpenShift clusters</td><td>${n(c, 'openshift_clusters')}</td><td>${joinEx(ex.openshift, empty)}</td></tr>
    <tr><td>Exadata racks</td><td>${n(c, 'exadata_racks')}</td><td>—</td></tr>
    <tr><td>Open events / incidents</td><td>${n(c, 'events_open')} / ${n(c, 'incidents_open')}</td><td>—</td></tr>
    <tr><td>AI-ready Linux / Windows</td><td>${n(c, 'ai_ready_linux')} / ${n(c, 'ai_ready_windows')}</td><td>SSH / WinRM targets</td></tr>
  </table>
  ${hot ? `<p><strong>Capacity signal:</strong> datastore <em>${esc(hot.name)}</em> is at <strong>${hot.usage_pct}%</strong>${hot.free_gb != null ? ` (${hot.free_gb} GB free)` : ''}.</p>` : ''}

  <h2>3. Conceptual architecture</h2>
  <p>Operators use the React SPA (port 3000). Nginx proxies <code>/api/v1</code> to FastAPI (8000). FastAPI talks to TimescaleDB (inventory + time series + pgvector RAG), Redis (queues, cancel flags, caches), Prometheus/Pushgateway (host metrics) and the LLM (Ollama or remote). The Dropt sidecar (Level 1) is a separate API/DB — do not mix it with the ainew database.</p>
  <div class="flow">Browser → Nginx :3000 → FastAPI :8000 → TimescaleDB · Redis · Prometheus · LLM · vCenter/WinRM/SSH</div>

  <h2>4. Logical modules (RBAC)</h2>
  <p>Access is module-based: executive, linux, windows, virtualization, exadata, openshift, ai_automation, integrations, level1, applications, knowledge. Admins see all. A user without virtualization never receives VM/host answers from that estate.</p>
  <table>
    <tr><th>Module</th><th>What it does</th></tr>
    <tr><td>Linux</td><td>SSH inventory, node_exporter metrics, packages, terminal, Linux AI chat</td></tr>
    <tr><td>Windows</td><td>WinRM, windows_exporter, Event Log, updates, Windows AI chat</td></tr>
    <tr><td>Virtualization</td><td>vCenter/OLVM inventory + metrics (no ESXi SSH required), virt chat</td></tr>
    <tr><td>OpenShift / Exadata</td><td>Cluster/node/workload or rack/node views and chat</td></tr>
    <tr><td>AIOps</td><td>Events, incidents, RCA, reports, capacity forecast</td></tr>
    <tr><td>Level 1</td><td>Dropt operations centre (separate stack)</td></tr>
  </table>

  <h2>5. How data moves</h2>
  <p><strong>Physical hosts:</strong> Prometheus scrapes exporters → metric sync writes <code>metric_data</code> (CPU/RAM/disk). Dashboard “Resource usage” reads the latest three series.</p>
  <p><strong>VMs / ESXi:</strong> vCenter APIs (not guest SSH) → <code>virt_vm_metrics</code>, host and datastore tables. Chat tools query the DB first; live API is for a single named entity.</p>
  <p><strong>Chat:</strong> question → scope (one VM vs fleet) → tools (DB / rare live call) → LLM → SSE stream. Admins can cancel; token usage can be shown.</p>

  <h2>6. What you can ask (using this estate)</h2>
  <ul>
    <li>${q1}</li>
    <li>${q2}</li>
    <li>${q3}</li>
    <li>${en ? '“List VMs with VMware Tools not running and their hosts.”' : '“VMware Tools çalışmayan VM’leri host/cluster ile listele.”'}</li>
    <li>${en ? '“Which snapshots are oldest and which datastore is short on free space?”' : '“En eski snapshot’lar hangileri, datastore boş alanı yeterli mi?”'}</li>
  </ul>
  <p>Scope is honoured: a single VM name returns that VM only — not the whole fleet.</p>

  <h2>7. Connected managers</h2>
  <table>
    <tr><th>Name</th><th>Type</th><th>Status</th></tr>
    ${hypRows}
  </table>

  <h2>8. Operating notes</h2>
  <ul>
    <li>AI: local Ollama or configured remote LLM. If remote is down, chat fails clearly — no silent local fallback.</li>
    <li>Prometheus scrape config is not edited by chat; PromQL is read-only.</li>
    <li>Agent mutating tools require human approval. Destructive actions are guarded.</li>
    <li>Metrics retention is typically 30 days (Timescale). Capacity forecasts use Theil–Sen slope + uncertainty.</li>
  </ul>
  ` : `
  <h2>1. Amaç</h2>
  <p>ainew, kendi sunucunuzda çalışan bir altyapı operasyon platformudur: envanter, metrik, AIOps ve Linux / Windows / sanallaştırma / OpenShift / Exadata için doğal dil asistanları. Çıkarım yerelde (Ollama) veya yöneticinin tanımladığı uzak geçitte kalır; uzak kopunca sessizce yerel modele düşülmez.</p>

  <h2>2. Bu ortam (canlı)</h2>
  <p class="note">Sayılar üretim anındaki veritabanından alınır; senkron ilerledikçe değişir.</p>
  <table>
    <tr><th>Katman</th><th>Adet</th><th>Örnek adlar</th></tr>
    <tr><td>Fiziksel Linux host</td><td>${n(c, 'linux_hosts')}</td><td>${linuxEx}</td></tr>
    <tr><td>Windows host</td><td>${n(c, 'windows_hosts')}</td><td>${joinEx(ex.windows, empty)}</td></tr>
    <tr><td>VM</td><td>${n(c, 'vms')} (${n(c, 'vms_powered_on')} açık)</td><td>${vmEx}</td></tr>
    <tr><td>ESXi / hypervisor host</td><td>${n(c, 'esxi_hosts')}</td><td>${hostEx}</td></tr>
    <tr><td>Datastore</td><td>${n(c, 'datastores')}</td><td>${dsEx}</td></tr>
    <tr><td>Cluster</td><td>${n(c, 'clusters')}</td><td>${joinEx(ex.clusters, empty)}</td></tr>
    <tr><td>vCenter / hypervisor yöneticisi</td><td>${n(c, 'hypervisors')}</td><td>${hypEx}</td></tr>
    <tr><td>OpenShift cluster</td><td>${n(c, 'openshift_clusters')}</td><td>${joinEx(ex.openshift, empty)}</td></tr>
    <tr><td>Exadata rack</td><td>${n(c, 'exadata_racks')}</td><td>—</td></tr>
    <tr><td>Açık event / incident</td><td>${n(c, 'events_open')} / ${n(c, 'incidents_open')}</td><td>—</td></tr>
    <tr><td>AI-ready Linux / Windows</td><td>${n(c, 'ai_ready_linux')} / ${n(c, 'ai_ready_windows')}</td><td>SSH / WinRM hedefleri</td></tr>
  </table>
  ${hot ? `<p><strong>Kapasite sinyali:</strong> <em>${esc(hot.name)}</em> datastore %<strong>${hot.usage_pct}</strong> dolu${hot.free_gb != null ? ` (${hot.free_gb} GB boş)` : ''}.</p>` : ''}

  <h2>3. Kavramsal mimari</h2>
  <p>Operatör React arayüzünü (:3000) kullanır. Nginx <code>/api/v1</code> isteklerini FastAPI’ye (:8000) iletir. FastAPI; TimescaleDB (envanter, zaman serisi, pgvector RAG), Redis (kuyruk, iptal, önbellek), Prometheus/Pushgateway (host metrikleri) ve LLM (Ollama veya uzak) ile konuşur. Level 1 Dropt ayrı API/DB’dir — ainew veritabanı ile karıştırılmaz.</p>
  <div class="flow">Tarayıcı → Nginx :3000 → FastAPI :8000 → TimescaleDB · Redis · Prometheus · LLM · vCenter/WinRM/SSH</div>

  <h2>4. Mantıksal modüller (RBAC)</h2>
  <p>Erişim modül bazlıdır: executive, linux, windows, virtualization, exadata, openshift, ai_automation, integrations, level1, applications, knowledge. Admin tümüne erişir. Sanallaştırma yetkisi olmayan kullanıcı o filodan yanıt almaz.</p>
  <table>
    <tr><th>Modül</th><th>Ne yapar</th></tr>
    <tr><td>Linux</td><td>SSH envanter, node_exporter, paket, terminal, Linux sohbet</td></tr>
    <tr><td>Windows</td><td>WinRM, windows_exporter, Event Log, güncelleme, Windows sohbet</td></tr>
    <tr><td>Sanallaştırma</td><td>vCenter/OLVM envanter + metrik (ESXi SSH gerekmez), virt sohbet</td></tr>
    <tr><td>OpenShift / Exadata</td><td>Cluster/node/yük veya rack/node görünümü ve sohbet</td></tr>
    <tr><td>AIOps</td><td>Event, incident, RCA, rapor, kapasite tahmini</td></tr>
    <tr><td>Level 1</td><td>Dropt operasyon merkezi (ayrı yığın)</td></tr>
  </table>

  <h2>5. Veri akışı</h2>
  <p><strong>Fiziksel host:</strong> Prometheus exporter’ları tarar → metric sync <code>metric_data</code> yazar. Dashboard “Kaynak Kullanımı” son CPU/RAM/disk değerini okur.</p>
  <p><strong>VM / ESXi:</strong> vCenter API (guest SSH yok) → <code>virt_vm_metrics</code>, host ve datastore tabloları. Sohbet önce DB’ye bakar; canlı API tek adlı varlık içindir.</p>
  <p><strong>Sohbet:</strong> soru → kapsam (tek VM / filo) → araçlar → LLM → SSE. İptal edilebilir; admin token kullanımını görebilir.</p>

  <h2>6. Bu ortamda sorulabilecekler</h2>
  <ul>
    <li>${q1}</li>
    <li>${q2}</li>
    <li>${q3}</li>
    <li>VMware Tools çalışmayan VM’leri host ve cluster ile listele.</li>
    <li>En eski snapshot’lar hangileri; datastore boş alanı yeterli mi?</li>
  </ul>
  <p>Kapsam korunur: tek VM adı sorulursa filo dökümü gelmez.</p>

  <h2>7. Bağlı yöneticiler</h2>
  <table>
    <tr><th>Ad</th><th>Tip</th><th>Durum</th></tr>
    ${hypRows}
  </table>

  <h2>8. İşletim notları</h2>
  <ul>
    <li>AI: yerel Ollama veya tanımlı uzak model. Uzak koparsa sohbet açık hata verir; sessiz local fallback yoktur.</li>
    <li>Sohbet Prometheus yapılandırmasını değiştirmez; yalnızca PromQL okur.</li>
    <li>Ajanın değiştirici araçları insan onayı ister; yıkıcı işlemler guard ile tutulur.</li>
    <li>Metrik saklama genelde 30 gündür (Timescale). Kapasite tahmini Theil–Sen eğim + belirsizlik aralığı kullanır.</li>
  </ul>
  `

  const printWindow = window.open('', '_blank', 'width=900,height=720')
  if (!printWindow) {
    alert(en ? 'Allow pop-ups to save the PDF.' : 'PDF için açılır pencereye izin verin.')
    return
  }

  printWindow.document.write(`<!DOCTYPE html>
<html lang="${en ? 'en' : 'tr'}">
<head>
  <meta charset="UTF-8">
  <title>${title}</title>
  <style>
    @page { size: A4; margin: 16mm 15mm 18mm 15mm; }
    * { box-sizing: border-box; }
    html, body {
      margin: 0; padding: 0;
      font-family: "Segoe UI", "Helvetica Neue", Helvetica, Arial, sans-serif;
      font-size: 11pt; line-height: 1.45; color: #1a2332;
      word-wrap: break-word; overflow-wrap: anywhere; hyphens: auto;
    }
    body { padding: 8mm 10mm 12mm; max-width: 190mm; }
    h1 { font-size: 18pt; color: #0f2a5c; margin: 0 0 4pt; font-weight: 700; }
    .sub { font-size: 9.5pt; color: #5b6573; margin-bottom: 14pt; }
    h2 {
      font-size: 12.5pt; color: #1d4ed8; margin: 16pt 0 6pt;
      border-bottom: 1.5pt solid #1d4ed8; padding-bottom: 3pt;
      page-break-after: avoid;
    }
    p, li { margin: 0 0 7pt; }
    ul { padding-left: 16pt; margin: 0 0 8pt; }
    table {
      width: 100%; border-collapse: collapse; margin: 8pt 0 12pt;
      font-size: 9.5pt; table-layout: fixed; page-break-inside: avoid;
    }
    th, td {
      border: 0.6pt solid #c5d0de; padding: 4pt 6pt; vertical-align: top;
      overflow-wrap: anywhere; word-break: break-word;
    }
    th { background: #e8f0fe; color: #1e3a8a; text-align: left; font-weight: 600; }
    tr:nth-child(even) td { background: #f7f9fc; }
    code { font-family: Consolas, "Courier New", monospace; font-size: 9.5pt; background: #f1f5f9; padding: 0 3pt; }
    .flow {
      border: 0.8pt solid #93c5fd; background: #eff6ff; padding: 8pt 10pt;
      font-size: 9.5pt; margin: 6pt 0 10pt; page-break-inside: avoid;
    }
    .note { font-size: 9.5pt; color: #4b5563; font-style: italic; }
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
  <h1>${title}</h1>
  <div class="sub">${en ? 'Conceptual &amp; logical architecture · generated' : 'Kavramsal ve mantıksal mimari · üretim'} ${esc(when)}</div>
  ${body}
  <script>setTimeout(function(){ window.print(); }, 350);<\/script>
</body>
</html>`)
  printWindow.document.close()
}
