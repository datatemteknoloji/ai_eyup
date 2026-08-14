import { FormEvent, useEffect, useState } from "react";
import { createJob, listServers, previewJob, ServerPublic } from "@dropt/api";
import { SingleServerField } from "@dropt/components/OpsLockedServer";
import { Button } from "@dropt/components/ui/button";
import { Input } from "@dropt/components/ui/input";
import { useServerQuery } from "@dropt/hooks/useServerQuery";
import { useAfterPreview } from "@dropt/hooks/useOpsWizard";
import { useT } from "@dropt/i18n/I18nProvider";
import { getToken } from "@dropt/session";

export function RebootPage() {
  const token = getToken()!;
  const afterPreview = useAfterPreview();
  const t = useT();
  const { serverId: qServerId } = useServerQuery();
  const [servers, setServers] = useState<ServerPublic[]>([]);
  const [serverId, setServerId] = useState("");
  const [talepId, setTalepId] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void listServers(token, { page: 1, page_size: 200, status: "ready" }).then((d) => {
      setServers(d.items);
      if (qServerId) setServerId(qServerId);
      else if (d.items[0]) setServerId(String(d.items[0].id));
    });
  }, [token, qServerId]);

  const selected = servers.find((s) => String(s.id) === serverId);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (!talepId.trim()) throw new Error("Talep ID zorunlu");
      if (!selected) throw new Error("Sunucu seçin");
      if (confirm.trim() !== selected.hostname && confirm.trim() !== selected.hostname.split(".")[0]) {
        throw new Error("Onay için sunucu adını birebir yazın");
      }
      const job = await createJob(token, {
        module: "reboot",
        action: "immediate",
        talep_id: talepId.trim(),
        server_ids: [selected.id],
        payload: { confirm_hostname: confirm.trim(), health_timeout_sec: 300 },
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
      <h2 className="text-xl font-semibold tracking-tight">{t("wizard_reboot")}</h2>
      <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
        Güvenli reboot · Talep ID ve sunucu adı onayı zorunlu
      </p>

      <div className="mt-4 max-w-xl rounded-xl border border-[var(--error)]/35 bg-[var(--error-bg)] px-3.5 py-2.5 text-sm text-[var(--error)]">
        Bu işlem sunucuyu yeniden başlatır. Yanlış hedefte çalıştırmayın.
      </div>

      <form
        onSubmit={onSubmit}
        className="mt-4 max-w-xl space-y-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-5"
      >
        <div>
          <label className="mb-1.5 block text-xs text-[var(--color-muted-foreground)]">Talep ID</label>
          <Input className="h-9" value={talepId} onChange={(e) => setTalepId(e.target.value)} required />
        </div>
        <SingleServerField
          locked={Boolean(qServerId)}
          servers={servers}
          serverId={serverId}
          onChange={setServerId}
          label="Sunucu"
        />
        <div>
          <label className="mb-1.5 block text-xs text-[var(--color-muted-foreground)]">
            Onay — sunucu adını yazın ({selected?.hostname || "…"})
          </label>
          <Input
            className="h-9 font-mono"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />
        </div>
        {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
        <div className="flex justify-end border-t border-[var(--color-border)] pt-3">
          <Button type="submit" variant="destructive" className="h-9 px-4" disabled={busy}>
            {busy ? "…" : "Değişiklikleri Önizle"}
          </Button>
        </div>
      </form>
    </div>
  );
}
