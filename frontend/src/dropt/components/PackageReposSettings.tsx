import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  createPkgLocalRepo,
  createPkgSubscription,
  deletePkgLocalRepo,
  deletePkgSubscription,
  getPackageReposOverview,
  OsOption,
  PkgLocalRepoRow,
  PkgSubscriptionRow,
  updatePkgLocalRepo,
} from "@dropt/api";
import { Button } from "@dropt/components/ui/button";
import { Input } from "@dropt/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@dropt/components/ui/select";
import { getToken } from "@dropt/session";

type SourceType = "nfs" | "portal_files" | "subscription";

function sourceLabel(st: string | undefined): string {
  if (st === "portal_files") return "portal";
  if (st === "subscription") return "subscription";
  return "nfs";
}

export function PackageReposSettings() {
  const token = getToken()!;
  const [osOptions, setOsOptions] = useState<OsOption[]>([]);
  const [subs, setSubs] = useState<PkgSubscriptionRow[]>([]);
  const [repos, setRepos] = useState<PkgLocalRepoRow[]>([]);
  const [portalRoot, setPortalRoot] = useState("/var/lib/dropt/rpms");
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [subOs, setSubOs] = useState("");
  const [org, setOrg] = useState("");
  const [actKey, setActKey] = useState("");

  const [editingId, setEditingId] = useState<number | null>(null);
  const [kw, setKw] = useState("");
  const [repoOs, setRepoOs] = useState("");
  const [sourceType, setSourceType] = useState<SourceType>("nfs");
  const [nfs, setNfs] = useState("");
  const [mount, setMount] = useState("");
  const [portalPath, setPortalPath] = useState("");
  const [fileGlob, setFileGlob] = useState("*.rpm");
  const [needsFs, setNeedsFs] = useState(false);
  const [postCmd, setPostCmd] = useState("");

  const resetRepoForm = useCallback((fallbackOs = "") => {
    setEditingId(null);
    setKw("");
    setRepoOs(fallbackOs);
    setSourceType("nfs");
    setNfs("");
    setMount("");
    setPortalPath("");
    setFileGlob("*.rpm");
    setNeedsFs(false);
    setPostCmd("");
  }, []);

  const reload = useCallback(async () => {
    const o = await getPackageReposOverview(token);
    setOsOptions(o.os_options);
    setSubs(o.subscriptions);
    setRepos(o.local_repos);
    if ((o as { portal_rpm_root?: string }).portal_rpm_root) {
      setPortalRoot((o as { portal_rpm_root: string }).portal_rpm_root);
    }
    setSubOs((prev) => prev || o.os_options[0]?.value || "");
    setRepoOs((prev) => prev || o.os_options[0]?.value || "");
  }, [token]);

  useEffect(() => {
    void reload().catch((e) => setError(e instanceof Error ? e.message : "Yüklenemedi"));
  }, [reload]);

  function startEdit(r: PkgLocalRepoRow) {
    setEditingId(r.id);
    setKw(r.keyword);
    setRepoOs(r.os_value);
    const st = (r.source_type || "nfs") as SourceType;
    setSourceType(st === "portal_files" || st === "subscription" ? st : "nfs");
    setNfs(r.nfs_path || "");
    setMount(r.mount_point || "");
    setPortalPath(r.portal_path || "");
    setFileGlob(r.file_glob || "*.rpm");
    setNeedsFs(Boolean(r.needs_data_mount));
    setPostCmd(r.post_commands || "");
    setMsg(null);
    setError(null);
  }

  async function onAddSub(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      await createPkgSubscription(token, {
        os_value: subOs,
        org: org.trim(),
        activation_key: actKey.trim() || undefined,
        label: subOs,
      });
      setActKey("");
      setMsg("Subscription eklendi (key boşsa operasyonlarda wipe/register atlanır)");
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  async function onSaveRepo(e: FormEvent) {
    e.preventDefault();
    if (!kw.trim()) {
      setError("Keyword zorunlu");
      return;
    }
    setBusy(true);
    setError(null);
    setMsg(null);
    const body = {
      keyword: kw.trim(),
      label: kw.trim(),
      os_value: repoOs,
      source_type: sourceType,
      nfs_path: sourceType === "nfs" ? nfs.trim() : "",
      mount_point: sourceType === "nfs" ? mount.trim() || `/mnt/dropt-repo-${kw.trim()}` : "",
      portal_path: sourceType === "portal_files" ? portalPath.trim() : "",
      file_glob: sourceType === "portal_files" ? fileGlob.trim() || "*.rpm" : "*.rpm",
      needs_data_mount: sourceType === "nfs" || sourceType === "subscription" ? needsFs : false,
      post_commands: postCmd,
      repo_id: `dropt-${kw.trim()}`,
    };
    try {
      if (editingId != null) {
        await updatePkgLocalRepo(token, editingId, body);
        setMsg(`Keyword reçetesi güncellendi: ${kw} @ ${repoOs}`);
      } else {
        await createPkgLocalRepo(token, body);
        setMsg(`Keyword reçetesi eklendi: ${kw} @ ${repoOs} (${sourceType})`);
      }
      resetRepoForm(repoOs || osOptions[0]?.value || "");
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-5">
      <div>
        <h3 className="text-sm font-medium">Paket reçeteleri (keyword · kaynak · OS)</h3>
        <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">
          Keyword Package ekranında chip olur. Kaynak: NFS mount, Portal RPM veya{" "}
          <strong>Subscription (Satellite)</strong> — her üçünde de post komutlar / data dizini aynı
          reçetede kalır. Portal kök: <span className="font-mono">{portalRoot}/…</span>
        </p>
      </div>

      <section className="space-y-2">
        <h4 className="text-xs font-medium text-[var(--color-muted-foreground)]">
          Subscription (OS activation key)
        </h4>
        <form onSubmit={onAddSub} className="grid gap-2 sm:grid-cols-4">
          <Select value={subOs || undefined} onValueChange={setSubOs}>
            <SelectTrigger className="h-8">
              <SelectValue placeholder="OS" />
            </SelectTrigger>
            <SelectContent>
              {osOptions.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                  {o.count ? ` (${o.count})` : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input className="h-8 font-mono" placeholder="org" value={org} onChange={(e) => setOrg(e.target.value)} />
          <Input
            className="h-8 font-mono"
            type="password"
            placeholder="activation key (ops.)"
            value={actKey}
            onChange={(e) => setActKey(e.target.value)}
          />
          <Button type="submit" size="sm" className="h-8" disabled={busy || !subOs}>
            Ekle
          </Button>
        </form>
        <ul className="space-y-1 font-mono text-[11px] text-[var(--color-muted-foreground)]">
          {subs.map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-2">
              <span>
                {s.label} · {s.os_value} · org={s.org || "—"} · key=
                {s.activation_key_set ? "set" : "yok"}
              </span>
              <button
                type="button"
                className="text-red-300/90 hover:underline"
                onClick={() =>
                  void deletePkgSubscription(token, s.id)
                    .then(reload)
                    .catch((e) => setError(e instanceof Error ? e.message : "Silinemedi"))
                }
              >
                sil
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-2 border-t border-[var(--color-border)] pt-3">
        <h4 className="text-xs font-medium text-[var(--color-muted-foreground)]">
          Keyword reçetesi {editingId != null ? `(düzenleniyor #${editingId})` : ""}
        </h4>
        <form onSubmit={onSaveRepo} className="grid gap-2 sm:grid-cols-2">
          <Input
            className="h-8 font-mono"
            placeholder="keyword (örn. docker / snowlinux)"
            value={kw}
            onChange={(e) => setKw(e.target.value)}
            required
          />
          <Select value={repoOs || undefined} onValueChange={setRepoOs}>
            <SelectTrigger className="h-8">
              <SelectValue placeholder="OS" />
            </SelectTrigger>
            <SelectContent>
              {osOptions.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={sourceType} onValueChange={(v) => setSourceType(v as SourceType)}>
            <SelectTrigger className="h-8 sm:col-span-2">
              <SelectValue placeholder="Kaynak tipi" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="nfs">NFS local repo</SelectItem>
              <SelectItem value="portal_files">Portal dosya (RPM → /tmp + localinstall)</SelectItem>
              <SelectItem value="subscription">Subscription (Satellite / dnf + post)</SelectItem>
            </SelectContent>
          </Select>

          {sourceType === "nfs" ? (
            <>
              <Input
                className="h-8 font-mono sm:col-span-2"
                placeholder="nfs path (host:/export/...)"
                value={nfs}
                onChange={(e) => setNfs(e.target.value)}
                required
              />
              <Input
                className="h-8 font-mono"
                placeholder="mount point (örn. /mnt/dropt-repo-xxx)"
                value={mount}
                onChange={(e) => setMount(e.target.value)}
              />
              <label className="flex items-center gap-2 text-[11px] text-[var(--color-muted-foreground)]">
                <input type="checkbox" checked={needsFs} onChange={(e) => setNeedsFs(e.target.checked)} />
                Data mount (FS) seçimi gerekli
              </label>
            </>
          ) : null}

          {sourceType === "portal_files" ? (
            <>
              <Input
                className="h-8 font-mono sm:col-span-2"
                placeholder={`${portalRoot}/snowlinux/el8`}
                value={portalPath}
                onChange={(e) => setPortalPath(e.target.value)}
                required
              />
              <Input
                className="h-8 font-mono sm:col-span-2"
                placeholder="file glob (örn. snowlinux*.rpm)"
                value={fileGlob}
                onChange={(e) => setFileGlob(e.target.value)}
              />
            </>
          ) : null}

          {sourceType === "subscription" ? (
            <div className="space-y-2 sm:col-span-2">
              <p className="text-[11px] text-[var(--color-muted-foreground)]">
                Paketler Satellite/dnf üzerinden kurulur (üstteki OS subscription key kullanılır). Aşağıdaki
                post komutlar ve data dizini NFS reçetesiyle aynı şekilde çalışır (
                <span className="font-mono">{"{{docker_pkgs}}"}</span>,{" "}
                <span className="font-mono">{"{{docker_dir}}"}</span>, …).
              </p>
              <label className="flex items-center gap-2 text-[11px] text-[var(--color-muted-foreground)]">
                <input type="checkbox" checked={needsFs} onChange={(e) => setNeedsFs(e.target.checked)} />
                Data mount (FS) seçimi gerekli
              </label>
            </div>
          ) : null}

          <textarea
            className="min-h-[8rem] rounded-md border border-[var(--color-border)] bg-transparent p-2 font-mono text-[10px] sm:col-span-2"
            value={postCmd}
            onChange={(e) => setPostCmd(e.target.value)}
            placeholder="Kurulum sonrası komutlar (opsiyonel) — {{data_mount}} {{docker_dir}} {{docker_pkgs}} …"
          />
          <div className="flex gap-2 sm:col-span-2">
            <Button type="submit" size="sm" className="h-8" disabled={busy || !repoOs || !kw.trim()}>
              {editingId != null ? "Güncelle" : "Reçete ekle"}
            </Button>
            {editingId != null ? (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                className="h-8"
                disabled={busy}
                onClick={() => resetRepoForm(osOptions[0]?.value || "")}
              >
                İptal
              </Button>
            ) : null}
          </div>
        </form>
        <ul className="space-y-1 font-mono text-[11px] text-[var(--color-muted-foreground)]">
          {repos.map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-2">
              <span>
                [{r.keyword}] {r.os_value} · {sourceLabel(r.source_type)} ·{" "}
                {r.source_type === "portal_files"
                  ? `${r.portal_path}/${r.file_glob || "*.rpm"}`
                  : r.source_type === "subscription"
                    ? "Satellite/dnf + post"
                    : r.nfs_path}
                {r.needs_data_mount ? " · FS" : ""}
              </span>
              <span className="flex shrink-0 gap-2">
                <button type="button" className="text-[var(--theme-link)] hover:underline" onClick={() => startEdit(r)}>
                  düzenle
                </button>
                <button
                  type="button"
                  className="text-red-300/90 hover:underline"
                  onClick={() =>
                    void deletePkgLocalRepo(token, r.id)
                      .then(() => {
                        if (editingId === r.id) resetRepoForm(osOptions[0]?.value || "");
                        return reload();
                      })
                      .catch((e) => setError(e instanceof Error ? e.message : "Silinemedi"))
                  }
                >
                  sil
                </button>
              </span>
            </li>
          ))}
        </ul>
      </section>

      {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
      {msg ? <p className="text-sm text-emerald-300">{msg}</p> : null}
    </div>
  );
}
