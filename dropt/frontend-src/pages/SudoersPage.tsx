import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  createJob,
  getServer,
  listServerSudoRules,
  listSudoTemplates,
  lookupSudoRules,
  previewJob,
  sudoWhich,
  SudoRuleRow,
  SudoTemplate,
  SudoWhichResult,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useServerQuery } from "@/hooks/useServerQuery";
import { useAfterPreview, useOpsWizard } from "@/hooks/useOpsWizard";
import { useT } from "@/i18n/I18nProvider";
import { getToken } from "@/session";
import { cn } from "@/lib/utils";

export function SudoersPage() {
  const token = getToken()!;
  const afterPreview = useAfterPreview();
  const opsCtx = useOpsWizard();
  const embedded = Boolean(opsCtx?.embedded);
  const t = useT();
  const { serverId } = useServerQuery();

  const [hostname, setHostname] = useState("");
  const [talepId, setTalepId] = useState("");
  const [targetType, setTargetType] = useState<"user" | "group">("user");
  const [targetName, setTargetName] = useState("");
  const [runas, setRunas] = useState("root");
  const [commandsText, setCommandsText] = useState("");
  const [nopasswd, setNopasswd] = useState(false);
  const [templates, setTemplates] = useState<SudoTemplate[]>([]);
  const [rules, setRules] = useState<SudoRuleRow[]>([]);
  const [rulesLoading, setRulesLoading] = useState(false);
  const [peerHost, setPeerHost] = useState("");
  const [peerWho, setPeerWho] = useState("");
  const [peerRules, setPeerRules] = useState<SudoRuleRow[]>([]);
  const [peerBusy, setPeerBusy] = useState(false);
  const [whichCmd, setWhichCmd] = useState("");
  const [whichBusy, setWhichBusy] = useState(false);
  const [whichResult, setWhichResult] = useState<SudoWhichResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadRules = useCallback(async () => {
    if (!serverId) {
      setRules([]);
      return;
    }
    setRulesLoading(true);
    try {
      const res = await listServerSudoRules(token, Number(serverId));
      setRules(res.rules);
    } catch (err) {
      setRules([]);
      setError(err instanceof Error ? err.message : "Sudo kuralları okunamadı");
    } finally {
      setRulesLoading(false);
    }
  }, [token, serverId]);

  useEffect(() => {
    void listSudoTemplates(token).then(setTemplates).catch(() => undefined);
  }, [token]);

  useEffect(() => {
    if (!serverId) {
      setHostname("");
      setRules([]);
      return;
    }
    void getServer(token, Number(serverId))
      .then((s) => setHostname(s.hostname || `#${serverId}`))
      .catch(() => setHostname(`#${serverId}`));
    void loadRules();
  }, [token, serverId, loadRules]);

  function applyTemplate(id: string) {
    const tpl = templates.find((x) => x.id === id);
    if (!tpl) return;
    setCommandsText(tpl.commands.join("\n"));
  }

  function applyPeerRule(rule: SudoRuleRow) {
    setTargetType(rule.is_group ? "group" : "user");
    setTargetName(rule.who.replace(/^%/, ""));
    setRunas(rule.runas || "root");
    setNopasswd(Boolean(rule.nopasswd));
    setCommandsText((rule.commands || []).join("\n"));
  }

  async function onPeerLookup() {
    if (!peerHost.trim() || !peerWho.trim()) return;
    setPeerBusy(true);
    setError(null);
    try {
      const res = await lookupSudoRules(token, peerHost.trim(), peerWho.trim());
      setPeerRules(res.rules);
      if (res.rules.length === 0) {
        setError(`Kopya kaynakta kural yok: ${res.hostname} / ${peerWho.trim()}`);
      }
    } catch (err) {
      setPeerRules([]);
      setError(err instanceof Error ? err.message : "Sorgulanamadı");
    } finally {
      setPeerBusy(false);
    }
  }

  async function onPathLookup() {
    if (!serverId || !whichCmd.trim()) return;
    setWhichBusy(true);
    setError(null);
    setWhichResult(null);
    try {
      // grup seçiliyse PATH user olmaz; as_user boş bırak → root (veya formdaki kısa adı dene)
      const asUser =
        targetType === "user" && targetName.trim() ? targetName.trim() : "";
      const res = await sudoWhich(token, Number(serverId), whichCmd.trim(), asUser || undefined);
      setWhichResult(res);
      if (!res.path) {
        setError(res.note || `"${res.query}" bulunamadı`);
      }
    } catch (err) {
      setWhichResult(null);
      setError(err instanceof Error ? err.message : "Path sorgusu başarısız");
    } finally {
      setWhichBusy(false);
    }
  }

  function appendPathToCommands(path: string) {
    if (!path) return;
    setCommandsText((prev) => {
      const lines = prev
        .split("\n")
        .map((x) => x.trim())
        .filter(Boolean);
      if (lines.includes(path)) return prev;
      return [...lines, path].join("\n");
    });
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!serverId) return;
    const commands = commandsText
      .split("\n")
      .map((x) => x.trim())
      .filter(Boolean);
    if (!targetName.trim() || commands.length === 0 || !talepId.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const job = await createJob(token, {
        module: "sudoers",
        action: "grant",
        talep_id: talepId.trim(),
        server_ids: [Number(serverId)],
        payload: {
          target_name: targetName.trim(),
          target_type: targetType,
          runas: (runas || "root").trim() || "root",
          commands,
          nopasswd,
          template: "",
        },
      });
      afterPreview(await previewJob(token, job.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  const previewReady =
    Boolean(serverId) &&
    Boolean(talepId.trim()) &&
    Boolean(targetName.trim()) &&
    commandsText.split("\n").some((x) => x.trim());

  return (
    <div className={cn("flex min-h-0 flex-col", embedded ? "px-3 py-2" : "px-6 py-6")}>
      <div className="mb-3 shrink-0">
        <h2 className="text-lg font-semibold">{t("wizard_sudo")}</h2>
        <p className="text-xs text-[var(--color-muted-foreground)]">
          Kullanıcı/grup → runas (default root) → absolut komut · /etc/sudoers.d
          {hostname ? ` · ${hostname}` : ""}
        </p>
      </div>

      {!serverId ? (
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
          Sunucu seçilmedi — Server Console’dan Sudo yetkisi’ni açın.
        </div>
      ) : null}

      <div className="space-y-3">
        {/* Mevcut custom kurallar */}
        <section className="rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-4">
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="text-xs font-medium uppercase tracking-wide text-[var(--color-muted-foreground)]">
              Tanımlı yetkiler (root / wheel / Defaults hariç)
            </h3>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              className="h-7"
              disabled={!serverId || rulesLoading}
              onClick={() => void loadRules()}
            >
              {rulesLoading ? "…" : "Yenile"}
            </Button>
          </div>
          {rules.length === 0 ? (
            <p className="text-[11px] text-[var(--color-muted-foreground)]">
              {rulesLoading ? "Okunuyor…" : "Custom kural yok veya okunamadı."}
            </p>
          ) : (
            <ul className="max-h-40 space-y-1 overflow-y-auto font-mono text-[10px]">
              {rules.map((r, i) => (
                <li key={`${r.source_file}-${i}`}>
                  <button
                    type="button"
                    className="w-full rounded border border-transparent px-1.5 py-1 text-left hover:border-emerald-500/30 hover:bg-emerald-500/5"
                    title="Forma kopyala"
                    onClick={() => applyPeerRule(r)}
                  >
                    <span className="text-emerald-200">{r.who}</span>
                    <span className="text-[var(--color-muted-foreground)]">
                      {" "}
                      ({r.runas}) {r.nopasswd ? "NOPASSWD " : ""}
                      {r.commands.join(", ")}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Peer lookup */}
        <section className="rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-4">
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-[var(--color-muted-foreground)]">
            Benzer sunucudan kopya
          </h3>
          <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
            <Input
              className="h-8 font-mono"
              placeholder="kaynak hostname"
              value={peerHost}
              onChange={(e) => setPeerHost(e.target.value)}
            />
            <Input
              className="h-8 font-mono"
              placeholder="user veya %group"
              value={peerWho}
              onChange={(e) => setPeerWho(e.target.value)}
            />
            <Button
              type="button"
              size="sm"
              variant="secondary"
              className="h-8"
              disabled={peerBusy || !peerHost.trim() || !peerWho.trim()}
              onClick={() => void onPeerLookup()}
            >
              {peerBusy ? "…" : "Sorgula"}
            </Button>
          </div>
          {peerRules.length > 0 ? (
            <ul className="mt-2 max-h-28 space-y-1 overflow-y-auto font-mono text-[10px]">
              {peerRules.map((r, i) => (
                <li key={`peer-${i}`}>
                  <button
                    type="button"
                    className="w-full rounded border border-transparent px-1.5 py-1 text-left hover:border-sky-500/30 hover:bg-sky-500/5"
                    onClick={() => applyPeerRule(r)}
                  >
                    <span className="text-sky-200">{r.who}</span>
                    <span className="text-[var(--color-muted-foreground)]">
                      {" "}
                      ({r.runas}) {r.commands.join(", ")}
                    </span>
                    <span className="ml-1 text-[9px] text-sky-400/80">← forma al</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}

          <div className="mt-3 border-t border-[var(--color-border)]/60 pt-3">
            <h4 className="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-[var(--color-muted-foreground)]">
              Path sorgula (which)
            </h4>
            <p className="mb-2 text-[10px] text-[var(--color-muted-foreground)]">
              Kısa ad (örn. systemctl). Önce formdaki kullanıcı login PATH’i; yoksa/bulunamazsa root
              fallback.
            </p>
            <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
              <Input
                className="h-8 font-mono"
                placeholder="systemctl"
                value={whichCmd}
                onChange={(e) => setWhichCmd(e.target.value)}
                disabled={!serverId}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void onPathLookup();
                  }
                }}
              />
              <Button
                type="button"
                size="sm"
                variant="secondary"
                className="h-8"
                disabled={!serverId || whichBusy || !whichCmd.trim()}
                onClick={() => void onPathLookup()}
              >
                {whichBusy ? "…" : "Ara"}
              </Button>
            </div>
            {whichResult?.path ? (
              <button
                type="button"
                className="mt-2 w-full rounded border border-emerald-500/20 bg-emerald-500/5 px-2 py-1.5 text-left font-mono text-[11px] hover:bg-emerald-500/10"
                title="Komut listesine ekle"
                onClick={() => appendPathToCommands(whichResult.path)}
              >
                <span className="text-emerald-200">{whichResult.path}</span>
                <span className="ml-2 text-[10px] text-[var(--color-muted-foreground)]">
                  {whichResult.source === "user"
                    ? `← ${whichResult.as_user}`
                    : whichResult.fallback
                      ? "← root (fallback)"
                      : "← root"}
                  {" · tıkla → komutlara ekle"}
                </span>
                {whichResult.note ? (
                  <span className="mt-0.5 block text-[9px] text-amber-200/80">{whichResult.note}</span>
                ) : null}
              </button>
            ) : null}
          </div>
        </section>

        {/* Grant form */}
        <form
          onSubmit={onSubmit}
          className="space-y-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-4"
        >
          <Input
            className="h-8"
            placeholder={t("talep_id")}
            value={talepId}
            onChange={(e) => setTalepId(e.target.value)}
            disabled={!serverId}
            required
          />

          <div>
            <label className="mb-0.5 block text-[10px] text-[var(--color-muted-foreground)]">
              1. Kullanıcı / Grup
            </label>
            <div className="grid gap-2 sm:grid-cols-[8rem_1fr]">
              <Select
                value={targetType}
                onValueChange={(v) => setTargetType(v as "user" | "group")}
              >
                <SelectTrigger className="h-8">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="user">Kullanıcı</SelectItem>
                  <SelectItem value="group">Grup (%)</SelectItem>
                </SelectContent>
              </Select>
              <Input
                className="h-8 font-mono"
                placeholder={targetType === "group" ? "domain_admins" : "ahmet"}
                value={targetName}
                onChange={(e) => setTargetName(e.target.value)}
                disabled={!serverId}
                required
              />
            </div>
          </div>

          <div>
            <label className="mb-0.5 block text-[10px] text-[var(--color-muted-foreground)]">
              2. Kimin yetkisiyle? (varsayılan: root)
            </label>
            <Input
              className="h-8 font-mono"
              placeholder="root"
              value={runas}
              onChange={(e) => setRunas(e.target.value)}
              disabled={!serverId}
            />
          </div>

          <div>
            <div className="mb-0.5 flex flex-wrap items-center justify-between gap-2">
              <label className="text-[10px] text-[var(--color-muted-foreground)]">
                3. Komut (tam yol) — satır başına bir komut
              </label>
              {templates.length > 0 ? (
                <Select onValueChange={applyTemplate}>
                  <SelectTrigger className="h-7 w-[14rem] text-[10px]">
                    <SelectValue placeholder="Şablon doldur (opsiyonel)" />
                  </SelectTrigger>
                  <SelectContent>
                    {templates.map((tpl) => (
                      <SelectItem key={tpl.id} value={tpl.id}>
                        {tpl.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : null}
            </div>
            <textarea
              className="min-h-[5.5rem] w-full rounded-md border border-[var(--color-border)] bg-transparent px-3 py-2 font-mono text-xs outline-none focus:border-emerald-500/40"
              placeholder={"/usr/bin/systemctl restart httpd\n/usr/bin/systemctl status httpd"}
              value={commandsText}
              onChange={(e) => setCommandsText(e.target.value)}
              disabled={!serverId}
            />
          </div>

          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={nopasswd} onCheckedChange={(v) => setNopasswd(!!v)} />
            Şifre sorulmasın (NOPASSWD)
          </label>

          {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}

          <Button type="submit" size="sm" disabled={busy || !previewReady}>
            {busy ? "…" : t("preview")}
          </Button>
        </form>
      </div>
    </div>
  );
}
