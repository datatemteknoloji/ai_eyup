import { useEffect, useState } from "react";
import { Navigate, useOutletContext } from "react-router-dom";
import { getContainerLogs, getSystemOverview, SystemOverview, UserPublic } from "@/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n/I18nProvider";
import { getToken } from "@/session";

type Ctx = { user: UserPublic };

export function AdminSystemPage() {
  const { user } = useOutletContext<Ctx>();
  const token = getToken()!;
  const t = useT();
  const [data, setData] = useState<SystemOverview | null>(null);
  const [logName, setLogName] = useState("");
  const [lines, setLines] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void getSystemOverview(token)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : t("list_failed")));
  }, [token, t]);

  if (user.role !== "admin") return <Navigate to="/app" replace />;

  async function loadLogs(name: string) {
    setLogName(name);
    const res = await getContainerLogs(token, name);
    setLines(res.lines || []);
    if (res.error) setError(res.error);
  }

  return (
    <div className="px-6 py-6">
      <h2 className="text-xl font-semibold">{t("system_logs")}</h2>
      <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">{t("system_logs_sub")}</p>
      {error ? <p className="mt-3 text-sm text-[var(--color-destructive)]">{error}</p> : null}
      {!data ? (
        <p className="mt-4 text-sm text-[var(--color-muted-foreground)]">{t("loading")}</p>
      ) : (
        <>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-[var(--color-border)] p-4">
              <p className="text-xs text-[var(--color-muted-foreground)]">{t("jobs_title")}</p>
              <p className="text-2xl font-semibold">{data.counts.jobs}</p>
            </div>
            <div className="rounded-xl border border-[var(--color-border)] p-4">
              <p className="text-xs text-[var(--color-muted-foreground)]">{t("audit_title")}</p>
              <p className="text-2xl font-semibold">{data.counts.audit}</p>
            </div>
            <div className="rounded-xl border border-[var(--color-border)] p-4">
              <p className="text-xs text-[var(--color-muted-foreground)]">Docker</p>
              <p className="text-sm">{data.docker_available ? "socket OK" : "socket yok"}</p>
            </div>
          </div>

          <h3 className="mt-6 text-sm font-medium">Konteynerler</h3>
          <div className="mt-2 space-y-2">
            {data.containers.map((c) => (
              <div key={c.name} className="flex items-center justify-between rounded-lg border border-[var(--color-border)] px-3 py-2 text-sm">
                <div>
                  <span className="font-mono">{c.name}</span>
                  <Badge className="ml-2" variant={c.state === "running" ? "success" : "muted"}>
                    {c.status}
                  </Badge>
                </div>
                <Button size="sm" variant="outline" onClick={() => void loadLogs(c.name)}>
                  Log
                </Button>
              </div>
            ))}
            {data.containers.length === 0 ? (
              <p className="text-xs text-[var(--color-muted-foreground)]">Konteyner listesi yok (socket mount gerekli)</p>
            ) : null}
          </div>

          {logName ? (
            <div className="mt-4 rounded-xl border border-[var(--color-border)] bg-[var(--theme-inset)] p-3">
              <p className="mb-2 text-xs text-[var(--color-muted-foreground)]">{logName}</p>
              <pre className="max-h-80 overflow-auto font-mono text-[11px]">{lines.join("\n") || "(boş)"}</pre>
            </div>
          ) : null}

          <h3 className="mt-6 text-sm font-medium">Son işler</h3>
          <ul className="mt-2 space-y-1 text-xs">
            {data.recent_jobs.map((j) => (
              <li key={j.id} className="font-mono">
                #{j.id} {j.status} · {j.talep_id} · {j.title}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
