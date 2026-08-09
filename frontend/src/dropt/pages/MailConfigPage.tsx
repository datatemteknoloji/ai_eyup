import { FormEvent, useEffect, useState } from "react";
import {
  createJob,
  getMailSettings,
  listServers,
  previewJob,
  ServerPublic,
} from "@dropt/api";
import { ServerPicker } from "@dropt/components/ServerPicker";
import { Button } from "@dropt/components/ui/button";
import { Input } from "@dropt/components/ui/input";
import { useServerQuery } from "@dropt/hooks/useServerQuery";
import { useAfterPreview } from "@dropt/hooks/useOpsWizard";
import { useT } from "@dropt/i18n/I18nProvider";
import { getToken } from "@dropt/session";

export function MailConfigPage() {
  const token = getToken()!;
  const afterPreview = useAfterPreview();
  const t = useT();
  const { serverId: qServerId, serverIds: qServerIds } = useServerQuery();
  const [servers, setServers] = useState<ServerPublic[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [smtpHost, setSmtpHost] = useState("");
  const [testMail, setTestMail] = useState("");
  const [talepId, setTalepId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void listServers(token, { page: 1, page_size: 200, status: "ready" }).then((d) => {
      setServers(d.items);
      const initial = qServerIds.length
        ? qServerIds.map(Number)
        : qServerId
          ? [Number(qServerId)]
          : d.items[0]
            ? [d.items[0].id]
            : [];
      setSelectedIds(initial);
    });
    void getMailSettings(token)
      .then((m) => {
        setSmtpHost(m.smtp_host || "");
        setTestMail(m.smtp_test_mail || "");
      })
      .catch(() => {
        /* ignore */
      });
  }, [token, qServerId, qServerIds.join(",")]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (!talepId.trim()) throw new Error("Talep ID zorunlu");
      if (!selectedIds.length) throw new Error("Sunucu seçin");
      if (!smtpHost.trim()) {
        throw new Error("SMTP host tanımlı değil — Ayarlar → Mail / SMTP bölümünden kaydedin");
      }
      const job = await createJob(token, {
        module: "mail_config",
        action: "configure",
        talep_id: talepId.trim(),
        server_ids: selectedIds,
        payload: {
          smtp_host: smtpHost.trim(),
          smtp_test_mail: testMail.trim(),
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
      <h2 className="text-xl font-semibold">{t("wizard_mail_config")}</h2>
      <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
        sendmail kurulum + DS smart-host · Settings SMTP kullanılır
      </p>

      <form
        onSubmit={onSubmit}
        className="mt-6 max-w-xl space-y-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-5"
      >
        <div className="rounded-lg border border-[var(--warning)]/40 bg-[var(--warning-bg)] px-3 py-2 text-sm leading-relaxed text-[var(--color-foreground)]">
          Talep eden ekibin ÇM üzerinden Relay için Uygulama Üzerinden Mail Gönderim talebini
          oluşturması gerekmektedir.
        </div>

        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">Talep ID</label>
          <Input value={talepId} onChange={(e) => setTalepId(e.target.value)} required />
        </div>

        <ServerPicker
          servers={servers}
          value={selectedIds}
          onChange={setSelectedIds}
          multiple
          label="Sunucu"
        />

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">SMTP Host</label>
            <Input className="font-mono" value={smtpHost} readOnly title="Ayarlar’dan gelir" />
          </div>
          <div>
            <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
              Test mail (opsiyonel)
            </label>
            <Input className="font-mono" value={testMail} readOnly title="Ayarlar’dan gelir" />
          </div>
        </div>
        <p className="text-[11px] text-[var(--color-muted-foreground)]">
          SMTP host ve test adresi Ayarlar → Mail / SMTP bölümünden yönetilir. Uygulama sonrası hedef
          sunucuda 25/tcp ve test mail doğrulamaları opsiyonel çalışır.
        </p>

        {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
        <Button type="submit" disabled={busy || !selectedIds.length}>
          {busy ? "…" : t("preview")}
        </Button>
      </form>
    </div>
  );
}
