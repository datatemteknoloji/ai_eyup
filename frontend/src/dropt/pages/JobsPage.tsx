import { useCallback, useEffect, useMemo, useState } from "react";
import { FileDown, RefreshCw, Search } from "lucide-react";
import { Link } from "react-router-dom";
import { JobPublic, JobStatus, listJobs } from "@dropt/api";
import { IconButton } from "@dropt/components/IconButton";
import { PaginationBar } from "@dropt/components/PaginationBar";
import { Badge } from "@dropt/components/ui/badge";
import { Button } from "@dropt/components/ui/button";
import { Input } from "@dropt/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@dropt/components/ui/select";
import { SortHeader, useClientSort } from "@dropt/hooks/useClientSort";
import { useT } from "@dropt/i18n/I18nProvider";
import { fetchAllFilteredJobs, openJobsPdfPrint } from "@dropt/lib/exportJobsPdf";
import { getToken } from "@dropt/session";

const PAGE_SIZE = 25;

function statusBadge(status: JobStatus) {
  if (status === "success") return <Badge variant="success">{status}</Badge>;
  if (status === "failed") return <Badge variant="danger">{status}</Badge>;
  if (status === "partial") return <Badge variant="warning">{status}</Badge>;
  if (status === "running" || status === "approved") return <Badge variant="warning">{status}</Badge>;
  if (status === "previewed") return <Badge variant="success">previewed</Badge>;
  return <Badge variant="muted">{status}</Badge>;
}

type JobRow = JobPublic & { event_at: string; progress_label: string; servers_label: string };

function jobEventAt(j: JobPublic): string {
  return j.finished_at || j.applied_at || j.previewed_at || j.created_at;
}

function serversLabel(j: JobPublic): string {
  const hosts = (j.hostnames || []).filter(Boolean);
  if (hosts.length) return hosts.join(", ");
  const ids = j.server_ids || [];
  return ids.length ? ids.map((id) => `#${id}`).join(", ") : "—";
}

function formatTs(iso: string): string {
  try {
    return new Date(iso).toLocaleString("tr-TR");
  } catch {
    return iso;
  }
}

export function JobsPage() {
  const token = getToken()!;
  const t = useT();
  const [items, setItems] = useState<JobPublic[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [qDraft, setQDraft] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<JobStatus | "">("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE) || 1);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listJobs(token, { q, status, page, page_size: PAGE_SIZE });
      setItems(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("list_failed"));
    } finally {
      setLoading(false);
    }
  }, [token, q, status, page, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (page > pageCount) setPage(pageCount);
  }, [page, pageCount]);

  const rows = useMemo<JobRow[]>(
    () =>
      items.map((j) => ({
        ...j,
        event_at: jobEventAt(j),
        progress_label: `${j.progress_done}/${j.progress_total}`,
        servers_label: serversLabel(j),
      })),
    [items],
  );

  const { sorted, sortKey, sortDir, toggle } = useClientSort<JobRow>(rows, "event_at", "desc");

  async function onExportPdf() {
    if (exporting) return;
    setExporting(true);
    setError(null);
    try {
      const jobs = await fetchAllFilteredJobs(token, { q, status });
      const parts: string[] = [];
      parts.push(status ? t("jobs_export_pdf_filters_status", { status }) : t("jobs_export_pdf_filters_all"));
      if (q) parts.push(t("jobs_export_pdf_filters_q", { q }));
      openJobsPdfPrint(jobs, {
        title: t("jobs_export_pdf_title"),
        filterSummary: parts.join(" · "),
        generatedLabel: `${t("jobs_export_pdf_generated")}: ${new Date().toLocaleString("tr-TR")}`,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "";
      setError(msg === "popup_blocked" ? t("jobs_export_pdf_popup") : t("jobs_export_pdf_failed"));
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="px-6 py-6">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">{t("jobs_title")}</h2>
          <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">{t("jobs_subtitle")}</p>
        </div>
        <div className="flex gap-1">
          <IconButton
            icon={FileDown}
            label={exporting ? t("jobs_export_pdf_busy") : t("jobs_export_pdf")}
            disabled={exporting || loading}
            onClick={() => void onExportPdf()}
          />
          <IconButton icon={RefreshCw} label={t("refresh")} onClick={() => void load()} />
        </div>
      </div>

      <div className="mb-4 flex flex-wrap gap-3">
        <div className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-muted-foreground)]" />
          <Input
            className="pl-9"
            placeholder="Talep ID veya başlık…"
            value={qDraft}
            onChange={(e) => setQDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                setPage(1);
                setQ(qDraft.trim());
              }
            }}
          />
        </div>
        <Button
          variant="secondary"
          onClick={() => {
            setPage(1);
            setQ(qDraft.trim());
          }}
        >
          {t("search")}
        </Button>
        <Select
          value={status || "all"}
          onValueChange={(v) => {
            setPage(1);
            setStatus(v === "all" ? "" : (v as JobStatus));
          }}
        >
          <SelectTrigger className="w-[160px]">
            <SelectValue placeholder={t("status")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("all_statuses")}</SelectItem>
            <SelectItem value="draft">draft</SelectItem>
            <SelectItem value="previewed">previewed</SelectItem>
            <SelectItem value="running">running</SelectItem>
            <SelectItem value="success">success</SelectItem>
            <SelectItem value="failed">failed</SelectItem>
            <SelectItem value="partial">partial</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {error ? <p className="mb-3 text-sm text-[var(--color-destructive)]">{error}</p> : null}

      <div className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-card)]/80">
        <table className="w-full text-sm">
          <thead className="border-b border-[var(--color-border)] text-[var(--color-muted-foreground)]">
            <tr>
              <th className="px-3 py-3 text-left">
                <SortHeader label="ID" active={sortKey === "id"} dir={sortDir} onClick={() => toggle("id")} />
              </th>
              <th className="px-3 py-3 text-left">
                <SortHeader
                  label={t("talep_id")}
                  active={sortKey === "talep_id"}
                  dir={sortDir}
                  onClick={() => toggle("talep_id")}
                />
              </th>
              <th className="px-3 py-3 text-left">
                <SortHeader
                  label={t("jobs_col_title")}
                  active={sortKey === "title"}
                  dir={sortDir}
                  onClick={() => toggle("title")}
                />
              </th>
              <th className="px-3 py-3 text-left">
                <SortHeader
                  label={t("jobs_col_servers")}
                  active={sortKey === "servers_label"}
                  dir={sortDir}
                  onClick={() => toggle("servers_label")}
                />
              </th>
              <th className="px-3 py-3 text-left">
                <SortHeader
                  label={t("status")}
                  active={sortKey === "status"}
                  dir={sortDir}
                  onClick={() => toggle("status")}
                />
              </th>
              <th className="px-3 py-3 text-left">
                <SortHeader
                  label={t("user")}
                  active={sortKey === "created_by_username"}
                  dir={sortDir}
                  onClick={() => toggle("created_by_username")}
                />
              </th>
              <th className="px-3 py-3 text-left">
                <SortHeader
                  label={t("jobs_col_progress")}
                  active={sortKey === "progress_label"}
                  dir={sortDir}
                  onClick={() => toggle("progress_label")}
                />
              </th>
              <th className="px-3 py-3 text-left">
                <SortHeader
                  label={t("jobs_col_date")}
                  active={sortKey === "event_at"}
                  dir={sortDir}
                  onClick={() => toggle("event_at")}
                />
              </th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={8} className="px-3 py-8 text-center text-[var(--color-muted-foreground)]">
                  {t("loading")}
                </td>
              </tr>
            ) : sorted.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-3 py-8 text-center text-[var(--color-muted-foreground)]">
                  {t("no_records")}
                </td>
              </tr>
            ) : (
              sorted.map((j) => (
                <tr key={j.id} className="border-t border-[var(--color-border)] hover:bg-[var(--color-accent)]/40">
                  <td className="px-3 py-2.5">
                    <Link
                      className="font-mono text-[var(--color-primary)] hover:underline"
                      to={`/level1/jobs/${j.id}`}
                    >
                      #{j.id}
                    </Link>
                  </td>
                  <td className="px-3 py-2.5 font-mono text-xs">{j.talep_id}</td>
                  <td className="px-3 py-2.5">{j.title}</td>
                  <td
                    className="max-w-[14rem] truncate px-3 py-2.5 font-mono text-xs text-[var(--color-muted-foreground)]"
                    title={j.servers_label}
                  >
                    {j.servers_label}
                  </td>
                  <td className="px-3 py-2.5">{statusBadge(j.status)}</td>
                  <td className="px-3 py-2.5 text-xs text-[var(--color-muted-foreground)]">
                    {j.created_by_username}
                  </td>
                  <td className="px-3 py-2.5 font-mono text-xs">{j.progress_label}</td>
                  <td className="px-3 py-2.5 font-mono text-[11px] text-[var(--color-muted-foreground)]">
                    {formatTs(j.event_at)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        <PaginationBar
          page={page}
          pageCount={pageCount}
          total={total}
          disabled={loading}
          onPageChange={setPage}
        />
      </div>
    </div>
  );
}
