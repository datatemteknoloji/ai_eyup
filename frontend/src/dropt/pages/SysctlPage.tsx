import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  createJob,
  getServerSysctl,
  listServers,
  listSysctlAllowed,
  previewJob,
  ServerPublic,
} from "@dropt/api";
import { ServerPicker } from "@dropt/components/ServerPicker";
import { Button } from "@dropt/components/ui/button";
import { Input } from "@dropt/components/ui/input";
import { useServerQuery } from "@dropt/hooks/useServerQuery";
import { useAfterPreview, useOpsWizard } from "@dropt/hooks/useOpsWizard";
import { useT } from "@dropt/i18n/I18nProvider";
import { getToken } from "@dropt/session";

const NONE = "__none__";
const VALUE_RE = /^[0-9]+(?:[ \t]+[0-9]+)*$/;
const LINE_RE = /^([a-zA-Z0-9_.]+)\s*=\s*(.+)$/;

function validateCustomLines(text: string): string | null {
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!.trim();
    if (!line || line.startsWith("#")) continue;
    const m = LINE_RE.exec(line);
    if (!m) return `Satır ${i + 1}: biçim 'parametre = değer' olmalı`;
    if (!VALUE_RE.test(m[2]!.trim())) {
      return `Satır ${i + 1}: değer sayı(lar) olmalı (örn. 10 veya 250 32000 100 200)`;
    }
  }
  return null;
}

export function SysctlPage() {
  const token = getToken()!;
  const afterPreview = useAfterPreview();
  const opsCtx = useOpsWizard();
  const embedded = Boolean(opsCtx?.embedded);
  const t = useT();
  const { serverId: qServerId } = useServerQuery();
  const [servers, setServers] = useState<ServerPublic[]>([]);
  const [presets, setPresets] = useState<string[]>([]);
  const [current, setCurrent] = useState<Record<string, string>>({});
  const [currentCached, setCurrentCached] = useState(false);
  const [currentLoading, setCurrentLoading] = useState(false);
  const [currentRefreshing, setCurrentRefreshing] = useState(false);
  const [currentError, setCurrentError] = useState<string | null>(null);
  const [serverId, setServerId] = useState("");
  const [presetKey, setPresetKey] = useState(NONE);
  const [presetValue, setPresetValue] = useState("");
  const [custom, setCustom] = useState("");
  const [talepId, setTalepId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const effectiveServerId = embedded && opsCtx?.serverId ? opsCtx.serverId : serverId;

  const loadCurrent = useCallback(
    async (opts: { refresh?: boolean } = {}) => {
      if (!effectiveServerId) return;
      const refresh = Boolean(opts.refresh);
      setCurrentLoading(true);
      setCurrentError(null);
      try {
        const data = await getServerSysctl(token, Number(effectiveServerId), { refresh });
        setCurrent(data.values || {});
        setCurrentCached(Boolean(data.cached));
        setCurrentLoading(false);

        // Cache-first: hemen göster, arka planda taze oku
        if (!refresh && data.cached) {
          setCurrentRefreshing(true);
          try {
            const fresh = await getServerSysctl(token, Number(effectiveServerId), { refresh: true });
            setCurrent(fresh.values || {});
            setCurrentCached(false);
          } catch {
            /* cache kalır */
          } finally {
            setCurrentRefreshing(false);
          }
        }
      } catch (err) {
        setCurrent({});
        setCurrentCached(false);
        setCurrentError(err instanceof Error ? err.message : "Mevcut değerler okunamadı");
        setCurrentLoading(false);
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
    void listSysctlAllowed(token)
      .then(setPresets)
      .catch(() => setPresets([]));
  }, [token, qServerId, embedded, opsCtx?.serverId]);

  useEffect(() => {
    void loadCurrent({ refresh: false });
  }, [loadCurrent]);

  function applyRowToForm(key: string, value: string) {
    setPresetKey(key);
    setPresetValue(value || "");
  }

  const customError = useMemo(() => {
    if (!custom.trim()) return null;
    return validateCustomLines(custom);
  }, [custom]);

  const hasPreset = presetKey !== NONE && presetValue.trim().length > 0;
  const hasCustom = custom.trim().length > 0 && !customError;
  const presetValueOk = presetKey === NONE || (presetValue.trim() && VALUE_RE.test(presetValue.trim()));

  const formComplete = useMemo(() => {
    if (!talepId.trim() || !effectiveServerId) return false;
    if (!hasPreset && !hasCustom) return false;
    if (presetKey !== NONE && !presetValueOk) return false;
    if (custom.trim() && customError) return false;
    return true;
  }, [talepId, effectiveServerId, hasPreset, hasCustom, presetKey, presetValueOk, custom, customError]);

  const currentRows = useMemo(() => {
    const keys = presets.length ? presets : Object.keys(current);
    return keys.map((k) => ({ key: k, value: current[k] ?? "" }));
  }, [presets, current]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (!formComplete) throw new Error("Zorunlu alanları doldurun");
      if (custom.trim()) {
        const err = validateCustomLines(custom);
        if (err) throw new Error(err);
      }
      const payload: Record<string, unknown> = {};
      if (presetKey !== NONE) {
        payload.preset_key = presetKey;
        payload.preset_value = presetValue.trim();
      }
      if (custom.trim()) {
        payload.custom = custom;
      }
      const job = await createJob(token, {
        module: "sysctl",
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

  return (
    <div className="px-6 py-6">
      <h2 className="text-xl font-semibold">{t("wizard_sysctl")}</h2>
      <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
        Hazır parametre ve/veya custom · 99-dropt-portal.conf · çakışan /etc satırları # · sysctl -p
      </p>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <form
          onSubmit={onSubmit}
          className="space-y-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-5"
        >
          <Input placeholder={t("talep_id")} value={talepId} onChange={(e) => setTalepId(e.target.value)} required />

          {!embedded ? (
            <ServerPicker
              servers={servers}
              value={serverId ? [Number(serverId)] : []}
              onChange={(ids) => setServerId(ids[0] ? String(ids[0]) : "")}
              multiple={false}
            />
          ) : (
            <p className="text-sm text-[var(--color-muted-foreground)]">
              {t("server")}:{" "}
              <span className="font-mono text-[var(--color-foreground)]">
                {servers.find((s) => String(s.id) === effectiveServerId)?.hostname || effectiveServerId}
              </span>
            </p>
          )}

          <div>
            <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">Hazır parametre</label>
            <div className="max-h-52 overflow-y-auto rounded-md border border-[var(--color-border)] bg-[var(--color-card)]">
              <button
                type="button"
                onClick={() => {
                  setPresetKey(NONE);
                  setPresetValue("");
                }}
                className={`block w-full border-b border-[var(--color-border)] px-3 py-2 text-left text-sm ${
                  presetKey === NONE
                    ? "bg-[var(--color-primary)]/15 text-[var(--color-foreground)]"
                    : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)]"
                }`}
              >
                — Seçme —
              </button>
              {presets.map((k) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => {
                    setPresetKey(k);
                    const cur = current[k];
                    if (cur) setPresetValue(cur);
                  }}
                  className={`block w-full border-b border-[var(--color-border)] px-3 py-2 text-left font-mono text-[12px] last:border-b-0 ${
                    presetKey === k
                      ? "bg-[var(--color-primary)]/15 text-[var(--color-foreground)]"
                      : "text-[var(--color-foreground)] hover:bg-[var(--color-accent)]"
                  }`}
                  title={k}
                >
                  <span className="break-all">{k}</span>
                  {current[k] ? (
                    <span className="mt-0.5 block truncate text-[10px] text-[var(--color-muted-foreground)]">
                      şu an: {current[k]}
                    </span>
                  ) : null}
                </button>
              ))}
            </div>
            {presetKey !== NONE ? (
              <div className="mt-2">
                <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                  Değer <span className="font-mono">({presetKey})</span>
                </label>
                <Input
                  className="font-mono"
                  placeholder={
                    presetKey === "kernel.sem"
                      ? "250 32000 100 200"
                      : presetKey === "net.ipv4.ip_local_port_range"
                        ? "9000 65500"
                        : current[presetKey] || "örn. 10"
                  }
                  value={presetValue}
                  onChange={(e) => setPresetValue(e.target.value)}
                />
                {presetValue.trim() && !VALUE_RE.test(presetValue.trim()) ? (
                  <p className="mt-1 text-xs text-[var(--color-destructive)]">
                    Değer sayı veya boşlukla ayrılmış sayılar olmalı
                  </p>
                ) : (
                  <p className="mt-1 text-[10px] text-[var(--color-muted-foreground)]">
                    Tek sayı veya boşlukla çoklu (örn. 250 32000 100 200)
                  </p>
                )}
              </div>
            ) : null}
          </div>

          <div>
            <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
              Custom parametreler (tekli / çoklu)
            </label>
            <textarea
              className="min-h-[110px] w-full rounded-md border border-[var(--color-border)] bg-transparent px-3 py-2 font-mono text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring)]"
              placeholder={"kernel.panic = 10\nkernel.sem = 250 32000 100 200\nfs.file-max = 6815744"}
              value={custom}
              onChange={(e) => setCustom(e.target.value)}
              spellCheck={false}
            />
            {customError ? (
              <p className="mt-1 text-xs text-[var(--color-destructive)]">{customError}</p>
            ) : (
              <p className="mt-1 text-[10px] text-[var(--color-muted-foreground)]">
                Her satır: parametre = değer · önizlemede sunucuda sysctl -n ile doğrulanır
              </p>
            )}
          </div>

          {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
          <Button type="submit" disabled={busy || !formComplete}>
            {busy ? "…" : t("preview")}
          </Button>
        </form>

        <aside className="rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-5">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-medium">Mevcut değerler</h3>
              <p className="text-[10px] text-[var(--color-muted-foreground)]">
                Hedef sunucu · sysctl -n · çift tıkla → forma aktar
              </p>
            </div>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={currentLoading || currentRefreshing || !effectiveServerId}
              onClick={() => void loadCurrent({ refresh: true })}
            >
              {currentLoading || currentRefreshing ? "…" : t("refresh")}
            </Button>
          </div>
          {currentCached && !currentLoading ? (
            <p className="mb-2 text-[10px] text-[var(--color-muted-foreground)]">
              Cache’den gösteriliyor{currentRefreshing ? " · arka planda yenileniyor…" : ""}
            </p>
          ) : null}
          {currentError ? (
            <p className="text-sm text-[var(--color-destructive)]">{currentError}</p>
          ) : null}
          <div className="max-h-[28rem] overflow-y-auto rounded-md border border-[var(--color-border)]">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-[var(--color-card)] text-[var(--color-muted-foreground)]">
                <tr className="border-b border-[var(--color-border)]">
                  <th className="px-2 py-2 font-medium">Parametre</th>
                  <th className="px-2 py-2 font-medium">Değer</th>
                </tr>
              </thead>
              <tbody>
                {currentLoading && !currentRows.some((r) => r.value) ? (
                  <tr>
                    <td colSpan={2} className="px-2 py-3 text-[var(--color-muted-foreground)]">
                      Yükleniyor…
                    </td>
                  </tr>
                ) : (
                  currentRows.map((r) => (
                    <tr
                      key={r.key}
                      title="Çift tıkla: forma aktar"
                      onDoubleClick={() => applyRowToForm(r.key, r.value)}
                      className={`cursor-pointer border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-accent)] ${
                        presetKey === r.key ? "bg-[var(--color-primary)]/10" : ""
                      }`}
                    >
                      <td className="max-w-[12rem] break-all px-2 py-1.5 font-mono text-[11px]">{r.key}</td>
                      <td className="px-2 py-1.5 font-mono text-[11px] text-[var(--color-muted-foreground)]">
                        {r.value || "—"}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </aside>
      </div>
    </div>
  );
}
