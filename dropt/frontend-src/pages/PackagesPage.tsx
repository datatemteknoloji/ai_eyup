import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  createJob,
  dnfSearch,
  getPackageContext,
  getServer,
  listPackageVersions,
  PackageContext,
  PackageSearchHit,
  PkgLocalRepoRow,
  previewJob,
} from "@/api";
import { Button } from "@/components/ui/button";
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

export function PackagesPage() {
  const token = getToken()!;
  const afterPreview = useAfterPreview();
  const opsCtx = useOpsWizard();
  const embedded = Boolean(opsCtx?.embedded);
  const t = useT();
  const { serverId } = useServerQuery();
  const [hostname, setHostname] = useState("");
  const [ctx, setCtx] = useState<PackageContext | null>(null);
  const [mode, setMode] = useState<string>("general"); // general | keyword
  const [talepId, setTalepId] = useState("");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<PackageSearchHit[]>([]);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [dataMount, setDataMount] = useState("");
  const [packageVersion, setPackageVersion] = useState("latest");
  const [versionOpts, setVersionOpts] = useState<string[]>([]);
  const [loadingVersions, setLoadingVersions] = useState(false);
  const [searching, setSearching] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeRepo: PkgLocalRepoRow | null = useMemo(() => {
    if (mode === "general" || !ctx) return null;
    return ctx.keywords.find((k) => k.keyword === mode) || null;
  }, [mode, ctx]);

  const showVersionPicker = useMemo(() => {
    if (!activeRepo) return false;
    const post = activeRepo.post_commands || "";
    return mode === "docker" || post.includes("{{docker_pkgs}}");
  }, [activeRepo, mode]);

  useEffect(() => {
    setPackageVersion("latest");
    setVersionOpts([]);
  }, [mode]);

  useEffect(() => {
    if (!serverId) {
      setHostname("");
      setCtx(null);
      return;
    }
    void getServer(token, Number(serverId))
      .then((s) => setHostname(s.hostname || `#${serverId}`))
      .catch(() => setHostname(`#${serverId}`));
    void getPackageContext(token, Number(serverId))
      .then((c) => {
        setCtx(c);
        setDataMount(c.data_mounts[0]?.mount || "");
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Bağlam okunamadı"));
  }, [token, serverId]);

  const onSearch = useCallback(async () => {
    if (!serverId || !query.trim()) return;
    setSearching(true);
    setError(null);
    try {
      const res = await dnfSearch(token, Number(serverId), query.trim());
      setHits(res.results);
    } catch (err) {
      setHits([]);
      setError(err instanceof Error ? err.message : "Arama başarısız");
    } finally {
      setSearching(false);
    }
  }, [token, serverId, query]);

  const onFetchVersions = useCallback(async () => {
    if (!serverId || !showVersionPicker) return;
    setLoadingVersions(true);
    setError(null);
    try {
      const res = await listPackageVersions(token, Number(serverId), {
        keyword: mode,
        package: "docker-ce",
      });
      setVersionOpts(res.versions);
      if (packageVersion !== "latest" && !res.versions.includes(packageVersion)) {
        setPackageVersion("latest");
      }
    } catch (err) {
      setVersionOpts([]);
      setError(err instanceof Error ? err.message : "Sürüm listesi alınamadı");
    } finally {
      setLoadingVersions(false);
    }
  }, [token, serverId, showVersionPicker, mode, packageVersion]);

  function togglePkg(name: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  const previewReady = useMemo(() => {
    if (!serverId || !talepId.trim()) return false;
    if (mode === "general") return selected.size >= 1;
    if (!activeRepo) return false;
    if (activeRepo.needs_data_mount && !dataMount) return false;
    if (activeRepo.source_type === "portal_files") return true;
    const hasPost = Boolean((activeRepo.post_commands || "").trim());
    // nfs + subscription: paket veya post_commands
    return selected.size >= 1 || hasPost;
  }, [serverId, talepId, mode, selected.size, activeRepo, dataMount]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!previewReady || !serverId) return;
    setBusy(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = {
        packages: Array.from(selected),
      };
      if (mode !== "general") {
        payload.keyword = mode;
        if (activeRepo?.needs_data_mount) payload.data_mount = dataMount;
        if (showVersionPicker) payload.package_version = packageVersion || "latest";
      }
      const job = await createJob(token, {
        module: "packages",
        action: "install",
        talep_id: talepId.trim(),
        server_ids: [Number(serverId)],
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
    <div className={cn("flex min-h-0 flex-col", embedded ? "px-3 py-2" : "px-6 py-6")}>
      <div className="mb-3 shrink-0">
        <h2 className="text-lg font-semibold">{t("wizard_packages")}</h2>
        <p className="text-xs text-[var(--color-muted-foreground)]">
          Genel dnf · NFS / Portal RPM / Subscription keyword ·{" "}
          {ctx?.os?.pretty || "OS ?"}
          {ctx ? (ctx.subscription_key_set ? " · activation key var" : " · key yok (mevcut sub)") : ""}
          {hostname ? ` · ${hostname}` : ""}
        </p>
      </div>

      {!serverId ? (
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
          Sunucu seçilmedi — Server Console’dan Paket kur’u açın.
        </div>
      ) : null}

      <form
        onSubmit={onSubmit}
        className="flex min-h-0 flex-1 flex-col gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-4"
      >
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => setMode("general")}
            className={cn(
              "rounded border px-2 py-0.5 text-[11px]",
              mode === "general"
                ? "border-emerald-400/50 bg-emerald-500/20 text-emerald-100"
                : "border-[var(--color-border)] text-[var(--color-muted-foreground)]",
            )}
          >
            Genel
          </button>
          {(ctx?.keywords || []).map((k) => (
            <button
              key={k.keyword}
              type="button"
              onClick={() => setMode(k.keyword)}
              className={cn(
                "rounded border px-2 py-0.5 font-mono text-[11px]",
                mode === k.keyword
                  ? "border-emerald-400/50 bg-emerald-500/20 text-emerald-100"
                  : "border-[var(--color-border)] text-[var(--color-muted-foreground)]",
              )}
              title={
                k.source_type === "portal_files"
                  ? `${k.portal_path}/${k.file_glob || "*.rpm"}`
                  : k.source_type === "subscription"
                    ? "Satellite/dnf + post_commands"
                    : k.nfs_path
              }
            >
              {k.label || k.keyword}
              {k.source_type === "portal_files" ? " · RPM" : ""}
              {k.source_type === "subscription" ? " · Sub" : ""}
              {k.needs_data_mount ? " · FS" : ""}
            </button>
          ))}
        </div>

        <div className="grid shrink-0 gap-2 sm:grid-cols-[1fr_auto]">
          <Input
            className="h-8"
            placeholder={t("talep_id")}
            value={talepId}
            onChange={(e) => setTalepId(e.target.value)}
            disabled={!serverId}
            required
          />
          <span className="self-center font-mono text-[11px] text-[var(--color-muted-foreground)]">
            {hostname || "—"}
          </span>
        </div>

        {activeRepo?.needs_data_mount ? (
          <div>
            <label className="mb-0.5 block text-[10px] text-[var(--color-muted-foreground)]">
              Data dizini (FS mount)
            </label>
            <Select value={dataMount || undefined} onValueChange={setDataMount}>
              <SelectTrigger className="h-8">
                <SelectValue placeholder="Mount seçin" />
              </SelectTrigger>
              <SelectContent>
                {(ctx?.data_mounts || []).map((m) => (
                  <SelectItem key={m.mount} value={m.mount}>
                    {m.mount}
                    {m.avail ? ` · boş ${m.avail}` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ) : null}

        {showVersionPicker ? (
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[10rem] flex-1">
              <label className="mb-0.5 block text-[10px] text-[var(--color-muted-foreground)]">
                Docker sürümü (opsiyonel · default Latest)
              </label>
              <Select value={packageVersion} onValueChange={setPackageVersion}>
                <SelectTrigger className="h-8">
                  <SelectValue placeholder="Latest" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="latest">Latest (son sürüm)</SelectItem>
                  {versionOpts.map((v) => (
                    <SelectItem key={v} value={v}>
                      {v}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              className="h-8"
              disabled={!serverId || loadingVersions}
              onClick={() => void onFetchVersions()}
            >
              {loadingVersions ? "…" : "Sürümleri getir"}
            </Button>
          </div>
        ) : null}

        {activeRepo?.source_type === "portal_files" ? (
          <div className="space-y-2 rounded-lg border border-[var(--color-border)] bg-[var(--theme-surface-deep)] p-3">
            <p className="text-[11px] text-[var(--color-muted-foreground)]">
              Portal RPM keyword <span className="font-mono text-emerald-200">{mode}</span>
            </p>
            <p className="font-mono text-[10px] text-[var(--color-foreground)]">
              {activeRepo.portal_path}/{activeRepo.file_glob || "*.rpm"}
            </p>
            <p className="text-[10px] text-[var(--color-muted-foreground)]">
              Dosyalar hedefte /tmp dizinine kopyalanıp <span className="font-mono">dnf localinstall</span>{" "}
              ile kurulur; ardından /tmp temizlenir.
            </p>
            {activeRepo.post_commands ? (
              <pre className="max-h-32 overflow-auto rounded border border-[var(--color-border)] p-2 font-mono text-[9px] text-[var(--color-muted-foreground)]">
                {activeRepo.post_commands.slice(0, 1200)}
              </pre>
            ) : null}
          </div>
        ) : activeRepo?.source_type === "subscription" ? (
          <div className="space-y-2 rounded-lg border border-[var(--color-border)] bg-[var(--theme-surface-deep)] p-3">
            <p className="text-[11px] text-[var(--color-muted-foreground)]">
              Subscription keyword <span className="font-mono text-emerald-200">{mode}</span> — Satellite/dnf
              + tanımlı post komutlar. İsteğe bağlı ekstra paket:
            </p>
            <Input
              className="h-8 font-mono"
              placeholder="opsiyonel: docker-ce … (boş=yalnız post_commands / {{docker_pkgs}})"
              value={Array.from(selected).join(" ")}
              onChange={(e) =>
                setSelected(
                  new Set(
                    e.target.value
                      .split(/\s+/)
                      .map((x) => x.trim())
                      .filter(Boolean),
                  ),
                )
              }
            />
            {activeRepo.post_commands ? (
              <pre className="max-h-32 overflow-auto rounded border border-[var(--color-border)] p-2 font-mono text-[9px] text-[var(--color-muted-foreground)]">
                {activeRepo.post_commands.slice(0, 1200)}
              </pre>
            ) : (
              <p className="text-[10px] text-amber-200/90">
                Bu reçetede post_commands yok — en az bir paket seçin/yazın.
              </p>
            )}
          </div>
        ) : mode === "general" || !activeRepo?.post_commands ? (
          <>
            <div className="flex shrink-0 gap-2">
              <Input
                className="h-8"
                placeholder="paket ara"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                disabled={!serverId || searching}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void onSearch();
                  }
                }}
              />
              <Button
                type="button"
                size="sm"
                variant="secondary"
                className="h-8"
                disabled={!serverId || searching || !query.trim()}
                onClick={() => void onSearch()}
              >
                {searching ? "…" : "Ara"}
              </Button>
            </div>
            <div className="min-h-0 max-h-48 flex-1 overflow-y-auto rounded-lg border border-[var(--color-border)]">
              {hits.length === 0 ? (
                <p className="p-3 text-xs text-[var(--color-muted-foreground)]">Arama sonuçları</p>
              ) : (
                <ul className="divide-y divide-[var(--color-border)]/60 text-xs">
                  {hits.map((h) => {
                    const on = selected.has(h.name);
                    return (
                      <li key={h.name}>
                        <button
                          type="button"
                          onClick={() => togglePkg(h.name)}
                          className={cn(
                            "flex w-full gap-2 px-3 py-1.5 text-left hover:bg-[var(--color-accent)]",
                            on && "bg-emerald-500/10",
                          )}
                        >
                          <span className="font-mono text-[var(--theme-link)]">{h.name}</span>
                          <span className="text-[var(--color-muted-foreground)]">{h.summary}</span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
            {selected.size > 0 ? (
              <p className="text-[10px] text-[var(--color-muted-foreground)]">
                Seçili: {Array.from(selected).join(", ")}
              </p>
            ) : null}
          </>
        ) : (
          <div className="space-y-2">
            <p className="text-[11px] text-[var(--color-muted-foreground)]">
              Keyword <span className="font-mono text-emerald-200">{mode}</span> — local NFS + tanımlı
              post komutlar çalışacak. İsteğe bağlı paket:
            </p>
            <Input
              className="h-8 font-mono"
              placeholder="opsiyonel: docker-ce docker-ce-cli … (boş=yalnız post_commands)"
              value={Array.from(selected).join(" ")}
              onChange={(e) =>
                setSelected(
                  new Set(
                    e.target.value
                      .split(/\s+/)
                      .map((x) => x.trim())
                      .filter(Boolean),
                  ),
                )
              }
            />
            <pre className="max-h-32 overflow-auto rounded border border-[var(--color-border)] p-2 font-mono text-[9px] text-[var(--color-muted-foreground)]">
              {activeRepo.post_commands.slice(0, 1200)}
            </pre>
          </div>
        )}

        {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}

        <Button type="submit" size="sm" disabled={busy || !previewReady}>
          {busy ? "…" : t("preview")}
        </Button>
      </form>
    </div>
  );
}
