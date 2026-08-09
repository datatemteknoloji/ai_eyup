import { JobPublic, JobStatus, listJobs } from "@/api";

function formatTs(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("tr-TR");
  } catch {
    return iso;
  }
}

function serversLabel(j: JobPublic): string {
  const hosts = (j.hostnames || []).filter(Boolean);
  if (hosts.length) return hosts.join(", ");
  const ids = j.server_ids || [];
  return ids.length ? ids.map((id) => `#${id}`).join(", ") : "—";
}

function jobEventAt(j: JobPublic): string {
  return j.finished_at || j.applied_at || j.previewed_at || j.created_at;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export async function fetchAllFilteredJobs(
  token: string,
  filters: { q?: string; status?: JobStatus | "" },
): Promise<JobPublic[]> {
  const pageSize = 100;
  const first = await listJobs(token, {
    q: filters.q,
    status: filters.status,
    page: 1,
    page_size: pageSize,
  });
  const all = [...first.items];
  const totalPages = Math.max(1, Math.ceil(first.total / pageSize));
  for (let page = 2; page <= totalPages; page += 1) {
    const data = await listJobs(token, {
      q: filters.q,
      status: filters.status,
      page,
      page_size: pageSize,
    });
    all.push(...data.items);
  }
  return all;
}

export function openJobsPdfPrint(
  jobs: JobPublic[],
  opts: { title: string; filterSummary: string; generatedLabel: string },
): void {
  const rows = jobs
    .map((j) => {
      const eventAt = formatTs(jobEventAt(j));
      return `<tr>
        <td>${j.id}</td>
        <td>${escapeHtml(j.talep_id || "—")}</td>
        <td>${escapeHtml(j.title || "")}</td>
        <td>${escapeHtml(serversLabel(j))}</td>
        <td>${escapeHtml(j.status)}</td>
        <td>${escapeHtml(j.created_by_username || "")}</td>
        <td>${j.progress_done}/${j.progress_total}</td>
        <td>${escapeHtml(eventAt)}</td>
      </tr>`;
    })
    .join("");

  const html = `<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <title>${escapeHtml(opts.title)}</title>
  <style>
    @page { size: A4 landscape; margin: 12mm; }
    body { font-family: system-ui, sans-serif; font-size: 11px; color: #111; margin: 0; }
    h1 { font-size: 16px; margin: 0 0 4px; }
    .meta { color: #444; margin-bottom: 12px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border: 1px solid #ccc; padding: 4px 6px; text-align: left; vertical-align: top; }
    th { background: #f3f3f3; font-weight: 600; }
    td { word-break: break-word; }
  </style>
</head>
<body>
  <h1>${escapeHtml(opts.title)}</h1>
  <div class="meta">${escapeHtml(opts.filterSummary)} · ${escapeHtml(opts.generatedLabel)} · ${jobs.length} kayıt</div>
  <table>
    <thead>
      <tr>
        <th>ID</th>
        <th>Talep ID</th>
        <th>Başlık</th>
        <th>Sunucular</th>
        <th>Durum</th>
        <th>Kullanıcı</th>
        <th>İlerleme</th>
        <th>Tarih</th>
      </tr>
    </thead>
    <tbody>${rows || `<tr><td colspan="8">Kayıt yok</td></tr>`}</tbody>
  </table>
  <script>
    window.onload = function () {
      window.focus();
      window.print();
    };
  </script>
</body>
</html>`;

  const w = window.open("", "_blank");
  if (!w) {
    throw new Error("popup_blocked");
  }
  w.document.open();
  w.document.write(html);
  w.document.close();
}
