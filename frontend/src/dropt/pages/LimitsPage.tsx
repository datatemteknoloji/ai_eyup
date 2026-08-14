import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  createJob,
  getServerLimits,
  LimitsEntry,
  listLimitsItems,
  listServers,
  previewJob,
  ServerPublic,
} from "@dropt/api";
import { SingleServerField } from "@dropt/components/OpsLockedServer";
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
import { useAfterPreview, useOpsWizard } from "@dropt/hooks/useOpsWizard";
import { useT } from "@dropt/i18n/I18nProvider";
import { getToken } from "@dropt/session";

const NONE = "__none__";
const VALUE_RE = /^(unlimited|[0-9]+)$/i;
const LINE_RE = /^(\S+)\s+(soft|hard|-)\s+(\S+)\s+(\S+)\s*$/i;

function validateCustomLines(text: string): string | null {
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!.trim();
    if (!line || line.startsWith("#")) continue;
    const m = LINE_RE.exec(line);
    if (!m) return `Satır ${i + 1}: biçim 'domain soft|hard|- item value' olmalı`;
    if (!VALUE_RE.test(m[4]!.trim())) {
      return `Satır ${i + 1}: değer sayı veya unlimited olmalı`;
    }
  }
  return null;
}

function entryKey(e: Pick<LimitsEntry, "domain" | "type" | "item">) {
  return `${e.domain}|${e.type}|${e.item}`;
}

export function LimitsPage() {
  const token = getToken()!;
  const afterPreview = useAfterPreview();
  const opsCtx = useOpsWizard();
  const embedded = Boolean(opsCtx?.embedded);
  const t = useT();
  const { serverId: qServerId } = useServerQuery();
  const [servers, setServers] = useState<ServerPublic[]>([]);
  const [items, setItems] = useState<string[]>([]);
  const [entries, setEntries] = useState<LimitsEntry[]>([]);
  const [cached, setCached] = useState(false);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [serverId, setServerId] = useState("");
  const [domain, setDomain] = useState("");
  const [limitType, setLimitType] = useState("soft");
  const [item, setItem] = useState(NONE);
  const [value, setValue] = useState("");
  const [custom, setCustom] = useState("");
  const [verifyUser, setVerifyUser] = useState("");
  const [ulimitText, setUlimitText] = useState<string | null>(null);
  const [talepId, setTalepId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const effectiveServerId = embedded && opsCtx?.serverId ? opsCtx.serverId : serverId;

  const loadCurrent = useCallback(
    async (opts: { refresh?: boolean; user?: string } = {}) => {
      if (!effectiveServerId) return;
      const refresh = Boolean(opts.refresh);
      setLoading(true);
      setListError(null);
      try {
        const data = await getServerLimits(token, Number(effectiveServerId), {
          refresh,
          user: opts.user,
        });
        setEntries(data.entries || []);
        setCached(Boolean(data.cached));
        if (data.ulimit) {
          const soft = Object.entries(data.ulimit.soft || {})
            .map(([k, v]) => `soft ${k}=${v}`)
            .join("\n");
          const hard = Object.entries(data.ulimit.hard || {})
            .map(([k, v]) => `hard ${k}=${v}`)
            .join("\n");
          setUlimitText(`user=${data.ulimit.user}\n${soft}\n${hard}`);
        } else if (data.ulimit_error) {
          setUlimitText(data.ulimit_error);
        }
        setLoading(false);

        if (!refresh && data.cached) {
          setRefreshing(true);
          try {
            const fresh = await getServerLimits(token, Number(effectiveServerId), {
              refresh: true,
              user: opts.user,
            });
            setEntries(fresh.entries || []);
            setCached(false);
            if (fresh.ulimit) {
              const soft = Object.entries(fresh.ulimit.soft || {})
                .map(([k, v]) => `soft ${k}=${v}`)
                .join("\n");
              const hard = Object.entries(fresh.ulimit.hard || {})
                .map(([k, v]) => `hard ${k}=${v}`)
                .join("\n");
              setUlimitText(`user=${fresh.ulimit.user}\n${soft}\n${hard}`);
            }
          } catch {
            /* cache kalır */
          } finally {
            setRefreshing(false);
          }
        }
      } catch (err) {
        setEntries([]);
        setCached(false);
        setListError(err instanceof Error ? err.message : "Limits okunamadı");
        setLoading(false);
      }
    },
    [token, effectiveServerId],
  );

  useEffect(() => {
    void listServers(token, { page: 1, page_size: 200, status: "ready" }).then((d) => {
      setServers(d.items);
      if (embedded && opsCtx?.serverId) setServerId(opsCtx.serverId);
      else if (qServerId) setServerId(qServerId);
      else if (d.items[0]) setServerId(String(d.items[0].id));
    });
    void listLimitsItems(token)
      .then(setItems)
      .catch(() => setItems([]));
  }, [token, qServerId, embedded, opsCtx?.serverId]);

  useEffect(() => {
    void loadCurrent({ refresh: false });
  }, [loadCurrent]);

  function applyRowToForm(e: LimitsEntry) {
    setDomain(e.domain);
    setLimitType(e.type === "-" ? "-" : e.type);
    setItem(e.item);
    setValue(e.value);
    if (!e.domain.startsWith("@") && e.domain !== "*") {
      setVerifyUser(e.domain);
    }
  }

  const customError = useMemo(() => {
    if (!custom.trim()) return null;
    return validateCustomLines(custom);
  }, [custom]);

  const hasPreset =
    domain.trim().length > 0 && item !== NONE && value.trim().length > 0 && VALUE_RE.test(value.trim());
  const hasCustom = custom.trim().length > 0 && !customError;

  const canSubmit = useMemo(() => {
    if (!talepId.trim() || !effectiveServerId) return false;
    if (custom.trim() && customError) return false;
    if (hasPreset || hasCustom) return true;
    return false;
  }, [talepId, effectiveServerId, hasPreset, hasCustom, custom, customError]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (!canSubmit) throw new Error("Zorunlu alanları doldurun");
      if (custom.trim()) {
        const err = validateCustomLines(custom);
        if (err) throw new Error(err);
      }
      const payload: Record<string, unknown> = {};
      if (hasPreset) {
        payload.domain = domain.trim();
        payload.limit_type = limitType;
        payload.item = item;
        payload.value = value.trim();
      }
      if (custom.trim()) {
        payload.custom = custom;
      }
      const job = await createJob(token, {
        module: "limits",
        action: "set",
        talep_id: talepId.trim(),
        server_ids: [Number(effectiveServerId)],
        payload,
      });
      afterPreview(await previewJob(token, job.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  const selectedKey =
    domain.trim() && item !== NONE ? entryKey({ domain: domain.trim(), type: limitType, item }) : "";

  return (
    <div className="px-6 py-6">
      <h2 className="text-xl font-semibold">{t("wizard_limits")}</h2>
      <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
        PAM limits · 99-dropt-portal.conf · çakışan satırlar # · yeni login’de geçerli
      </p>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <form
          onSubmit={onSubmit}
          className="space-y-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-5"
        >
          <Input placeholder={t("talep_id")} value={talepId} onChange={(e) => setTalepId(e.target.value)} required />

          <SingleServerField
            locked={Boolean(qServerId) || embedded}
            servers={servers}
            serverId={effectiveServerId}
            onChange={setServerId}
          />

          <div className="grid items-end gap-3 sm:grid-cols-2">
            <div className="min-w-0">
              <label className="mb-1.5 block text-xs text-[var(--color-muted-foreground)]">
                User / domain
              </label>
              <Input
                className="h-9 font-mono"
                placeholder="oracle, @dba, *"
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
              />
            </div>
            <div className="min-w-0">
              <label className="mb-1.5 block text-xs text-[var(--color-muted-foreground)]">Type</label>
              <Select value={limitType} onValueChange={setLimitType}>
                <SelectTrigger className="h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="soft">soft</SelectItem>
                  <SelectItem value="hard">hard</SelectItem>
                  <SelectItem value="-">- (soft+hard)</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid items-end gap-3 sm:grid-cols-2">
            <div className="min-w-0">
              <label className="mb-1.5 block text-xs text-[var(--color-muted-foreground)]">Item</label>
              <Select value={item} onValueChange={setItem}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="Seçin" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>— Seçme —</SelectItem>
                  {items.map((it) => (
                    <SelectItem key={it} value={it}>
                      {it}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="min-w-0">
              <label className="mb-1.5 block text-xs text-[var(--color-muted-foreground)]">Değer</label>
              <Input
                className="h-9 font-mono"
                placeholder="65536 veya unlimited"
                value={value}
                onChange={(e) => setValue(e.target.value)}
              />
              {value.trim() && !VALUE_RE.test(value.trim()) ? (
                <p className="mt-1 text-xs text-[var(--color-destructive)]">Sayı veya unlimited</p>
              ) : (
                <p className="mt-1 text-[10px] text-[var(--color-muted-foreground)]">
                  stack/memlock genelde KB
                </p>
              )}
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-xs text-[var(--color-muted-foreground)]">
              Custom satırlar (tekli / çoklu)
            </label>
            <textarea
              className="min-h-[200px] w-full resize-y rounded-lg border border-[var(--color-border)] bg-[var(--bg-deep,var(--theme-inset))] px-3 py-2.5 font-mono text-sm leading-relaxed text-[var(--color-foreground)] outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring)]"
              placeholder={"oracle soft nofile 65536\noracle hard nofile 65536\noracle soft nproc 16384"}
              value={custom}
              onChange={(e) => setCustom(e.target.value)}
              spellCheck={false}
              rows={8}
            />
            {customError ? (
              <p className="mt-1 text-xs text-[var(--color-destructive)]">{customError}</p>
            ) : (
              <p className="mt-1 text-[10px] text-[var(--color-muted-foreground)]">
                Her satır: domain soft|hard|- item value
              </p>
            )}
          </div>

          {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
          <Button type="submit" disabled={busy || !canSubmit}>
            {busy ? "…" : t("preview")}
          </Button>
        </form>

        <aside className="rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-5">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-medium">Mevcut limits</h3>
              <p className="text-[10px] text-[var(--color-muted-foreground)]">
                limits.conf + limits.d · çift tıkla → forma aktar
              </p>
            </div>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={loading || refreshing || !effectiveServerId}
              onClick={() => void loadCurrent({ refresh: true })}
            >
              {loading || refreshing ? "…" : t("refresh")}
            </Button>
          </div>
          {cached && !loading ? (
            <p className="mb-2 text-[10px] text-[var(--color-muted-foreground)]">
              Cache’den gösteriliyor{refreshing ? " · arka planda yenileniyor…" : ""}
            </p>
          ) : null}
          {listError ? <p className="text-sm text-[var(--color-destructive)]">{listError}</p> : null}

          <div className="mb-3 flex flex-wrap items-end gap-2">
            <div className="min-w-[8rem] flex-1">
              <label className="mb-1 block text-[10px] text-[var(--color-muted-foreground)]">
                ulimit doğrula (user)
              </label>
              <Input
                className="font-mono"
                placeholder="datatem"
                value={verifyUser}
                onChange={(e) => setVerifyUser(e.target.value)}
              />
            </div>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={!effectiveServerId || !verifyUser.trim() || loading}
              onClick={() => void loadCurrent({ refresh: true, user: verifyUser.trim() })}
            >
              ulimit
            </Button>
          </div>
          {ulimitText ? (
            <pre className="mb-3 max-h-28 overflow-auto rounded-md border border-[var(--color-border)] bg-[var(--color-background)] p-2 font-mono text-[10px] text-[var(--color-muted-foreground)]">
              {ulimitText}
            </pre>
          ) : null}

          <div className="max-h-[28rem] overflow-y-auto rounded-md border border-[var(--color-border)]">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-[var(--color-card)] text-[var(--color-muted-foreground)]">
                <tr className="border-b border-[var(--color-border)]">
                  <th className="px-2 py-2 font-medium">Domain</th>
                  <th className="px-2 py-2 font-medium">Type</th>
                  <th className="px-2 py-2 font-medium">Item</th>
                  <th className="px-2 py-2 font-medium">Value</th>
                </tr>
              </thead>
              <tbody>
                {loading && !entries.length ? (
                  <tr>
                    <td colSpan={4} className="px-2 py-3 text-[var(--color-muted-foreground)]">
                      Yükleniyor…
                    </td>
                  </tr>
                ) : !entries.length ? (
                  <tr>
                    <td colSpan={4} className="px-2 py-3 text-[var(--color-muted-foreground)]">
                      Kayıt yok
                    </td>
                  </tr>
                ) : (
                  entries.map((e) => {
                    const k = entryKey(e);
                    return (
                      <tr
                        key={`${k}|${e.source || ""}`}
                        title={`${e.source || ""}\nÇift tıkla: forma aktar`}
                        onDoubleClick={() => applyRowToForm(e)}
                        className={`cursor-pointer border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-accent)] ${
                          selectedKey === k ? "bg-[var(--color-primary)]/10" : ""
                        }`}
                      >
                        <td className="px-2 py-1.5 font-mono text-[11px]">{e.domain}</td>
                        <td className="px-2 py-1.5 font-mono text-[11px]">{e.type}</td>
                        <td className="px-2 py-1.5 font-mono text-[11px]">{e.item}</td>
                        <td className="px-2 py-1.5 font-mono text-[11px] text-[var(--color-muted-foreground)]">
                          {e.value}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </aside>
      </div>
    </div>
  );
}
