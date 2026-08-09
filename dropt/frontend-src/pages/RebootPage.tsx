import { FormEvent, useEffect, useState } from "react";
import { createJob, listServers, previewJob, ServerPublic } from "@/api";
import { ServerPicker } from "@/components/ServerPicker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useServerQuery } from "@/hooks/useServerQuery";
import { useAfterPreview } from "@/hooks/useOpsWizard";
import { useT } from "@/i18n/I18nProvider";
import { getToken } from "@/session";

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
      <h2 className="text-xl font-semibold">{t("wizard_reboot")}</h2>
      <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
        Güvenli reboot · Talep ID + sunucu adı onayı zorunlu
      </p>
      <form
        onSubmit={onSubmit}
        className="mt-6 max-w-xl space-y-4 rounded-xl border border-red-500/30 bg-[var(--color-card)] p-5"
      >
        <p className="text-sm text-red-300">Bu işlem sunucuyu kapatır. Yanlış sunucuda çalıştırmayın.</p>
        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">Talep ID</label>
          <Input value={talepId} onChange={(e) => setTalepId(e.target.value)} required />
        </div>
        <ServerPicker
          servers={servers}
          value={serverId ? [Number(serverId)] : []}
          onChange={(ids) => setServerId(ids[0] ? String(ids[0]) : "")}
          multiple={false}
          label="Sunucu"
        />
        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
            Onay — sunucu adını yazın ({selected?.hostname})
          </label>
          <Input className="font-mono" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
        </div>
        {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
        <Button type="submit" variant="destructive" disabled={busy}>
          {busy ? "…" : "Değişiklikleri Önizle"}
        </Button>
      </form>
    </div>
  );
}
