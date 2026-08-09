import { FormEvent, useEffect, useState } from "react";
import {
  createJob,
  listLogTemplates,
  listServers,
  LogTemplate,
  previewJob,
  ServerPublic,
} from "@dropt/api";
import { ServerPicker } from "@dropt/components/ServerPicker";
import { Button } from "@dropt/components/ui/button";
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

export function LogCollectPage() {
  const token = getToken()!;
  const afterPreview = useAfterPreview();
  const t = useT();
  const { serverId: qServerId } = useServerQuery();
  const [servers, setServers] = useState<ServerPublic[]>([]);
  const [templates, setTemplates] = useState<LogTemplate[]>([]);
  const [serverId, setServerId] = useState("");
  const [hours, setHours] = useState("1");
  const [template, setTemplate] = useState("system");
  const [talepId, setTalepId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void listServers(token, { page: 1, page_size: 200, status: "ready" }).then((d) => {
      setServers(d.items);
      if (qServerId) setServerId(qServerId);
      else if (d.items[0]) setServerId(String(d.items[0].id));
    });
    void listLogTemplates(token).then(setTemplates).catch(() => setTemplates([]));
  }, [token, qServerId]);

  const selectedTemplate = templates.find((t) => t.id === template);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const tid = talepId.trim();
      if (!tid) throw new Error("Talep ID zorunlu");
      if (!serverId) throw new Error("Sunucu seçin");
      const job = await createJob(token, {
        module: "log_collect",
        action: "package",
        talep_id: tid,
        server_ids: [Number(serverId)],
        payload: {
          hours: Number(hours),
          template,
          max_mb: 100,
        },
      });
      afterPreview(await previewJob(token, job.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Paket işi oluşturulamadı");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="px-6 py-6">
      <h2 className="text-xl font-semibold">{t("wizard_logs")}</h2>
      <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
        Salt okuma · son N saatin kayıtlarını zip olarak indir
      </p>

      <form
        onSubmit={onSubmit}
        className="mt-6 max-w-xl space-y-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-5"
      >
        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">Talep ID</label>
          <Input
            value={talepId}
            onChange={(e) => setTalepId(e.target.value)}
            placeholder="Örn. TLP-LOG-001"
            required
          />
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
            Ne kadar geriye bakılsın?
          </label>
          <Select value={hours} onValueChange={setHours}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="1">Son 1 saat</SelectItem>
              <SelectItem value="6">Son 6 saat</SelectItem>
              <SelectItem value="24">Son 24 saat</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
            Uygulama / sistem şablonu
          </label>
          <Select value={template} onValueChange={setTemplate}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(templates.length ? templates : [{ id: "system", label: "Sistem" }]).map((t) => (
                <SelectItem key={t.id} value={t.id}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {selectedTemplate ? (
            <p className="mt-2 text-xs text-[var(--color-muted-foreground)]">
              Kaynaklar:{" "}
              {[
                selectedTemplate.include_journal ? "journalctl" : null,
                ...selectedTemplate.paths,
              ]
                .filter(Boolean)
                .join(", ")}
              {" · "}limit 100 MB
            </p>
          ) : null}
        </div>

        {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}

        <Button type="submit" disabled={busy}>
          {busy ? "Önizleme hazırlanıyor…" : "Paketi hazırla (önizle)"}
        </Button>
      </form>
    </div>
  );
}
