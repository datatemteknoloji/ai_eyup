import { FormEvent, useEffect, useState } from "react";
import {
  createJob,
  listPathModes,
  listServers,
  PathMode,
  previewJob,
  ServerPublic,
} from "@dropt/api";
import { SingleServerField } from "@dropt/components/OpsLockedServer";
import { Button } from "@dropt/components/ui/button";
import { Checkbox } from "@dropt/components/ui/checkbox";
import { Input } from "@dropt/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@dropt/components/ui/select";
import { useServerQuery } from "@dropt/hooks/useServerQuery";
import { useAfterPreview } from "@dropt/hooks/useOpsWizard";
import { useT } from "@dropt/i18n/I18nProvider";
import { getToken } from "@dropt/session";

export function PathPermsPage() {
  const token = getToken()!;
  const afterPreview = useAfterPreview();
  const t = useT();
  const { serverId: qServerId } = useServerQuery();
  const [servers, setServers] = useState<ServerPublic[]>([]);
  const [modes, setModes] = useState<PathMode[]>([]);
  const [serverId, setServerId] = useState("");
  const [path, setPath] = useState("");
  const [mode, setMode] = useState("750");
  const [owner, setOwner] = useState("");
  const [group, setGroup] = useState("");
  const [recursive, setRecursive] = useState(false);
  const [talepId, setTalepId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void listServers(token, { page: 1, page_size: 200, status: "ready" }).then((d) => {
      setServers(d.items);
      if (qServerId) setServerId(qServerId);
      else if (d.items[0]) setServerId(String(d.items[0].id));
    });
    void listPathModes(token).then(setModes);
  }, [token, qServerId]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const cleaned = path.trim();
      if (!cleaned.startsWith("/")) throw new Error("Path / ile başlamalı");
      if (!talepId.trim()) throw new Error("Talep ID zorunlu");
      const job = await createJob(token, {
        module: "path_perms",
        action: "set",
        talep_id: talepId.trim(),
        server_ids: [Number(serverId)],
        payload: {
          path: cleaned,
          owner: owner.trim(),
          group: group.trim(),
          mode,
          recursive,
        },
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
      <h2 className="text-xl font-semibold">{t("wizard_path")}</h2>
      <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
        Sunucudaki gerçek path · chown/chmod · kritik sistem dizinleri yasak
      </p>
      <form
        onSubmit={onSubmit}
        className="mt-6 max-w-xl space-y-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-5"
      >
        <Input
          placeholder={t("talep_id")}
          value={talepId}
          onChange={(e) => setTalepId(e.target.value)}
          required
        />
        <SingleServerField
          locked={Boolean(qServerId)}
          servers={servers}
          serverId={serverId}
          onChange={setServerId}
        />
        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">Path</label>
          <Input
            className="font-mono"
            placeholder="/opt/uygulama veya /home/appuser/data"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            required
          />
          <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">
            Path sunucuda var olmalı; önizlemede kontrol edilir.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Input
            className="font-mono"
            placeholder="Sahip user"
            value={owner}
            onChange={(e) => setOwner(e.target.value)}
            required
          />
          <Input
            className="font-mono"
            placeholder="Grup"
            value={group}
            onChange={(e) => setGroup(e.target.value)}
            required
          />
        </div>
        <Select value={mode} onValueChange={setMode}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {modes.map((m) => (
              <SelectItem key={m.id} value={m.id}>
                {m.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <label className="flex items-center gap-2 text-sm text-amber-200/90">
          <Checkbox checked={recursive} onCheckedChange={(v) => setRecursive(!!v)} />
          Alt klasörlere de uygula (dikkat)
        </label>
        {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
        <Button type="submit" disabled={busy}>
          {busy ? "…" : t("preview")}
        </Button>
      </form>
    </div>
  );
}
