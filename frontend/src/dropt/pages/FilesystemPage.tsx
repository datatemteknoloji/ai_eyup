import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  createJob,
  FilesystemInventory,
  FilesystemRow,
  FsFreeDisk,
  getFilesystemInventory,
  getServer,
  previewJob,
  VolumeGroup,
} from "@dropt/api";
import { Badge } from "@dropt/components/ui/badge";
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
import { cn } from "@dropt/lib/utils";
import { ArrowLeft, FolderPlus, Maximize2, Folders } from "lucide-react";

/** Partition/LVM overhead — backend DISK_USABLE_RESERVE_BYTES ile aynı */
const DISK_USABLE_RESERVE = 16 * 1024 * 1024;
const GIB = 1024 ** 3;
const MIN_VG_FREE = 4 * 1024 * 1024;
/** Create / extend / organize — 0.5 → ~512 MiB */
const MIN_SIZE_GB = 0.1;

type OpMode = "create" | "extend" | "organize";
type FsGate = "choice" | OpMode;

function normalizeFsMode(raw: string): OpMode | null {
  const v = raw.toLowerCase();
  if (v === "extend" || v === "create" || v === "organize") return v;
  return null;
}

function parseSizeGb(raw: string): number {
  const n = Number(String(raw).trim().replace(",", "."));
  return Number.isFinite(n) ? n : NaN;
}

type OrgSlice = {
  id: string;
  mount: string;
  sizeGb: string;
  /** Kaynak LV bütçesinden kalanın tamamı (satır başına en fazla bir) */
  useAllFree?: boolean;
  fstype: string;
  owner: string;
};

function freeDiskKey(d: FsFreeDisk) {
  return d.wwid || d.device || d.alias;
}

function diskUsableBytes(d: FsFreeDisk) {
  return Math.max(0, (d.size_bytes || 0) - DISK_USABLE_RESERVE);
}

function diskUsableGb(d: FsFreeDisk) {
  // Ondalıklı GiB — 900MiB disk usable ~0.86G (floor → 0 olmasın)
  return Math.round((diskUsableBytes(d) / GIB) * 1000) / 1000;
}

function approxGbFromHuman(size?: string): number {
  if (!size) return 0;
  const m = String(size).trim().match(/^([\d.]+)\s*([KMGTPE]?i?B?)?$/i);
  if (!m) return 0;
  const n = Number(m[1]);
  if (!Number.isFinite(n)) return 0;
  const u = (m[2] || "G").toUpperCase().charAt(0);
  const mult: Record<string, number> = {
    K: 1 / (1024 * 1024),
    M: 1 / 1024,
    G: 1,
    T: 1024,
    P: 1024 * 1024,
  };
  // 448M → ~0.438 GB (floor etme — küçük LV’lerde organize bütçesi 0 olmasın)
  const gb = n * (mult[u] ?? 1);
  return Math.round(gb * 1000) / 1000;
}

function formatGb(n: number): string {
  return n.toLocaleString("tr-TR", { maximumFractionDigits: 3 });
}

function lvNamePreview(mount: string): string {
  const parts = mount
    .replace(/^\/+/, "")
    .split("/")
    .filter(Boolean);
  let stem = (parts.join("_") || "data").replace(/[^A-Za-z0-9_-]/g, "_");
  if (!stem || !/^[A-Za-z]/.test(stem)) stem = `x${stem || "data"}`;
  stem = stem.slice(0, 30).replace(/_+$/, "") || "data";
  return `${stem}lv`.slice(0, 32);
}

/** Create bağlamı: non-root LVM FS */
function isCreateContextFs(f: FilesystemRow): boolean {
  return Boolean(f.vg_name && f.lv_name && !f.on_root_vg && !f.blacklisted);
}

/** Organize: non-root + extendable flags (backend root allowlist'i dışla) */
function isOrganizeFs(f: FilesystemRow): boolean {
  return Boolean(f.extendable && !f.on_root_vg);
}

export function FilesystemPage() {
  const token = getToken()!;
  const afterPreview = useAfterPreview();
  const opsCtx = useOpsWizard();
  const embedded = Boolean(opsCtx?.embedded);
  const draftJob = opsCtx?.draftJob;
  const t = useT();
  const { serverId } = useServerQuery();
  const [params, setParams] = useSearchParams();
  const [hostname, setHostname] = useState("");
  const [inv, setInv] = useState<FilesystemInventory | null>(null);
  const [loading, setLoading] = useState(false);
  const [embeddedGate, setEmbeddedGate] = useState<FsGate>("choice");
  const [mode, setMode] = useState<OpMode>("extend");
  /** Tabloda seçili mevcut FS (extend/organize hedefi) */
  const [selectedMount, setSelectedMount] = useState("");
  /** Create: hedef VG (root hariç) */
  const [vgName, setVgName] = useState("");
  /** Create: yeni FS mount yolu */
  const [createMount, setCreateMount] = useState("");
  const [addGb, setAddGb] = useState("");
  const [sizeGb, setSizeGb] = useState("");
  const [useAllFree, setUseAllFree] = useState(false);
  const [fstype, setFstype] = useState("xfs");
  const autoLvName = useMemo(
    () => (createMount.trim().startsWith("/") ? lvNamePreview(createMount) : ""),
    [createMount],
  );
  const [owner, setOwner] = useState("");
  const [talepId, setTalepId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedDiskKeys, setSelectedDiskKeys] = useState<Set<string>>(() => new Set());
  const [orgSlices, setOrgSlices] = useState<OrgSlice[]>(() => [
    { id: "1", mount: "", sizeGb: "", useAllFree: false, fstype: "xfs", owner: "" },
  ]);

  useEffect(() => {
    if (!serverId) {
      setHostname("");
      setInv(null);
      return;
    }
    let cancelled = false;
    void getServer(token, Number(serverId))
      .then((s) => {
        if (!cancelled) setHostname(s.hostname || s.ip || `#${serverId}`);
      })
      .catch(() => {
        if (!cancelled) setHostname(`#${serverId}`);
      });
    return () => {
      cancelled = true;
    };
  }, [token, serverId]);

  const loadInv = useCallback(
    async (refresh = false) => {
      if (!serverId) {
        setInv(null);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const data = await getFilesystemInventory(token, Number(serverId), { refresh });
        setInv(data);
        setSelectedDiskKeys(new Set());
      } catch (err) {
        setInv(null);
        setError(err instanceof Error ? err.message : "Envanter okunamadı");
      } finally {
        setLoading(false);
      }
    },
    [token, serverId],
  );

  useEffect(() => {
    void loadInv(false);
  }, [loadInv]);

  useEffect(() => {
    setSelectedDiskKeys(new Set());
    setUseAllFree(false);
  }, [mode, selectedMount, vgName]);

  const createVgs = useMemo(
    () => (inv?.volume_groups || []).filter((v) => v.selectable !== false && !v.is_root_vg),
    [inv],
  );

  const listedFs: FilesystemRow[] = useMemo(() => {
    const all = inv?.filesystems || [];
    if (mode === "extend") return all.filter((f) => f.extendable);
    if (mode === "organize") return all.filter(isOrganizeFs);
    // Create: seçili VG altındaki non-root FS’ler (bağlam)
    if (!vgName) return all.filter(isCreateContextFs);
    return all.filter((f) => isCreateContextFs(f) && f.vg_name === vgName);
  }, [inv, mode, vgName]);

  useEffect(() => {
    if (mode === "create") {
      if (vgName && createVgs.some((v) => v.name === vgName)) return;
      setVgName(createVgs[0]?.name || "");
      return;
    }
    if (selectedMount && listedFs.some((f) => f.mount === selectedMount)) return;
    setSelectedMount(listedFs[0]?.mount || "");
  }, [listedFs, selectedMount, mode, vgName, createVgs]);

  // Draft job'dan formu doldur (Seçimleri düzenle)
  useEffect(() => {
    if (!draftJob || draftJob.module !== "filesystem" || !inv) return;
    const p = (draftJob.payload || {}) as Record<string, unknown>;
    const action = String(draftJob.action || p.action || "");
    if (action === "organize" || action === "extend" || action === "create") {
      if (embedded) setEmbeddedGate(action);
      else {
        const next = new URLSearchParams(params);
        next.set("mode", action);
        setParams(next, { replace: true });
      }
    }
    if (action === "organize") {
      setMode("organize");
      setSelectedMount(String(p.mount || ""));
      const slices = Array.isArray(p.slices) ? p.slices : [];
      setOrgSlices(
        slices.length
          ? slices.map((s, i) => {
              const row = (s || {}) as Record<string, unknown>;
              const useAll = Boolean(row.use_all_free);
              return {
                id: `d${i}-${String(row.mount || i)}`,
                mount: String(row.mount || ""),
                sizeGb: useAll ? "" : String(row.size_gb ?? ""),
                useAllFree: useAll,
                fstype: String(row.fstype || "xfs"),
                owner: String(row.owner || ""),
              };
            })
          : [{ id: "1", mount: "", sizeGb: "", useAllFree: false, fstype: "xfs", owner: "" }],
      );
      setTalepId(draftJob.talep_id || "");
      return;
    }
    if (action === "extend") {
      setMode("extend");
      setSelectedMount(String(p.mount || ""));
      setUseAllFree(Boolean(p.use_all_free));
      setAddGb(p.use_all_free ? "" : String(p.add_gb ?? ""));
      setTalepId(draftJob.talep_id || "");
      return;
    }
    if (action === "create") {
      setMode("create");
      setVgName(String(p.vg_name || ""));
      setCreateMount(String(p.mount || ""));
      setFstype(String(p.fstype || "xfs"));
      setOwner(String(p.owner || ""));
      setUseAllFree(Boolean(p.use_all_free));
      setSizeGb(p.use_all_free ? "" : String(p.size_gb ?? ""));
      setTalepId(draftJob.talep_id || "");
    }
  }, [draftJob?.id, inv]);

  useEffect(() => {
    if (!embedded) return;
    setEmbeddedGate("choice");
  }, [embedded, opsCtx?.serverId]);

  const urlMode = normalizeFsMode(params.get("mode") || params.get("tab") || "");
  const gate: FsGate = embedded ? embeddedGate : urlMode || "choice";

  useEffect(() => {
    if (gate !== "choice") setMode(gate);
  }, [gate]);

  function goMode(next: OpMode) {
    setMode(next);
    if (next === "create") {
      setCreateMount("");
      setUseAllFree(false);
    }
    if (next === "organize") {
      setUseAllFree(false);
      setOrgSlices([
        { id: String(Date.now()), mount: "", sizeGb: "", useAllFree: false, fstype: "xfs", owner: "" },
      ]);
    }
    if (embedded) {
      setEmbeddedGate(next);
      return;
    }
    const nextParams = new URLSearchParams(params);
    nextParams.set("mode", next);
    setParams(nextParams, { replace: true });
  }

  function goChoice() {
    if (embedded) {
      setEmbeddedGate("choice");
      return;
    }
    const nextParams = new URLSearchParams(params);
    nextParams.delete("mode");
    nextParams.delete("tab");
    setParams(nextParams, { replace: true });
  }

  const selectedFs = useMemo(
    () => listedFs.find((f) => f.mount === selectedMount),
    [listedFs, selectedMount],
  );

  const effectiveVgName =
    mode === "create" ? vgName : selectedFs?.vg_name || "";

  const selectedVg: VolumeGroup | undefined = useMemo(
    () => inv?.volume_groups.find((v) => v.name === effectiveVgName),
    [inv, effectiveVgName],
  );

  const sourceFs = selectedFs;
  const orgBudgetGb = approxGbFromHuman(sourceFs?.size);
  const orgFixedSum = useMemo(
    () =>
      orgSlices.reduce((s, r) => {
        if (r.useAllFree) return s;
        const n = parseSizeGb(r.sizeGb);
        return s + (n >= MIN_SIZE_GB ? n : 0);
      }, 0),
    [orgSlices],
  );
  const orgHasAllFree = orgSlices.some((r) => r.useAllFree);
  const orgAllFreeGb = Math.max(0, orgBudgetGb - orgFixedSum);
  const orgUsedSum = orgHasAllFree ? orgFixedSum + orgAllFreeGb : orgFixedSum;
  const orgRemainGb = Math.max(0, orgBudgetGb - orgUsedSum);

  const freeGb =
    mode === "create"
      ? (selectedVg?.free_gb ?? 0)
      : (selectedFs?.vg_free_gb ?? selectedVg?.free_gb ?? 0);
  const freeBytes = freeGb * GIB;
  const needGb =
    mode === "extend"
      ? parseSizeGb(addGb) || 0
      : mode === "create"
        ? parseSizeGb(sizeGb) || 0
        : 0;

  const selectedDisks = useMemo(() => {
    const all = inv?.free_disks || [];
    return all.filter((d) => selectedDiskKeys.has(freeDiskKey(d)));
  }, [inv, selectedDiskKeys]);

  const selectedDiskUsableBytes = useMemo(
    () => selectedDisks.reduce((sum, d) => sum + diskUsableBytes(d), 0),
    [selectedDisks],
  );
  const selectedDiskGb = useMemo(
    () => selectedDisks.reduce((sum, d) => sum + diskUsableGb(d), 0),
    [selectedDisks],
  );
  const estFreeBytes = freeBytes + selectedDiskUsableBytes;

  const vgLockedForDisks = Boolean(selectedFs?.on_root_vg && mode !== "extend");
  const vgOperable = Boolean(
    effectiveVgName && (mode === "create" ? selectedVg && !selectedVg.is_root_vg : selectedFs && !vgLockedForDisks),
  );

  const vgSpaceOk = Boolean(
    mode !== "organize" &&
      vgOperable &&
      !useAllFree &&
      needGb >= MIN_SIZE_GB &&
      freeBytes >= needGb * GIB,
  );
  const needsDisks = Boolean(
    mode !== "organize" &&
      vgOperable &&
      (useAllFree ? freeBytes < MIN_VG_FREE : needGb >= MIN_SIZE_GB && !vgSpaceOk),
  );
  const disksSelectable = Boolean(
    mode !== "organize" && vgOperable && (needsDisks || useAllFree),
  );
  const spaceOk = Boolean(
    mode === "organize"
      ? Boolean(
          selectedMount &&
            orgBudgetGb >= MIN_SIZE_GB &&
            orgUsedSum >= MIN_SIZE_GB &&
            orgUsedSum <= orgBudgetGb + 1e-6,
        )
      : vgOperable &&
          (useAllFree
            ? estFreeBytes >= MIN_VG_FREE
            : needGb >= MIN_SIZE_GB && estFreeBytes >= needGb * GIB),
  );
  const showDiskPanel = Boolean(
    mode !== "organize" && vgOperable && (needsDisks || (useAllFree && selectedDisks.length > 0)),
  );

  function toggleDisk(d: FsFreeDisk) {
    if (!disksSelectable) return;
    const key = freeDiskKey(d);
    setSelectedDiskKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const previewReady = useMemo(() => {
    if (!talepId.trim() || !serverId || !effectiveVgName) return false;
    if (mode === "organize") {
      if (!selectedMount || !isOrganizeFs(selectedFs || ({} as FilesystemRow))) return false;
      if (orgUsedSum < MIN_SIZE_GB || (orgBudgetGb > 0 && orgUsedSum > orgBudgetGb + 1e-6))
        return false;
      if (orgHasAllFree && orgAllFreeGb < 0.05) return false;
      const mounts = new Set<string>();
      let allFreeRows = 0;
      for (const s of orgSlices) {
        if (!s.mount.trim().startsWith("/")) return false;
        if (s.useAllFree) {
          allFreeRows += 1;
          if (allFreeRows > 1) return false;
        } else if (!(parseSizeGb(s.sizeGb) >= MIN_SIZE_GB)) {
          return false;
        }
        if (mounts.has(s.mount.trim())) return false;
        mounts.add(s.mount.trim());
      }
      return orgSlices.length >= 1;
    }
    if (!spaceOk) return false;
    if (needsDisks && selectedDisks.length < 1) return false;
    if (mode === "extend") {
      return Boolean(selectedMount && selectedFs?.extendable);
    }
    return Boolean(autoLvName && createMount.trim().startsWith("/") && fstype);
  }, [
    talepId,
    serverId,
    effectiveVgName,
    selectedMount,
    spaceOk,
    needsDisks,
    selectedDisks.length,
    mode,
    selectedFs,
    autoLvName,
    createMount,
    fstype,
    orgSlices,
    orgUsedSum,
    orgBudgetGb,
    orgHasAllFree,
    orgAllFreeGb,
  ]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!previewReady) return;
    setBusy(true);
    setError(null);
    try {
      if (!talepId.trim()) throw new Error("Talep ID zorunlu");
      if (!serverId) throw new Error("Sunucu bağlamı yok — Server Console’dan açın");
      const add_disks = needsDisks
        ? selectedDisks.map((d) => ({
            alias: d.alias,
            wwid: d.wwid,
            device: d.device,
            size_bytes: d.size_bytes,
            size: d.size,
          }))
        : [];
      if (mode === "extend") {
        const job = await createJob(token, {
          module: "filesystem",
          action: "extend",
          talep_id: talepId.trim(),
          server_ids: [Number(serverId)],
          payload: {
            mount: selectedMount,
            vg_name: effectiveVgName,
            add_disks,
            use_all_free: useAllFree,
            ...(useAllFree ? {} : { add_gb: parseSizeGb(addGb) }),
          },
        });
        afterPreview(await previewJob(token, job.id));
      } else if (mode === "organize") {
        const job = await createJob(token, {
          module: "filesystem",
          action: "organize",
          talep_id: talepId.trim(),
          server_ids: [Number(serverId)],
          payload: {
            mount: selectedMount,
            vg_name: effectiveVgName,
            slices: orgSlices.map((s) =>
              s.useAllFree
                ? {
                    mount: s.mount.trim(),
                    use_all_free: true,
                    fstype: s.fstype || "xfs",
                    owner: s.owner.trim() || undefined,
                  }
                : {
                    mount: s.mount.trim(),
                    size_gb: parseSizeGb(s.sizeGb),
                    use_all_free: false,
                    fstype: s.fstype || "xfs",
                    owner: s.owner.trim() || undefined,
                  },
            ),
          },
        });
        afterPreview(await previewJob(token, job.id));
      } else {
        const job = await createJob(token, {
          module: "filesystem",
          action: "create",
          talep_id: talepId.trim(),
          server_ids: [Number(serverId)],
          payload: {
            vg_name: effectiveVgName,
            lv_name: autoLvName,
            mount: createMount.trim(),
            fstype,
            owner: owner.trim() || undefined,
            add_disks,
            use_all_free: useAllFree,
            ...(useAllFree ? {} : { size_gb: parseSizeGb(sizeGb) }),
          },
        });
        afterPreview(await previewJob(token, job.id));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  function fsStatusLabel(r: FilesystemRow): { text: string; kind: "ok" | "warn" | "mute" } {
    if (r.on_root_vg) {
      if (mode === "extend" && r.extendable) return { text: "root · extend ok", kind: "ok" };
      return { text: "root VG", kind: "warn" };
    }
    if (r.blacklisted) return { text: "kilit", kind: "warn" };
    if (mode === "extend" && r.extendable) return { text: "extend", kind: "ok" };
    if (mode === "organize" && isOrganizeFs(r)) return { text: "organize", kind: "ok" };
    if (mode === "create" && isCreateContextFs(r)) return { text: "VG bağlam", kind: "ok" };
    return { text: "—", kind: "mute" };
  }

  if (gate === "choice") {
    const choices: {
      mode: OpMode;
      title: string;
      hint: string;
      icon: typeof Maximize2;
      tone: string;
    }[] = [
      {
        mode: "extend",
        title: t("fs_extend"),
        hint: t("fs_extend_hint"),
        icon: Maximize2,
        tone: "bg-[var(--info-bg)] text-[var(--info)]",
      },
      {
        mode: "create",
        title: t("fs_create"),
        hint: t("fs_create_hint"),
        icon: FolderPlus,
        tone: "bg-[var(--accent-subtle)] text-[var(--accent)]",
      },
      {
        mode: "organize",
        title: t("fs_organize"),
        hint: t("fs_organize_hint"),
        icon: Folders,
        tone: "bg-[var(--success-bg)] text-[var(--success)]",
      },
    ];
    return (
      <div className={cn(embedded ? "px-4 py-4 md:px-5" : "px-6 py-5")}>
        {!embedded ? (
          <h2 className="text-lg font-semibold tracking-tight">{t("wizard_fs")}</h2>
        ) : null}
        <p
          className={cn(
            "text-sm text-[var(--color-muted-foreground)]",
            !embedded ? "mt-1" : "mb-1",
          )}
        >
          {t("fs_mgmt_sub")}
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          {choices.map((c) => {
            const Icon = c.icon;
            return (
              <button
                key={c.mode}
                type="button"
                onClick={() => goMode(c.mode)}
                className="group flex flex-col rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-4 text-left transition hover:border-[var(--accent)]/45 hover:bg-[var(--accent-subtle)]"
              >
                <span
                  className={cn(
                    "mb-3 grid h-10 w-10 place-items-center rounded-lg transition group-hover:scale-105",
                    c.tone,
                  )}
                >
                  <Icon className="h-5 w-5" />
                </span>
                <p className="text-sm font-semibold text-[var(--color-foreground)]">{c.title}</p>
                <p className="mt-1.5 flex-1 text-xs leading-relaxed text-[var(--color-muted-foreground)]">
                  {c.hint}
                </p>
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  const modeTitle =
    mode === "extend" ? t("fs_extend") : mode === "create" ? t("fs_create") : t("fs_organize");

  return (
    <div className={cn("flex min-h-0 flex-col", embedded ? "px-4 py-3 md:px-5 md:py-4" : "px-6 py-5")}>
      <div className="mb-3 shrink-0">
        <button
          type="button"
          onClick={goChoice}
          className="mb-2 inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--bg-elevated,var(--color-secondary))] px-2.5 py-1.5 text-xs font-medium text-[var(--color-foreground)] transition hover:border-[var(--accent)]/40"
        >
          <ArrowLeft className="h-3.5 w-3.5 opacity-70" />
          İşlem seçimine dön
        </button>
        <h2 className="text-lg font-semibold tracking-tight">{modeTitle}</h2>
        <p className="mt-0.5 text-xs text-[var(--color-muted-foreground)]">
          {hostname ? `${hostname}` : ""}
          {inv?.root_vg ? ` · root VG: ${inv.root_vg}` : ""}
          {inv?.cached ? " · cache" : ""}
        </p>
      </div>

      {!serverId ? (
        <div className="rounded-2xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm">
          Sunucu seçilmedi. Bu işlem tek sunucuda çalışır — Server Console’dan FileSystem Management’i açın.
        </div>
      ) : null}

      <form
        onSubmit={onSubmit}
        className="relative flex min-h-0 flex-1 flex-col gap-3 overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] p-5 shadow-sm"
      >
        {loading ? (
          <div className="absolute inset-0 z-20 flex items-center justify-center rounded-2xl bg-[var(--theme-overlay)] backdrop-blur-[1px]">
            <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-card)] px-4 py-2 text-sm text-[var(--color-muted-foreground)]">
              Sunucu envanteri yükleniyor…
            </div>
          </div>
        ) : null}

        <div className="grid shrink-0 gap-2 sm:grid-cols-[1fr_auto_12rem] sm:items-center">
          <Input
            className="h-8"
            placeholder={t("talep_id")}
            value={talepId}
            onChange={(e) => setTalepId(e.target.value)}
            required
            disabled={loading || !serverId}
          />
          <p
            className="truncate font-mono text-[11px] text-[var(--color-muted-foreground)]"
            title={hostname || undefined}
          >
            {hostname || (serverId ? `#${serverId}` : "—")}
          </p>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            className="h-8"
            disabled={loading || !serverId}
            onClick={() => void loadInv(true)}
          >
            {loading ? "…" : "Yenile"}
          </Button>
        </div>

        {/* FS tablosu (df) */}
        <div className="min-h-0 shrink-0 overflow-hidden rounded-lg border border-[var(--color-border)]">
          <div className="flex items-center justify-between border-b border-[var(--color-border)] px-3 py-1.5">
            <p className="text-xs font-medium text-[var(--color-muted-foreground)]">
              {mode === "create" ? "Volume group / Filesystems" : "Filesystems"}
              {mode === "extend"
                ? " · root VG: yalnızca /home /var /tmp /var/tmp"
                : mode === "create"
                  ? " · root VG hariç VG seçin"
                  : " · root VG hariç"}
            </p>
            <span className="text-[10px] text-[var(--color-muted-foreground)]">
              {listedFs.length} satır
            </span>
          </div>
          <div className="max-h-64 overflow-y-auto">
            <table className="w-full text-[11px]">
              <thead className="sticky top-0 bg-[var(--color-card)] text-[var(--color-muted-foreground)]">
                <tr>
                  <th className="px-2 py-1.5 text-left font-medium">Mounted on</th>
                  <th className="px-2 py-1.5 text-left font-medium">Size</th>
                  <th className="px-2 py-1.5 text-left font-medium">Used</th>
                  <th className="px-2 py-1.5 text-left font-medium">Avail</th>
                  <th className="px-2 py-1.5 text-left font-medium">Use%</th>
                  <th className="px-2 py-1.5 text-left font-medium">VG</th>
                  <th className="px-2 py-1.5 text-left font-medium">LV</th>
                  <th className="px-2 py-1.5 text-left font-medium">VG boş</th>
                  <th className="px-2 py-1.5 text-left font-medium">Durum</th>
                </tr>
              </thead>
              <tbody>
                {listedFs.map((r) => {
                  const selected = r.mount === selectedMount;
                  const st = fsStatusLabel(r);
                  return (
                    <tr
                      key={r.mount}
                      className={cn(
                        "cursor-pointer border-t border-[var(--color-border)] hover:bg-[var(--color-accent)]",
                        selected && "bg-[var(--color-primary)]/15",
                      )}
                      onClick={() => {
                        setSelectedMount(r.mount);
                        if (mode === "create" && r.vg_name) setVgName(r.vg_name);
                      }}
                    >
                      <td className="max-w-[9rem] truncate px-2 py-1.5 font-mono" title={r.mount}>
                        {r.mount}
                      </td>
                      <td className="px-2 py-1.5 tabular-nums">{r.size || "—"}</td>
                      <td className="px-2 py-1.5 tabular-nums">{r.used || "—"}</td>
                      <td className="px-2 py-1.5 tabular-nums">{r.avail || "—"}</td>
                      <td className="px-2 py-1.5 tabular-nums">{r.use_pct || "—"}</td>
                      <td className="px-2 py-1.5 font-mono text-[var(--theme-link)]">{r.vg_name || "—"}</td>
                      <td className="px-2 py-1.5 font-mono">{r.lv_name || "—"}</td>
                      <td className="px-2 py-1.5 tabular-nums">
                        {typeof r.vg_free_gb === "number" ? `${r.vg_free_gb.toFixed(1)}G` : "—"}
                      </td>
                      <td className="px-2 py-1.5">
                        {st.kind === "ok" ? (
                          <Badge variant="success">{st.text}</Badge>
                        ) : st.kind === "warn" ? (
                          <Badge variant="warning">{st.text}</Badge>
                        ) : (
                          <Badge variant="muted">{st.text}</Badge>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {!listedFs.length && !loading ? (
                  <tr>
                    <td
                      colSpan={9}
                      className="px-3 py-4 text-center text-[var(--color-muted-foreground)]"
                    >
                      Bu mod için uygun FS yok
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>

        {mode === "extend" ? (
          <div className="grid shrink-0 gap-2 sm:grid-cols-2">
            <div>
              <label className="mb-0.5 block text-[10px] text-[var(--color-muted-foreground)]">
                Seçili FS
              </label>
              <p className="h-8 truncate rounded-md border border-[var(--color-border)] px-2 leading-8 font-mono text-xs">
                {selectedMount || "—"}
                {effectiveVgName ? ` · ${effectiveVgName}` : ""}
              </p>
            </div>
            <div>
              <div className="mb-0.5 flex flex-wrap items-center gap-2">
                <label className="text-[10px] text-[var(--color-muted-foreground)]">
                  Büyütülecek miktar (GB)
                  <span className="ml-1 font-normal opacity-80">
                    · VG boş: {freeGb.toFixed(1)} GB
                    {selectedDiskGb > 0 ? ` · disk ~${selectedDiskGb} GB` : ""}
                  </span>
                </label>
                <button
                  type="button"
                  title="VG’deki tüm boş alanı kullan (lvextend -l +100%FREE)"
                  onClick={() => setUseAllFree((v) => !v)}
                  className={cn(
                    "shrink-0 rounded border px-1.5 py-0.5 text-[10px] leading-none",
                    useAllFree
                      ? "border-emerald-400/50 bg-emerald-500/20 text-emerald-200"
                      : "border-[var(--color-border)] text-[var(--color-muted-foreground)] hover:border-[var(--color-border)]",
                  )}
                >
                  %100’ü kullan
                </button>
              </div>
              <Input
                className="h-8"
                type="number"
                min={MIN_SIZE_GB}
                max={500}
                step="0.1"
                value={useAllFree ? "" : addGb}
                onChange={(e) => {
                  setUseAllFree(false);
                  setAddGb(e.target.value.replace(",", "."));
                }}
                placeholder={useAllFree ? "%100 VG free" : "örn. 20 veya 0.5"}
                disabled={useAllFree}
                required={!useAllFree}
              />
            </div>
          </div>
        ) : mode === "organize" ? (
          <div className="space-y-2 shrink-0">
            <p className="text-[10px] text-amber-200/90">
              Yıkıcı: boş + idle FS. umount → fstab sil → lvremove -y → yeni LV’ler. Kalan VG’de kalır.
              Kaynak: <span className="font-mono">{selectedMount || "—"}</span>
              {sourceFs ? (
                <span className="ml-1 opacity-80">
                  · ~{formatGb(orgBudgetGb)} GB · used {sourceFs.used || "?"}
                </span>
              ) : null}
            </p>
            <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
              <table className="w-full min-w-[36rem] text-[11px]">
                <thead className="bg-[var(--theme-inset)] text-[var(--color-muted-foreground)]">
                  <tr>
                    <th className="px-2 py-1.5 text-left font-medium">Mount</th>
                    <th className="px-2 py-1.5 text-left font-medium">GB</th>
                    <th className="px-2 py-1.5 text-left font-medium">FS</th>
                    <th className="px-2 py-1.5 text-left font-medium">Owner</th>
                    <th className="px-2 py-1.5 text-left font-medium">LV</th>
                    <th className="px-2 py-1.5" />
                  </tr>
                </thead>
                <tbody>
                  {orgSlices.map((s) => {
                    const otherFixed = orgSlices.reduce((sum, r) => {
                      if (r.id === s.id || r.useAllFree) return sum;
                      const n = parseSizeGb(r.sizeGb);
                      return sum + (n >= MIN_SIZE_GB ? n : 0);
                    }, 0);
                    const rowAllFreeGb = Math.max(0, orgBudgetGb - otherFixed);
                    return (
                    <tr key={s.id} className="border-t border-[var(--color-border)]">
                      <td className="px-1 py-1">
                        <Input
                          className="h-7 font-mono text-[11px]"
                          placeholder="/data/app"
                          value={s.mount}
                          onChange={(e) =>
                            setOrgSlices((prev) =>
                              prev.map((x) => (x.id === s.id ? { ...x, mount: e.target.value } : x)),
                            )
                          }
                        />
                      </td>
                      <td className="min-w-[7.5rem] px-1 py-1">
                        <div className="flex flex-col gap-0.5">
                          <Input
                            className="h-7 text-[11px]"
                            type="number"
                            min={MIN_SIZE_GB}
                            step="0.1"
                            placeholder={s.useAllFree ? "%100 bütçe" : "0.5 / 1"}
                            value={s.useAllFree ? "" : s.sizeGb}
                            disabled={s.useAllFree}
                            onChange={(e) =>
                              setOrgSlices((prev) =>
                                prev.map((x) =>
                                  x.id === s.id
                                    ? {
                                        ...x,
                                        useAllFree: false,
                                        sizeGb: e.target.value.replace(",", "."),
                                      }
                                    : x,
                                ),
                              )
                            }
                          />
                          <button
                            type="button"
                            title="Kaynak LV bütçesinden kalanın tamamını bu satıra yaz"
                            onClick={() =>
                              setOrgSlices((prev) =>
                                prev.map((x) =>
                                  x.id === s.id
                                    ? { ...x, useAllFree: !x.useAllFree, sizeGb: "" }
                                    : { ...x, useAllFree: false },
                                ),
                              )
                            }
                            className={cn(
                              "rounded border px-1 py-0.5 text-[9px] leading-none",
                              s.useAllFree
                                ? "border-emerald-400/50 bg-emerald-500/20 text-[var(--theme-success-fg)]"
                                : "border-[var(--color-border)] text-[var(--color-muted-foreground)] hover:border-[var(--color-muted-foreground)]",
                            )}
                          >
                            %100’ü kullan
                            {s.useAllFree && orgBudgetGb > 0 ? ` (~${formatGb(rowAllFreeGb)}G)` : ""}
                          </button>
                        </div>
                      </td>
                      <td className="w-24 px-1 py-1">
                        <Select
                          value={s.fstype}
                          onValueChange={(v) =>
                            setOrgSlices((prev) =>
                              prev.map((x) => (x.id === s.id ? { ...x, fstype: v } : x)),
                            )
                          }
                        >
                          <SelectTrigger className="h-7 text-[11px]">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="xfs">xfs</SelectItem>
                            <SelectItem value="ext4">ext4</SelectItem>
                          </SelectContent>
                        </Select>
                      </td>
                      <td className="px-1 py-1">
                        <Input
                          className="h-7 font-mono text-[11px]"
                          placeholder="user:group"
                          value={s.owner}
                          onChange={(e) =>
                            setOrgSlices((prev) =>
                              prev.map((x) =>
                                x.id === s.id ? { ...x, owner: e.target.value } : x,
                              ),
                            )
                          }
                        />
                      </td>
                      <td className="px-2 py-1 font-mono text-[10px] text-[var(--theme-link)]">
                        {s.mount.trim().startsWith("/") ? lvNamePreview(s.mount) : "—"}
                      </td>
                      <td className="px-1 py-1">
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          className="h-7 px-2"
                          disabled={orgSlices.length <= 1}
                          onClick={() => setOrgSlices((prev) => prev.filter((x) => x.id !== s.id))}
                        >
                          −
                        </Button>
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Button
                type="button"
                size="sm"
                variant="secondary"
                className="h-7"
                onClick={() =>
                  setOrgSlices((prev) => [
                    ...prev,
                    {
                      id: String(Date.now()),
                      mount: "",
                      sizeGb: "",
                      useAllFree: false,
                      fstype: "xfs",
                      owner: "",
                    },
                  ])
                }
              >
                + FS satırı
              </Button>
              <p
                className={cn(
                  "font-mono text-[10px]",
                  orgBudgetGb > 0 && orgUsedSum > orgBudgetGb
                    ? "text-[var(--color-destructive)]"
                    : "text-[var(--color-muted-foreground)]",
                )}
              >
                kullanılan {formatGb(orgUsedSum)} GB
                {orgBudgetGb > 0 ? ` / bütçe ~${formatGb(orgBudgetGb)} GB` : ""}
                {" · "}
                VG’de kalacak ~{formatGb(orgRemainGb)} GB
                {orgHasAllFree ? " · %100 satırı kalanı (100%FREE) alır" : ""}
              </p>
            </div>
          </div>
        ) : (
          <div className="grid shrink-0 gap-2 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <label className="mb-0.5 block text-[10px] text-[var(--color-muted-foreground)]">
                Hedef VG (root hariç)
              </label>
              <Select
                value={vgName || undefined}
                onValueChange={(v) => {
                  setVgName(v);
                  setSelectedMount("");
                }}
              >
                <SelectTrigger className="h-8 font-mono">
                  <SelectValue placeholder="VG seçin" />
                </SelectTrigger>
                <SelectContent>
                  {createVgs.map((v) => (
                    <SelectItem key={v.name} value={v.name}>
                      {v.name} · boş {v.free_gb.toFixed(1)} GB / {v.size_gb.toFixed(1)} GB
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {!createVgs.length ? (
                <p className="mt-1 text-[10px] text-amber-200/90">Uygun (non-root) VG yok</p>
              ) : null}
            </div>
            <div className="sm:col-span-2">
              <label className="mb-0.5 block text-[10px] text-[var(--color-muted-foreground)]">
                Yeni mount
                {autoLvName ? (
                  <span className="ml-1 font-mono text-[var(--theme-link)]">· LV: {autoLvName}</span>
                ) : null}
              </label>
              <Input
                className="h-8 font-mono"
                placeholder="/data2"
                value={createMount}
                onChange={(e) => setCreateMount(e.target.value)}
                required
              />
            </div>
            <div>
              <div className="mb-0.5 flex h-5 flex-wrap items-center gap-2">
                <label className="text-[10px] text-[var(--color-muted-foreground)]">
                  FS boyutu (GB)
                  <span className="ml-1 font-normal opacity-80">· VG boş: {freeGb.toFixed(1)} GB</span>
                </label>
                <button
                  type="button"
                  title="VG’deki tüm boş alanı kullan (lvcreate -l 100%FREE)"
                  onClick={() => setUseAllFree((v) => !v)}
                  className={cn(
                    "shrink-0 rounded border px-1.5 py-0.5 text-[10px] leading-none",
                    useAllFree
                      ? "border-emerald-400/50 bg-emerald-500/20 text-emerald-200"
                      : "border-[var(--color-border)] text-[var(--color-muted-foreground)] hover:border-[var(--color-border)]",
                  )}
                >
                  %100’ü kullan
                </button>
              </div>
              <Input
                className="h-8"
                type="number"
                min={MIN_SIZE_GB}
                max={2000}
                step="0.1"
                value={useAllFree ? "" : sizeGb}
                onChange={(e) => {
                  setUseAllFree(false);
                  setSizeGb(e.target.value.replace(",", "."));
                }}
                placeholder={useAllFree ? "%100 VG free" : "örn. 50 veya 0.5"}
                disabled={useAllFree}
                required={!useAllFree}
              />
            </div>
            <div>
              <label className="mb-0.5 block h-5 text-[10px] leading-5 text-[var(--color-muted-foreground)]">
                Dosya sistemi
              </label>
              <Select value={fstype} onValueChange={setFstype}>
                <SelectTrigger className="h-8">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="xfs">XFS</SelectItem>
                  <SelectItem value="ext4">EXT4</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Input
              className="h-8 font-mono sm:col-span-2"
              placeholder="Owner (opsiyonel, user veya user:group)"
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
            />
          </div>
        )}

        <div className="flex shrink-0 flex-wrap items-center gap-2 border-t border-[var(--color-border)] pt-2">
          {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
          {needsDisks || useAllFree ? (
            <p className="text-xs text-amber-200/90">
              {useAllFree ? "%100 VG free · " : ""}
              VG boş {freeGb.toFixed(1)} GB
              {!useAllFree ? ` · ihtiyaç ${needGb} GB` : ""}
              {selectedDisks.length > 0 ? ` · disk usable ~${selectedDiskGb} GB (−16MiB/disk)` : ""}
              {needsDisks && !spaceOk
                ? " — yetersiz, ek disk seçin"
                : needsDisks && spaceOk
                  ? " — yeterli, partition + vgextend sonra işlem"
                  : useAllFree
                    ? " — VG’deki tüm boş alan kullanılacak"
                    : ""}
            </p>
          ) : null}
          <Button type="submit" size="sm" disabled={busy || !previewReady || loading}>
            {busy ? "…" : t("preview")}
          </Button>
        </div>

        {mode !== "organize" ? (
        <aside
          className={cn(
            "mt-auto min-h-[7rem] shrink-0 overflow-hidden rounded-lg border border-[var(--color-border)]",
            showDiskPanel ? "border-amber-500/40 bg-amber-500/5" : "bg-[var(--theme-surface-deep)]",
          )}
        >
          <div className="flex items-center justify-between border-b border-[var(--color-border)] px-3 py-1.5">
            <p className="text-[11px] font-medium text-[var(--color-foreground)]">
              Partitionsuz diskler ({inv?.free_disks.length ?? 0})
              {needsDisks && selectedDisks.length > 0 ? ` · seçili ${selectedDisks.length}` : ""}
            </p>
          </div>
          <div className="max-h-36 overflow-y-auto px-2 py-1.5 font-mono text-[10px] leading-4 text-[var(--color-muted-foreground)]">
            {showDiskPanel || needsDisks ? (
              <p className="mb-1 px-1 text-[10px] text-amber-200/90">
                {needsDisks
                  ? "VG boş alan yetersiz. 1+ disk seçin (partition → pvcreate → vgextend → sonra "
                  : "İsteğe bağlı disk ekleyebilirsiniz (önce vgextend, sonra "}
                {mode === "extend" ? "lvextend" : "lvcreate"}
                {useAllFree ? " %100 free" : ""}
                ).
              </p>
            ) : (
              <p className="mb-1 px-1 text-[10px] text-[var(--color-muted-foreground)]">
                VG alanı yeterliyse disk seçimi gerekmez. Yetmezse veya “%100’ü kullan” ile daha fazla
                alan için disk seçin.
              </p>
            )}
            {(inv?.free_disks || []).length === 0 ? (
              <p className="px-1 text-[var(--color-muted-foreground)]">(partitionsuz uygun disk yok)</p>
            ) : (
              inv!.free_disks.map((d) => {
                const key = freeDiskKey(d);
                const on = selectedDiskKeys.has(key);
                const clickable = disksSelectable;
                const usable = diskUsableGb(d);
                return (
                  <button
                    key={key}
                    type="button"
                    disabled={!clickable || loading}
                    onClick={() => toggleDisk(d)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded px-1 py-0.5 text-left",
                      clickable ? "cursor-pointer hover:bg-[var(--color-accent)]" : "cursor-default opacity-70",
                      on && "bg-emerald-500/15 text-[var(--theme-success-strong)]",
                    )}
                  >
                    <span
                      className={cn(
                        "flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-sm border text-[9px]",
                        on
                          ? "border-emerald-400 bg-emerald-500 text-white"
                          : "border-[var(--color-border)] text-transparent",
                      )}
                    >
                      {on ? "✓" : ""}
                    </span>
                    <span className={on ? "text-[var(--theme-success-strong)]" : "text-[var(--theme-link)]"}>{d.alias}</span>
                    <span>
                      {d.size} · usable ~{formatGb(usable)}G
                    </span>
                  </button>
                );
              })
            )}
          </div>
        </aside>
        ) : null}
      </form>
    </div>
  );
}
