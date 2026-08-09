import { useCallback, useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";
import { AuditPublic, listAudit } from "@dropt/api";
import { PaginationBar } from "@dropt/components/PaginationBar";
import { Badge } from "@dropt/components/ui/badge";
import { Button } from "@dropt/components/ui/button";
import { Input } from "@dropt/components/ui/input";
import { SortHeader, useClientSort } from "@dropt/hooks/useClientSort";
import { useT } from "@dropt/i18n/I18nProvider";
import { getToken } from "@dropt/session";

const PAGE_SIZE = 50;

type AuditRow = AuditPublic & { who: string; message_sort: string };

export function AuditPage() {
  const token = getToken()!;
  const t = useT();
  const [items, setItems] = useState<AuditPublic[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [qDraft, setQDraft] = useState("");
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE) || 1);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listAudit(token, { q, page, page_size: PAGE_SIZE });
      setItems(data.items);
      setTotal(data.total);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("list_failed"));
    } finally {
      setLoading(false);
    }
  }, [token, q, page, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (page > pageCount) setPage(pageCount);
  }, [page, pageCount]);

  const rows = useMemo<AuditRow[]>(
    () =>
      items.map((a) => ({
        ...a,
        who: `${a.username} ${a.role}`,
        message_sort: a.message || a.hostname || "",
      })),
    [items],
  );

  const { sorted, sortKey, sortDir, toggle } = useClientSort<AuditRow>(rows, "created_at", "desc");

  return (
    <div className="px-6 py-6">
      <h2 className="text-xl font-semibold">{t("audit_title")}</h2>
      <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">{t("audit_subtitle")}</p>

      <div className="my-4 flex flex-wrap gap-3">
        <div className="relative min-w-[240px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-muted-foreground)]" />
          <Input
            className="pl-9"
            placeholder="Talep ID, aksiyon, kullanıcı…"
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
      </div>

      {error ? <p className="mb-3 text-sm text-[var(--color-destructive)]">{error}</p> : null}

      <div className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-card)]/80">
        <table className="w-full text-sm">
          <thead className="border-b border-[var(--color-border)] text-[var(--color-muted-foreground)]">
            <tr>
              <th className="px-3 py-3 text-left">
                <SortHeader
                  label={t("audit_col_time")}
                  active={sortKey === "created_at"}
                  dir={sortDir}
                  onClick={() => toggle("created_at")}
                />
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
                  label={t("audit_col_who")}
                  active={sortKey === "who"}
                  dir={sortDir}
                  onClick={() => toggle("who")}
                />
              </th>
              <th className="px-3 py-3 text-left">
                <SortHeader
                  label={t("audit_col_action")}
                  active={sortKey === "action"}
                  dir={sortDir}
                  onClick={() => toggle("action")}
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
                  label={t("audit_col_message")}
                  active={sortKey === "message_sort"}
                  dir={sortDir}
                  onClick={() => toggle("message_sort")}
                />
              </th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-[var(--color-muted-foreground)]">
                  {t("loading")}
                </td>
              </tr>
            ) : sorted.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-[var(--color-muted-foreground)]">
                  {t("no_records")}
                </td>
              </tr>
            ) : (
              sorted.map((a) => (
                <tr key={a.id} className="border-t border-[var(--color-border)] align-top">
                  <td className="px-3 py-2.5 font-mono text-[11px] text-[var(--color-muted-foreground)]">
                    {new Date(a.created_at).toLocaleString("tr-TR")}
                  </td>
                  <td className="px-3 py-2.5 font-mono text-xs">{a.talep_id || "—"}</td>
                  <td className="px-3 py-2.5 text-xs">
                    {a.username}
                    <div className="text-[var(--color-muted-foreground)]">{a.role}</div>
                  </td>
                  <td className="px-3 py-2.5 font-mono text-[11px]">{a.action}</td>
                  <td className="px-3 py-2.5">
                    <Badge
                      variant={
                        a.status === "success" ? "success" : a.status === "failed" ? "danger" : "muted"
                      }
                    >
                      {a.status}
                    </Badge>
                  </td>
                  <td className="max-w-[360px] px-3 py-2.5 text-xs">
                    <div className="truncate" title={a.message}>
                      {a.message || a.hostname || "—"}
                    </div>
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
