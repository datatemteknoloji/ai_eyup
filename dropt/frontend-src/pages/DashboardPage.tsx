import { useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { ArrowRight, Server, Shield, Wifi } from "lucide-react";
import { getHealth, listServers, UserPublic } from "@/api";
import { useT } from "@/i18n/I18nProvider";
import { getToken } from "@/session";

type OutletCtx = { user: UserPublic; appName: string };

export function DashboardPage() {
  const { user, appName } = useOutletContext<OutletCtx>();
  const token = getToken()!;
  const t = useT();
  const [health, setHealth] = useState("…");
  const [serverTotal, setServerTotal] = useState(0);
  const [readyCount, setReadyCount] = useState(0);

  useEffect(() => {
    void (async () => {
      try {
        const h = await getHealth();
        setHealth(`${h.status} · v${h.version}`);
        const all = await listServers(token, { page: 1, page_size: 1 });
        setServerTotal(all.total);
        const ready = await listServers(token, { status: "ready", page: 1, page_size: 1 });
        setReadyCount(ready.total);
      } catch {
        /* ignore */
      }
    })();
  }, [token]);

  return (
    <div className="px-6 py-6">
      <div className="mb-6">
        <h2 className="text-xl font-semibold tracking-tight">{t("dashboard")}</h2>
        <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
          {appName} {t("dashboard_summary")}: <span className="font-mono">{user.role}</span>
        </p>
      </div>

      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-4">
          <div className="flex items-center gap-2 text-[var(--color-muted-foreground)]">
            <Server className="h-4 w-4" />
            <span className="text-xs uppercase tracking-wide">{t("server")}</span>
          </div>
          <p className="mt-2 text-2xl font-semibold">{serverTotal}</p>
        </div>
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-4">
          <div className="flex items-center gap-2 text-[var(--color-muted-foreground)]">
            <Wifi className="h-4 w-4" />
            <span className="text-xs uppercase tracking-wide">Ready</span>
          </div>
          <p className="mt-2 text-2xl font-semibold text-emerald-300">{readyCount}</p>
        </div>
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-4">
          <div className="flex items-center gap-2 text-[var(--color-muted-foreground)]">
            <Shield className="h-4 w-4" />
            <span className="text-xs uppercase tracking-wide">API</span>
          </div>
          <p className="mt-2 font-mono text-sm text-emerald-300">{health}</p>
        </div>
      </div>

      <Link
        to="/app/servers"
        className="inline-flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-4 py-3 text-sm hover:bg-[var(--color-accent)]"
      >
        {t("go_inventory")}
        <ArrowRight className="h-4 w-4" />
      </Link>
    </div>
  );
}
