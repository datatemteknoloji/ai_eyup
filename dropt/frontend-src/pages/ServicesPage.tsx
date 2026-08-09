import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  createJob,
  listServers,
  listSystemServices,
  previewJob,
  ServerPublic,
  SystemServiceRow,
} from "@/api";
import { ServerPicker } from "@/components/ServerPicker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAfterPreview } from "@/hooks/useOpsWizard";
import { useServerQuery } from "@/hooks/useServerQuery";
import { useT } from "@/i18n/I18nProvider";
import { cn } from "@/lib/utils";
import { getToken } from "@/session";

type Op = "start" | "stop" | "restart";

function activeBadge(active: string): "success" | "warning" | "danger" | "muted" {
  if (active === "active") return "success";
  if (active === "activating" || active === "deactivating" || active === "reloading") return "warning";
  if (active === "failed") return "danger";
  return "muted";
}

export function ServicesPage() {
  const token = getToken()!;
  const afterPreview = useAfterPreview();
  const t = useT();
  const { serverId: qServerId } = useServerQuery();
  const [servers, setServers] = useState<ServerPublic[]>([]);
  const [serverId, setServerId] = useState("");
  const [rows, setRows] = useState<SystemServiceRow[]>([]);
  const [selectedUnit, setSelectedUnit] = useState("");
  const [op, setOp] = useState<Op>("restart");
  const [talepId, setTalepId] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void listServers(token, { page: 1, page_size: 200, status: "ready" }).then((d) => {
      setServers(d.items);
      if (qServerId) setServerId(qServerId);
      else if (d.items[0]) setServerId(String(d.items[0].id));
    });
  }, [token, qServerId]);

  const refresh = useCallback(() => {
    if (!serverId) return;
    setLoading(true);
    setError(null);
    void listSystemServices(token, Number(serverId))
      .then((d) => {
        setRows(d.services);
        setSelectedUnit((prev) =>
          prev && d.services.some((s) => s.unit === prev) ? prev : d.services[0]?.unit || "",
        );
      })
      .catch((err) => setError(err instanceof Error ? err.message : t("list_failed")))
      .finally(() => setLoading(false));
  }, [token, serverId, t]);

  useEffect(() => {
    setRows([]);
    setSelectedUnit("");
    refresh();
  }, [refresh]);

  const selected = rows.find((r) => r.unit === selectedUnit);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (!talepId.trim()) throw new Error("Talep ID zorunlu");
      if (!serverId) throw new Error("Sunucu seçin");
      if (!selectedUnit) throw new Error("Servis seçin");
      const job = await createJob(token, {
        module: "services",
        action: op,
        talep_id: talepId.trim(),
        server_ids: [Number(serverId)],
        payload: { unit: selectedUnit },
      });
      afterPreview(await previewJob(token, job.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="px-6 py-6">
      <h2 className="text-xl font-semibold">{t("wizard_services")}</h2>
      <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">{t("services_subtitle")}</p>

      <form
        onSubmit={onSubmit}
        className="mt-6 max-w-3xl space-y-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-5"
      >
        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">{t("talep_id")}</label>
          <Input value={talepId} onChange={(e) => setTalepId(e.target.value)} required />
        </div>

        <ServerPicker
          servers={servers}
          value={serverId ? [Number(serverId)] : []}
          onChange={(ids) => setServerId(ids[0] ? String(ids[0]) : "")}
          multiple={false}
          label={t("server")}
        />

        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-[var(--color-muted-foreground)]">
            {t("services_list_hint")}
            {loading ? ` · ${t("loading")}` : null}
          </p>
          <Button type="button" size="sm" variant="outline" onClick={refresh} disabled={loading || !serverId}>
            {t("services_refresh")}
          </Button>
        </div>

        <div className="max-h-72 overflow-y-auto rounded-lg border border-[var(--color-border)]">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-[var(--theme-surface-deep)] text-[var(--color-muted-foreground)]">
              <tr>
                <th className="px-3 py-2 font-medium">{t("services_col_unit")}</th>
                <th className="px-3 py-2 font-medium">{t("services_col_active")}</th>
                <th className="px-3 py-2 font-medium">{t("services_col_enabled")}</th>
                <th className="px-3 py-2 font-medium">{t("services_col_desc")}</th>
              </tr>
            </thead>
            <tbody>
              {!rows.length && !loading ? (
                <tr>
                  <td colSpan={4} className="px-3 py-6 text-center text-[var(--color-muted-foreground)]">
                    {t("services_empty")}
                  </td>
                </tr>
              ) : null}
              {rows.map((r) => {
                const on = r.unit === selectedUnit;
                return (
                  <tr
                    key={r.unit}
                    className={cn(
                      "cursor-pointer border-t border-[var(--color-border)] hover:bg-[var(--color-accent)]",
                      on && "bg-[var(--color-primary)]/10",
                      !r.operable && "opacity-50",
                    )}
                    onClick={() => r.operable && setSelectedUnit(r.unit)}
                  >
                    <td className="px-3 py-2 font-mono text-[var(--theme-link)]">{r.name}</td>
                    <td className="px-3 py-2">
                      <Badge variant={activeBadge(r.active)}>{r.active}</Badge>
                    </td>
                    <td className="px-3 py-2 font-mono text-[var(--color-muted-foreground)]">{r.enabled}</td>
                    <td className="max-w-[14rem] truncate px-3 py-2 text-[var(--color-muted-foreground)]" title={r.description}>
                      {r.description || "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div>
          <label className="mb-1.5 block text-xs text-[var(--color-muted-foreground)]">{t("services_operation")}</label>
          <div className="flex flex-wrap gap-2">
            {(
              [
                ["start", t("services_op_start")],
                ["stop", t("services_op_stop")],
                ["restart", t("services_op_restart")],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => setOp(id)}
                className={cn(
                  "rounded-md border px-3 py-1.5 text-sm",
                  op === id
                    ? "border-[var(--color-primary)] bg-[var(--color-primary)]/15 text-[var(--theme-success-fg)]"
                    : "border-[var(--color-border)] text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)]",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {selected ? (
          <p className="font-mono text-[11px] text-[var(--color-muted-foreground)]">
            {selected.unit} · {selected.active}/{selected.sub_state || "—"} · {selected.fragment_path || "—"}
          </p>
        ) : null}

        {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}

        <Button type="submit" disabled={busy || !selectedUnit || !selected?.operable}>
          {busy ? "…" : t("preview")}
        </Button>
      </form>
    </div>
  );
}
