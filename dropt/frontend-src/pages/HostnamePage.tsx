import { FormEvent, useEffect, useState } from "react";
import {
  createJob,
  getHostnameState,
  HostnameState,
  listServers,
  previewJob,
  ServerPublic,
} from "@/api";
import { ServerPicker } from "@/components/ServerPicker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useServerQuery } from "@/hooks/useServerQuery";
import { useAfterPreview } from "@/hooks/useOpsWizard";
import { useI18n } from "@/i18n/I18nProvider";
import { buildHostnameSuccessChecklist } from "@/lib/opsPostchecks";
import { getToken } from "@/session";

export function HostnamePage() {
  const token = getToken()!;
  const afterPreview = useAfterPreview();
  const { t, locale } = useI18n();
  const { serverId: qServerId } = useServerQuery();
  const [servers, setServers] = useState<ServerPublic[]>([]);
  const [serverId, setServerId] = useState("");
  const [state, setState] = useState<HostnameState | null>(null);
  const [shortName, setShortName] = useState("");
  const [domain, setDomain] = useState("");
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

  useEffect(() => {
    if (!serverId) return;
    setLoading(true);
    setError(null);
    void getHostnameState(token, Number(serverId))
      .then((s) => {
        setState(s);
        setShortName(s.short_name || "");
        setDomain(s.domain || "");
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Hostname okunamadı"))
      .finally(() => setLoading(false));
  }, [token, serverId]);

  const newFqdn = domain.trim() ? `${shortName.trim()}.${domain.trim()}` : shortName.trim();
  const oldFqdn = (() => {
    const fq = (state?.fqdn || "").trim();
    if (fq) return fq;
    const s = (state?.short_name || "").trim();
    const d = (state?.domain || "").trim();
    if (s && d) return `${s}.${d}`;
    return s || "—";
  })();
  const ipAddr =
    (state?.ip || "").trim() ||
    servers.find((s) => String(s.id) === serverId)?.ip ||
    "—";
  const displayNewFqdn = newFqdn.trim() || "—";

  const successChecklist = buildHostnameSuccessChecklist(
    locale,
    oldFqdn,
    displayNewFqdn,
    ipAddr,
  );

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const tid = talepId.trim();
      if (!tid) throw new Error("Talep ID zorunlu");
      if (!serverId) throw new Error("Sunucu seçin");
      if (!shortName.trim()) throw new Error("Kısa ad zorunlu");
      const job = await createJob(token, {
        module: "hostname",
        action: "set",
        talep_id: tid,
        server_ids: [Number(serverId)],
        payload: {
          short_name: shortName.trim(),
          domain: domain.trim(),
        },
      });
      afterPreview(await previewJob(token, job.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "İş oluşturulamadı");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="px-6 py-6">
      <h2 className="text-xl font-semibold">{t("wizard_hostname")}</h2>
      <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
        Kısa ad / domain değiştir · Talep ID + önizleme zorunlu
      </p>

      <div className="mt-6 flex w-full flex-col gap-4">
        <form
          onSubmit={onSubmit}
          className="space-y-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-4"
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">Talep ID</label>
              <Input
                className="h-8"
                value={talepId}
                onChange={(e) => setTalepId(e.target.value)}
                placeholder="Örn. TLP-HN-001"
                required
              />
            </div>
            <div className="flex flex-col justify-end">
              <p className="text-xs text-[var(--color-muted-foreground)]">
                Yeni FQDN:{" "}
                <span className="font-mono text-[var(--color-foreground)]">{newFqdn || "—"}</span>
              </p>
            </div>
          </div>

          <ServerPicker
            servers={servers}
            value={serverId ? [Number(serverId)] : []}
            onChange={(ids) => setServerId(ids[0] ? String(ids[0]) : "")}
            multiple={false}
            label="Sunucu"
            listClassName="max-h-36"
          />

          {loading ? (
            <p className="text-sm text-[var(--color-muted-foreground)]">Mevcut durum okunuyor…</p>
          ) : state ? (
            <div className="rounded-lg border border-[var(--color-border)] bg-[var(--theme-inset)] px-3 py-2 text-xs">
              <p>
                Mevcut FQDN: <span className="font-mono">{state.fqdn || "—"}</span>
                {" · "}
                Kısa / domain:{" "}
                <span className="font-mono">
                  {state.short_name || "—"} / {state.domain || "(yok)"}
                </span>
              </p>
              {state.warnings.map((w) => (
                <p key={w} className="mt-1 text-amber-200/90">
                  {w}
                </p>
              ))}
            </div>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">Yeni kısa ad</label>
              <Input
                className="h-8 font-mono"
                value={shortName}
                onChange={(e) => setShortName(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">Domain</label>
              <Input
                className="h-8 font-mono"
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                placeholder="örn. datatem.local"
              />
            </div>
          </div>

          {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}

          <Button type="submit" size="sm" className="h-8" disabled={busy || loading}>
            {busy ? "Önizleme hazırlanıyor…" : "Değişiklikleri Önizle"}
          </Button>
        </form>

        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-card)]/60 p-4 text-sm text-[var(--color-muted-foreground)]">
          <p className="font-medium text-[var(--color-foreground)]">{t("ops_success_checklist")}</p>
          <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">
            {t("ops_success_checklist_hint")}
          </p>
          <ol className="mt-3 list-decimal space-y-3 pl-5">
            {successChecklist.map((item, idx) => (
              <li key={idx} className="whitespace-pre-wrap text-[var(--color-foreground)]/90">
                {item}
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}
