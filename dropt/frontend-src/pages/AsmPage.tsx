import { FormEvent, MouseEvent as ReactMouseEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  CheckSquare,
  ClipboardList,
  Eraser,
  RefreshCw,
} from "lucide-react";
import {
  AsmDisk,
  AsmDiskGroup,
  AsmScanResult,
  createJob,
  fetchAsmSeqNext,
  listServers,
  previewJob,
  scanAsmDisks,
  ServerPublic,
} from "@/api";
import { IconButton } from "@/components/IconButton";
import { ServerPicker } from "@/components/ServerPicker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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

function diskKey(d: AsmDisk) {
  return `${d.wwid || d.alias}`;
}

function buildClusterDisplayList(
  viewDisks: AsmDisk[],
  peerDisks: AsmDisk[],
): { shared: AsmDisk[]; local: AsmDisk[] } {
  const peerWwids = new Set(peerDisks.map((d) => d.wwid).filter(Boolean));
  const shared: AsmDisk[] = [];
  const local: AsmDisk[] = [];
  for (const d of viewDisks) {
    const tagged: AsmDisk = {
      ...d,
      scope: peerWwids.has(d.wwid) ? "shared" : "local",
    };
    if (tagged.scope === "shared") shared.push(tagged);
    else local.push(tagged);
  }
  return { shared, local };
}

function normalizeWwid(raw: string): string {
  return raw.trim().toLowerCase().replace(/[^a-z0-9]/g, "");
}

/** Storage listesi: satır / virgül / noktalı virgül / boşluk */
function parseWwidList(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of text.split(/[\s,;]+/)) {
    const n = normalizeWwid(part);
    if (!n || seen.has(n)) continue;
    seen.add(n);
    out.push(n);
  }
  return out;
}

/**
 * Storage WWID ↔ multipath WWID:
 * Yapıştırılan değer en az 16 karakter; sunucu WWID'inin son 16 hanesi ile
 * yapıştırılanın son 16 hanesi eşitse eşleşir.
 */
function wwidMatchesPaste(foundWwid: string, pastedNorm: string): boolean {
  const f = normalizeWwid(foundWwid);
  if (!f || pastedNorm.length < 16 || f.length < 16) return false;
  return f.slice(-16) === pastedNorm.slice(-16);
}

type LeftUsableOpts = {
  cluster: boolean;
  /** multipath: WWID listesi onayı zorunlu */
  wwidGate: boolean;
  /** null = henüz kontrol edilmedi → seçilemez */
  matchedWwids: Set<string> | null;
};

function leftUsable(d: AsmDisk, opts: LeftUsableOpts): boolean {
  if (!d.usable) return false;
  if (opts.cluster && d.scope !== "shared") return false;
  if (opts.wwidGate) {
    if (!opts.matchedWwids) return false;
    if (!opts.matchedWwids.has(d.wwid)) return false;
  }
  return true;
}

function mergeAsmGroups(lists: AsmDiskGroup[][]): AsmDiskGroup[] {
  const map = new Map<string, AsmDiskGroup>();
  for (const list of lists) {
    for (const g of list || []) {
      const label = (g.label || "").trim().toUpperCase();
      if (!label) continue;
      const cur = map.get(label);
      if (!cur) {
        map.set(label, {
          label,
          count: g.count || 0,
          samples: [...(g.samples || [])].slice(0, 3),
        });
      } else {
        cur.count = Math.max(cur.count, g.count || 0);
        for (const s of g.samples || []) {
          if ((cur.samples?.length || 0) >= 3) break;
          if (!cur.samples) cur.samples = [];
          if (!cur.samples.includes(s)) cur.samples.push(s);
        }
      }
    }
  }
  return [...map.values()].sort((a, b) => a.label.localeCompare(b.label));
}

/** Grup etiketine göre chip renkleri (role / anahtar kelime). */
function asmGroupChipClass(label: string): string {
  const u = (label || "").toUpperCase();
  if (/\bREDO\b|_REDO|REDO_/.test(u) || u.endsWith("REDO") || u.includes("REDO")) {
    return "border-rose-400/50 bg-rose-500/20 text-rose-700 dark:text-rose-300";
  }
  if (/\bARCH\b|_ARCH|ARCH_/.test(u) || u.includes("ARCH")) {
    return "border-amber-400/50 bg-amber-500/20 text-amber-800 dark:text-amber-300";
  }
  if (/\bRECO\b|_RECO|RECO_/.test(u) || u.includes("RECO")) {
    return "border-violet-400/50 bg-violet-500/20 text-violet-800 dark:text-violet-300";
  }
  if (/\bTEMP\b|_TEMP|TEMP_/.test(u) || u.includes("TEMP")) {
    return "border-orange-400/50 bg-orange-500/20 text-orange-800 dark:text-orange-300";
  }
  if (/\bCONF\b|_CONF|CONF_/.test(u) || u.includes("CONF")) {
    return "border-teal-400/50 bg-teal-500/20 text-teal-800 dark:text-teal-300";
  }
  if (/\bDATA\b|_DATA|DATA_/.test(u) || u.includes("DATA")) {
    return "border-sky-400/50 bg-sky-500/20 text-sky-800 dark:text-sky-300";
  }
  if (/\bFRA\b|_FRA|FRA_/.test(u) || u.includes("FRA")) {
    return "border-fuchsia-400/50 bg-fuchsia-500/20 text-fuchsia-800 dark:text-fuchsia-300";
  }
  // bilinmeyen / özel önekler — sabit paletten hash
  const palette = [
    "border-emerald-400/50 bg-emerald-500/20 text-emerald-800 dark:text-emerald-300",
    "border-cyan-400/50 bg-cyan-500/20 text-cyan-800 dark:text-cyan-300",
    "border-indigo-400/50 bg-indigo-500/20 text-indigo-800 dark:text-indigo-300",
    "border-lime-400/50 bg-lime-500/20 text-lime-800 dark:text-lime-300",
  ];
  let h = 0;
  for (let i = 0; i < u.length; i++) h = (h + u.charCodeAt(i) * (i + 1)) % palette.length;
  return palette[h]!;
}

type Side = "left" | "right";

type DragSession = {
  side: Side;
  keys: string[];
  originX: number;
  originY: number;
  x: number;
  y: number;
  active: boolean; // threshold aşıldı mı
};

export function AsmPage() {
  const token = getToken()!;
  const afterPreview = useAfterPreview();
  const opsCtx = useOpsWizard();
  const embedded = Boolean(opsCtx?.embedded);
  const t = useT();
  const { serverId: qServerId, serverIds: qServerIds } = useServerQuery();
  const [servers, setServers] = useState<ServerPublic[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [primaryId, setPrimaryId] = useState("");
  const [viewServerId, setViewServerId] = useState("");
  const [nodeScans, setNodeScans] = useState<Record<number, AsmScanResult>>({});
  const [available, setAvailable] = useState<AsmDisk[]>([]);
  const [selected, setSelected] = useState<AsmDisk[]>([]);
  const [, setCached] = useState(false);
  const [diskMode, setDiskMode] = useState<"multipath" | "sd" | string>("multipath");
  const [, setMachineType] = useState("");
  const [asmGroups, setAsmGroups] = useState<AsmDiskGroup[]>([]);
  const [aliasPrefix, setAliasPrefix] = useState("");
  const [talepId, setTalepId] = useState("");
  const [scanning, setScanning] = useState(false);
  const [loadingList, setLoadingList] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(() => new Set());
  const [dragUi, setDragUi] = useState<DragSession | null>(null);
  const [wwidPanelOpen, setWwidPanelOpen] = useState(false);
  const [wwidPasteText, setWwidPasteText] = useState("");
  /** null = kontrol yok; Set = eşleşen bulunan disk WWID'leri (sistemdeki tam değer) */
  const [matchedWwids, setMatchedWwids] = useState<Set<string> | null>(null);
  const [unmatchedPaste, setUnmatchedPaste] = useState<string[]>([]);
  const [wwidCheckMsg, setWwidCheckMsg] = useState<string | null>(null);
  /** SCSI yenilemeli tarama (refresh=true) başarıyla bitti mi */
  const [scsiScanDone, setScsiScanDone] = useState(false);
  /** sunucudaki max indeks + 1; null = henüz alınmadı */
  const [asmSeqNext, setAsmSeqNext] = useState<number | null>(null);

  const lastPickRef = useRef<{ side: Side; key: string } | null>(null);
  const availableRef = useRef(available);
  const selectedRef = useRef(selected);
  const pickedRef = useRef(picked);
  const dragRef = useRef<DragSession | null>(null);
  const leftZoneRef = useRef<HTMLDivElement | null>(null);
  const rightZoneRef = useRef<HTMLDivElement | null>(null);
  const skipClickRef = useRef(false);

  availableRef.current = available;
  selectedRef.current = selected;
  pickedRef.current = picked;

  useEffect(() => {
    void listServers(token, { page: 1, page_size: 200, status: "ready" }).then((d) => {
      setServers(d.items);
      const initialRaw = qServerIds.length
        ? qServerIds.map(Number)
        : qServerId
          ? [Number(qServerId)]
          : d.items[0]
            ? [d.items[0].id]
            : [];
      const initial = initialRaw.slice(0, 2);
      setSelectedIds(initial);
      const first = String(initial[0] || "");
      setPrimaryId(first);
      setViewServerId(first);
    });
  }, [token, qServerId, qServerIds.join(",")]);

  const cluster = selectedIds.length > 1;

  function applyGroupAsPrefix(label: string) {
    const v = (label || "").trim().toUpperCase().slice(0, 17);
    if (!v) return;
    setAliasPrefix(v);
  }
  const wwidGate = diskMode === "multipath";
  const usableOpts: LeftUsableOpts = useMemo(
    () => ({ cluster, wwidGate, matchedWwids }),
    [cluster, wwidGate, matchedWwids],
  );
  const selectedServers = useMemo(
    () => servers.filter((s) => selectedIds.includes(s.id)),
    [servers, selectedIds],
  );
  const viewHostname = useMemo(() => {
    const sid = Number(viewServerId) || selectedIds[0];
    return servers.find((s) => s.id === sid)?.hostname || "";
  }, [servers, viewServerId, selectedIds]);

  const applyCatalogToLists = useCallback((all: AsmDisk[], keepSelected: boolean, matched: Set<string> | null) => {
    if (!keepSelected) {
      setSelected([]);
      setAvailable(all);
      setPicked(new Set());
      return;
    }
    setSelected((prev) => {
      const next = prev.filter((d) => {
        if (!all.some((x) => diskKey(x) === diskKey(d))) return false;
        if (matched && !matched.has(d.wwid)) return false;
        return true;
      });
      const selKeys = new Set(next.map(diskKey));
      setAvailable(all.filter((d) => !selKeys.has(diskKey(d))));
      return next;
    });
  }, []);

  const rebuildFromScans = useCallback(
    (
      scans: Record<number, AsmScanResult>,
      viewId: number,
      peerId: number,
      keepSelected: boolean,
      matched: Set<string> | null,
    ) => {
      const viewResult = scans[viewId];
      const peerResult = scans[peerId];
      if (!viewResult || !peerResult) return;
      const { shared, local } = buildClusterDisplayList(viewResult.disks || [], peerResult.disks || []);
      const all = [...shared, ...local];
      setCached(Boolean(viewResult.cached && peerResult.cached));
      setDiskMode(viewResult.disk_mode || "multipath");
      setMachineType(viewResult.machine_type || "");
      setAsmGroups(mergeAsmGroups([viewResult.groups || [], peerResult.groups || []]));
      applyCatalogToLists(all, keepSelected, matched);
      if (!all.length) {
        setError(
          (viewResult.disk_mode || "multipath") === "sd"
            ? "Uygun partitionsuz disk bulunamadı"
            : "Uygun disk bulunamadı (multipath / LV hariç)",
        );
      }
    },
    [applyCatalogToLists],
  );

  const resetWwidCheck = useCallback(() => {
    setMatchedWwids(null);
    setUnmatchedPaste([]);
    setWwidCheckMsg(null);
  }, []);

  const loadDisks = useCallback(
    async (refresh: boolean, keepSelected = true) => {
      if (refresh) setScanning(true);
      else setLoadingList(true);
      setError(null);
      try {
        const ids = selectedIds.slice(0, 2);
        if (!ids.length) throw new Error("Sunucu seçin");

        const matched = keepSelected ? matchedWwids : null;
        if (!keepSelected) resetWwidCheck();

        if (ids.length === 1) {
          const sid = ids[0]!;
          const result = await scanAsmDisks(token, sid, { refresh });
          setNodeScans({ [sid]: result });
          setCached(Boolean(result.cached));
          setDiskMode(result.disk_mode || "multipath");
          setMachineType(result.machine_type || "");
          setAsmGroups(mergeAsmGroups([result.groups || []]));
          const all = result.disks || [];
          applyCatalogToLists(all, keepSelected, matched);
          if (refresh) setScsiScanDone(true);
          if (!all.length) {
            setError(
              (result.disk_mode || "multipath") === "sd"
                ? "Uygun partitionsuz disk bulunamadı"
                : "Uygun disk bulunamadı (multipath / LV hariç)",
            );
          }
          return;
        }

        const results = await Promise.all(ids.map((id) => scanAsmDisks(token, id, { refresh })));
        const scans: Record<number, AsmScanResult> = {};
        for (const r of results) scans[r.server_id] = r;
        setNodeScans(scans);
        if (refresh) setScsiScanDone(true);

        const viewId = Number(viewServerId) || ids[0]!;
        const peerId = ids.find((id) => id !== viewId) ?? ids[1]!;
        rebuildFromScans(scans, viewId, peerId, keepSelected, matched);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Tarama başarısız");
      } finally {
        setScanning(false);
        setLoadingList(false);
      }
    },
    [
      token,
      selectedIds,
      viewServerId,
      matchedWwids,
      applyCatalogToLists,
      rebuildFromScans,
      resetWwidCheck,
    ],
  );

  useEffect(() => {
    if (!selectedIds.length) return;
    setScsiScanDone(false);
    resetWwidCheck();
    void loadDisks(false, false);
  }, [selectedIds.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!cluster || selectedIds.length !== 2) return;
    const ids = selectedIds.slice(0, 2);
    const viewId = Number(viewServerId) || ids[0]!;
    const peerId = ids.find((id) => id !== viewId);
    if (!peerId || !nodeScans[viewId] || !nodeScans[peerId]) return;
    rebuildFromScans(nodeScans, viewId, peerId, true, matchedWwids);
  }, [viewServerId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const prefix = aliasPrefix.trim();
    if (!prefix || !selectedIds.length) {
      setAsmSeqNext(null);
      return;
    }
    if (!/^[a-zA-Z][a-zA-Z0-9_]{0,16}$/.test(prefix)) {
      setAsmSeqNext(null);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void fetchAsmSeqNext(token, prefix, selectedIds.slice(0, 2))
        .then((r) => {
          if (!cancelled) setAsmSeqNext(r.next_index);
        })
        .catch(() => {
          if (!cancelled) setAsmSeqNext(1);
        });
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [token, aliasPrefix, selectedIds.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  function runWwidCheck() {
    const pasted = parseWwidList(wwidPasteText);
    if (!pasted.length) {
      setWwidCheckMsg("En az bir WWID yapıştırın");
      setMatchedWwids(null);
      setUnmatchedPaste([]);
      return;
    }
    const tooShort = pasted.filter((p) => p.length < 16);
    const validPaste = pasted.filter((p) => p.length >= 16);
    if (!validPaste.length) {
      setWwidCheckMsg("Her WWID en az 16 karakter olmalı");
      setMatchedWwids(null);
      setUnmatchedPaste(tooShort);
      return;
    }
    const catalog = [...availableRef.current, ...selectedRef.current];
    const matched = new Set<string>();
    const usedPaste = new Set<string>();
    for (const d of catalog) {
      if (!d.wwid) continue;
      for (const p of validPaste) {
        if (wwidMatchesPaste(d.wwid, p)) {
          matched.add(d.wwid);
          usedPaste.add(p);
          break;
        }
      }
    }
    const missing = [
      ...validPaste.filter((p) => !usedPaste.has(p)),
      ...tooShort,
    ];
    setMatchedWwids(matched);
    setUnmatchedPaste(missing);
    const shortNote = tooShort.length ? ` · ${tooShort.length} WWID <16 karakter` : "";
    setWwidCheckMsg(
      missing.length
        ? `${matched.size} disk eşleşti · ${validPaste.filter((p) => !usedPaste.has(p)).length} WWID taramada yok${shortNote}`
        : `${matched.size} disk eşleşti`,
    );
    // Seçimde artık eşleşmeyenleri geri sola at
    setSelected((prev) => {
      const keep = prev.filter((d) => matched.has(d.wwid));
      const drop = prev.filter((d) => !matched.has(d.wwid));
      if (drop.length) {
        setAvailable((av) => {
          const have = new Set(av.map(diskKey));
          return [...av, ...drop.filter((d) => !have.has(diskKey(d)))];
        });
      }
      return keep;
    });
    clearPicked();
    setWwidPanelOpen(false);
  }

  function clearPicked() {
    setPicked(new Set());
    lastPickRef.current = null;
  }

  function moveKeysToSelected(keys: string[]) {
    const keySet = new Set(keys.filter(Boolean));
    if (!keySet.size) return;
    const moving = availableRef.current.filter((d) => keySet.has(diskKey(d)) && leftUsable(d, usableOpts));
    if (!moving.length) return;
    const moveKeys = new Set(moving.map(diskKey));
    setAvailable((prev) => prev.filter((x) => !moveKeys.has(diskKey(x))));
    setSelected((prev) => {
      const have = new Set(prev.map(diskKey));
      return [...prev, ...moving.filter((d) => !have.has(diskKey(d)))];
    });
    clearPicked();
  }

  function moveKeysToAvailable(keys: string[]) {
    const keySet = new Set(keys.filter(Boolean));
    if (!keySet.size) return;
    const moving = selectedRef.current.filter((d) => keySet.has(diskKey(d)));
    if (!moving.length) return;
    const moveKeys = new Set(moving.map(diskKey));
    setSelected((prev) => prev.filter((x) => !moveKeys.has(diskKey(x))));
    setAvailable((prev) => {
      const have = new Set(prev.map(diskKey));
      return [...prev, ...moving.filter((d) => !have.has(diskKey(d)))];
    });
    clearPicked();
  }

  function applyPick(side: Side, d: AsmDisk, e: { shiftKey: boolean; ctrlKey: boolean; metaKey: boolean }) {
    const key = diskKey(d);
    const list = side === "left" ? availableRef.current : selectedRef.current;
    const keys = list.map(diskKey);

    setPicked((prev) => {
      const next = new Set(prev);
      if (e.shiftKey && lastPickRef.current?.side === side) {
        const a = keys.indexOf(lastPickRef.current.key);
        const b = keys.indexOf(key);
        if (a >= 0 && b >= 0) {
          const [lo, hi] = a < b ? [a, b] : [b, a];
          if (!(e.ctrlKey || e.metaKey)) next.clear();
          for (let i = lo; i <= hi; i++) next.add(keys[i]!);
          return next;
        }
      }
      if (e.ctrlKey || e.metaKey) {
        if (next.has(key)) next.delete(key);
        else next.add(key);
      } else {
        if (next.has(key) && next.size === 1) next.clear();
        else {
          next.clear();
          next.add(key);
        }
      }
      return next;
    });
    if (!e.shiftKey || !lastPickRef.current || lastPickRef.current.side !== side) {
      lastPickRef.current = { side, key };
    }
  }

  function resolveDragKeys(side: Side, d: AsmDisk): string[] {
    const key = diskKey(d);
    const list = side === "left" ? availableRef.current : selectedRef.current;
    const listKeys = new Set(list.map(diskKey));
    const pickedNow = pickedRef.current;
    if (pickedNow.has(key)) {
      let keys = [...pickedNow].filter((k) => listKeys.has(k));
      if (side === "left") {
        keys = keys.filter((k) => {
          const d = list.find((x) => diskKey(x) === k);
          return d ? leftUsable(d, usableOpts) : false;
        });
      }
      return keys;
    }
    if (side === "right" || leftUsable(d, usableOpts)) return [key];
    return [];
  }

  function zoneUnderPoint(x: number, y: number): Side | null {
    const left = leftZoneRef.current?.getBoundingClientRect();
    const right = rightZoneRef.current?.getBoundingClientRect();
    if (right && x >= right.left && x <= right.right && y >= right.top && y <= right.bottom) return "right";
    if (left && x >= left.left && x <= left.right && y >= left.top && y <= left.bottom) return "left";
    return null;
  }

  function endDrag(clientX: number, clientY: number) {
    const session = dragRef.current;
    dragRef.current = null;
    setDragUi(null);
    if (!session?.active) return;
    skipClickRef.current = true;
    window.setTimeout(() => {
      skipClickRef.current = false;
    }, 100);
    const target = zoneUnderPoint(clientX, clientY);
    if (!target || target === session.side) return;
    if (target === "right") moveKeysToSelected(session.keys);
    else moveKeysToAvailable(session.keys);
  }

  useEffect(() => {
    function onMove(e: MouseEvent) {
      const session = dragRef.current;
      if (!session) return;
      const dx = e.clientX - session.originX;
      const dy = e.clientY - session.originY;
      const active = session.active || Math.hypot(dx, dy) > 6;
      const next: DragSession = {
        ...session,
        x: e.clientX,
        y: e.clientY,
        active,
      };
      dragRef.current = next;
      setDragUi(next);
    }
    function onUp(e: MouseEvent) {
      if (!dragRef.current) return;
      endDrag(e.clientX, e.clientY);
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  function onCardMouseDown(side: Side, d: AsmDisk, e: ReactMouseEvent) {
    if (e.button !== 0) return;
    if (e.shiftKey) e.preventDefault();

    // Çoklu seçim modifier ile — sürükleme başlatma
    if (e.shiftKey || e.ctrlKey || e.metaKey) {
      applyPick(side, d, e);
      return;
    }

    const keys = resolveDragKeys(side, d);
    if (!keys.length) return;

    // Sürükleme için mousedown; tıklama mouseup'ta kısa hareketle seçim olur
    const session: DragSession = {
      side,
      keys,
      originX: e.clientX,
      originY: e.clientY,
      x: e.clientX,
      y: e.clientY,
      active: false,
    };
    dragRef.current = session;
  }

  function onCardClick(side: Side, d: AsmDisk, e: ReactMouseEvent) {
    if (skipClickRef.current) return;
    if (e.shiftKey || e.ctrlKey || e.metaKey) return;
    // Sürükleme olmadıysa tek seçim
    if (dragRef.current?.active) return;
    if (side === "left" && !leftUsable(d, usableOpts)) return;
    applyPick(side, d, e);
  }

  function selectAllUsableLeft() {
    const keys = available.filter((x) => leftUsable(x, usableOpts)).map(diskKey);
    setPicked(new Set(keys));
    if (keys[0]) lastPickRef.current = { side: "left", key: keys[0] };
  }

  function formatSeqIndex(n: number): string {
    return n < 1000 ? String(n).padStart(3, "0") : String(n);
  }

  function predictedAlias(d: AsmDisk): string {
    const prefix = aliasPrefix.trim();
    if (!prefix) return "";
    const idxInSelected = selected.findIndex((x) => diskKey(x) === diskKey(d));
    const base = asmSeqNext ?? 1;
    const n = idxInSelected >= 0 ? base + idxInSelected : base;
    return `${prefix}_${formatSeqIndex(n)}`;
  }

  function predictedAsmName(d: AsmDisk): string {
    const alias = predictedAlias(d);
    return alias ? `ASM_${alias}`.toUpperCase() : "";
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (!talepId.trim()) throw new Error("Talep ID zorunlu");
      if (!selected.length) throw new Error("İşlem için en az bir disk sürükleyin");
      if (cluster && selected.some((d) => d.scope !== "shared")) {
        throw new Error("Cluster modunda yalnızca ortak (her iki node'da bulunan) diskler seçilebilir");
      }
      if (wwidGate && (!matchedWwids || selected.some((d) => !matchedWwids.has(d.wwid)))) {
        throw new Error("Önce storage WWID listesini kontrol edin; yalnızca eşleşen diskler seçilebilir");
      }
      if (!aliasPrefix.trim()) throw new Error("Alias öneki zorunlu");
      if (!/^[a-zA-Z][a-zA-Z0-9_]{0,16}$/.test(aliasPrefix.trim())) {
        throw new Error("Alias öneki geçersiz (örn. DATA; en fazla 17 karakter)");
      }
      const primary = Number(primaryId);
      const ordered = [primary, ...selectedIds.filter((id) => id !== primary)];
      const job = await createJob(token, {
        module: "asm",
        action: "add_disk",
        talep_id: talepId.trim(),
        server_ids: ordered,
        payload: {
          primary_server_id: primary,
          alias_prefix: aliasPrefix.trim(),
          disks: selected.map((d) => ({
            wwid: d.wwid,
            alias: d.alias,
            device: d.device,
            size: d.size || "",
            size_bytes: d.size_bytes || 0,
          })),
        },
      });
      afterPreview(await previewJob(token, job.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  function renderCard(d: AsmDisk, side: Side) {
    const key = diskKey(d);
    const isPicked = picked.has(key);
    const canStart = side === "right" || leftUsable(d, usableOpts);
    const dragging = Boolean(dragUi?.active && dragUi.keys.includes(key));
    const predAlias = side === "right" && aliasPrefix ? predictedAlias(d) : "";
    const predAsm = side === "right" && aliasPrefix ? predictedAsmName(d) : "";
    const clusterLocal = cluster && side === "left" && d.scope === "local";
    const awaitingWwid = wwidGate && side === "left" && matchedWwids === null;
    const wwidMatched = wwidGate && matchedWwids?.has(d.wwid);
    const wwidBlocked =
      wwidGate && side === "left" && matchedWwids !== null && !matchedWwids.has(d.wwid);

    return (
      <div
        key={key}
        onMouseDown={(e) => {
          if (!canStart) return;
          onCardMouseDown(side, d, e);
        }}
        onClick={(e) => onCardClick(side, d, e)}
        onDoubleClick={(e) => {
          e.preventDefault();
          if (side === "left" && !leftUsable(d, usableOpts)) return;
          if (side === "left") moveKeysToSelected([key]);
          else moveKeysToAvailable([key]);
        }}
        className={`flex h-7 select-none items-center gap-2 rounded border px-2 text-[10px] leading-none ${
          canStart ? "cursor-grab active:cursor-grabbing" : "cursor-default"
        } ${
          isPicked
            ? "border-emerald-400 bg-emerald-500/15 ring-1 ring-emerald-400/50"
            : leftUsable(d, usableOpts)
              ? "border-[var(--color-border)] bg-[var(--color-card)]"
              : "border-[var(--color-border)] opacity-50"
        } ${dragging ? "opacity-40" : ""}`}
        title={[
          d.alias,
          d.wwid,
          d.size,
          cluster && d.scope === "shared" ? "Ortak disk (her iki node)" : "",
          cluster && d.scope === "local" ? "Yalnızca bu node'da" : "",
          awaitingWwid ? "WWID kontrolü bekleniyor" : "",
          wwidMatched ? "WWID listesi ile eşleşti" : "",
          wwidBlocked ? "WWID listesinde yok" : "",
          predAlias,
          predAsm,
        ]
          .filter(Boolean)
          .join(" · ")}
      >
        <span className="shrink-0 font-mono font-medium">{d.alias}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-[var(--color-muted-foreground)]">
          {d.wwid || "—"}
        </span>
        <span className="shrink-0 tabular-nums text-[var(--color-muted-foreground)]">{d.size || "—"}</span>
        {cluster && side === "left" && d.scope === "shared" ? (
          <Badge variant="default" className="h-4 shrink-0 px-1 text-[9px]">
            Ortak
          </Badge>
        ) : null}
        {clusterLocal ? (
          <Badge variant="muted" className="h-4 shrink-0 px-1 text-[9px]">
            Yerel
          </Badge>
        ) : null}
        {wwidMatched && side === "left" ? (
          <Badge variant="success" className="h-4 shrink-0 px-1 text-[9px]">
            Match
          </Badge>
        ) : null}
        {awaitingWwid && d.usable && (!cluster || d.scope === "shared") ? (
          <Badge variant="muted" className="h-4 shrink-0 px-1 text-[9px]">
            Kilitli
          </Badge>
        ) : null}
        {leftUsable(d, usableOpts) ? (
          <Badge variant="success" className="h-4 shrink-0 px-1 text-[9px]">
            Uygun
          </Badge>
        ) : (
          <Badge variant="muted" className="h-4 shrink-0 px-1 text-[9px]">
            {clusterLocal
              ? "Cluster dışı"
              : wwidBlocked
                ? "Listede yok"
                : awaitingWwid
                  ? "WWID bekliyor"
                  : "Kullanımda"}
          </Badge>
        )}
        {predAsm ? (
          <span className="max-w-[40%] shrink truncate font-mono text-emerald-300/90" title={`${predAlias} → ${predAsm}`}>
            → {predAsm}
          </span>
        ) : null}
      </div>
    );
  }

  const dropTarget = dragUi?.active ? zoneUnderPoint(dragUi.x, dragUi.y) : null;
  const rescanLabel = diskMode === "sd" ? "Yeniden tara" : "Yeniden tara (SCSI)";
  const scanNeedsAttention =
    wwidGate && Boolean(selectedIds.length) && !scanning && !scsiScanDone;
  const wwidNeedsAttention =
    wwidGate &&
    scsiScanDone &&
    matchedWwids === null &&
    (available.length > 0 || selected.length > 0);
  const availableShared = useMemo(
    () => (cluster ? available.filter((d) => d.scope === "shared") : []),
    [available, cluster],
  );
  const availableLocal = useMemo(
    () => (cluster ? available.filter((d) => d.scope === "local") : []),
    [available, cluster],
  );

  function renderDiskSection(title: string, disks: AsmDisk[]) {
    if (!disks.length) return null;
    return (
      <div className="space-y-1">
        <p className="sticky top-0 z-[1] bg-[var(--color-card)] py-0.5 text-[10px] font-medium text-[var(--color-muted-foreground)]">
          {title} ({disks.length})
        </p>
        {disks.map((d) => renderCard(d, "left"))}
      </div>
    );
  }

  return (
    <div
      className={`flex min-h-0 flex-col px-2 py-1 ${
        embedded
          ? "h-[calc(96vh-0.5rem)] max-h-[calc(96vh-0.5rem)]"
          : "h-[calc(100vh-3.25rem)]"
      }`}
    >
      <form
        onSubmit={onSubmit}
        className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-2.5"
      >
        {/* Başlık + Request ID + Label + Preview */}
        <div className="flex shrink-0 flex-wrap items-center gap-2 pr-8">
          <h2 className="shrink-0 text-base font-semibold">{t("wizard_asm")}</h2>
          <Input
            className="h-8 w-[9rem] sm:w-[11rem]"
            placeholder={t("talep_id")}
            value={talepId}
            onChange={(e) => setTalepId(e.target.value)}
            required
          />
          <Input
            className="h-8 w-[7rem] font-mono sm:w-[9rem]"
            placeholder="DATA"
            value={aliasPrefix}
            onChange={(e) => setAliasPrefix(e.target.value)}
            required
            maxLength={17}
            title="Önek → DATA_001 · ASM_DATA_001 (mevcut max+1). Sağdaki gruba tıklayınca dolar."
          />
          <Button type="submit" size="sm" className="h-8" disabled={busy || !selected.length}>
            {busy ? "…" : t("preview")}
          </Button>
          {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
          {loadingList ? (
            <span className="text-xs text-[var(--color-muted-foreground)]">yükleniyor…</span>
          ) : null}
        </div>

        {/* 1) Sunucu | Mevcut ASM grupları */}
        <div
          className="grid min-h-0 shrink-0 grid-cols-1 gap-2 lg:grid-cols-2"
          style={{ height: embedded ? "min(36vh, 300px)" : "min(34vh, 300px)" }}
        >
          <div className="flex min-h-0 flex-col gap-1 overflow-hidden">
            <ServerPicker
              servers={servers}
              value={selectedIds}
              onChange={(ids) => {
                const capped = ids.slice(0, 2);
                setSelectedIds(capped);
                if (capped.length && !capped.includes(Number(primaryId))) {
                  const first = String(capped[0]);
                  setPrimaryId(first);
                  setViewServerId(first);
                }
                if (capped.length === 1) {
                  setViewServerId(String(capped[0]));
                }
                if (!capped.length) {
                  setPrimaryId("");
                  setViewServerId("");
                }
              }}
              multiple
              maxSelected={2}
              label="Sunucu seçimi (en fazla 2)"
              listClassName="max-h-none flex-1 min-h-0"
              className="flex min-h-0 flex-1 flex-col"
            />
            {cluster ? (
              <div className="grid shrink-0 grid-cols-1 gap-1 sm:grid-cols-2">
                <Select value={primaryId || undefined} onValueChange={setPrimaryId}>
                  <SelectTrigger className="h-7 text-xs">
                    <SelectValue placeholder="Ana sunucu (Primary)" />
                  </SelectTrigger>
                  <SelectContent>
                    {selectedServers.map((s) => (
                      <SelectItem key={s.id} value={String(s.id)}>
                        {s.hostname}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select value={viewServerId || undefined} onValueChange={setViewServerId}>
                  <SelectTrigger className="h-7 text-xs">
                    <SelectValue placeholder="Görüntülenen sunucu" />
                  </SelectTrigger>
                  <SelectContent>
                    {selectedServers.map((s) => (
                      <SelectItem key={s.id} value={String(s.id)}>
                        {s.hostname}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : null}
          </div>

          <aside className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--theme-surface-deep)]">
            <div className="flex shrink-0 items-center justify-between gap-2 border-b border-[var(--color-border)] px-2.5 py-1.5">
              <h3 className="truncate text-xs font-semibold text-[var(--color-foreground)]">
                Mevcut ASM grupları
              </h3>
              <span className="shrink-0 text-[10px] font-medium text-[var(--color-muted-foreground)]">
                {asmGroups.length ? `${asmGroups.length} grup` : ""}
              </span>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-2 py-1.5">
              {asmGroups.length === 0 ? (
                <p className="px-1 text-xs text-[var(--color-muted-foreground)]">
                  (oracleasm listdisks boş / grup yok)
                </p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {asmGroups.map((g) => {
                    const active = aliasPrefix.trim().toUpperCase() === g.label;
                    const tip = (g.samples || []).join(", ") || g.label;
                    const color = asmGroupChipClass(g.label);
                    return (
                      <button
                        key={g.label}
                        type="button"
                        title={`${tip} — tıkla: alias öneki = ${g.label}`}
                        onClick={() => applyGroupAsPrefix(g.label)}
                        className={`inline-flex max-w-full items-center gap-1.5 rounded-md border px-2.5 py-1.5 font-mono text-sm font-semibold leading-none tracking-wide shadow-sm transition-all ${color} ${
                          active
                            ? "ring-2 ring-offset-1 ring-offset-[var(--theme-surface-deep)] ring-[var(--color-foreground)] scale-[1.03]"
                            : "hover:brightness-110 hover:shadow"
                        }`}
                      >
                        <span className="truncate">{g.label}</span>
                        <span className="shrink-0 rounded bg-black/10 px-1 py-0.5 text-[11px] font-bold tabular-nums dark:bg-white/15">
                          {g.count}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
            <p className="shrink-0 border-t border-[var(--color-border)] px-2.5 py-1 text-[10px] text-[var(--color-muted-foreground)]">
              Tıklayınca alias öneki dolar · renk = disk türü
            </p>
          </aside>
        </div>

        {/* 3) Bulunan | ikon araç çubuğu | İşlem */}
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 md:grid-cols-[1fr_auto_1fr]">
          <div
            ref={leftZoneRef}
            className={`flex min-h-0 flex-col overflow-hidden rounded-lg border border-dashed p-2 ${
              dropTarget === "left"
                ? "border-sky-400 bg-sky-500/10"
                : "border-[var(--color-border)]"
            }`}
          >
            <p className="mb-1.5 shrink-0 text-xs font-medium text-[var(--color-muted-foreground)]">
              Bulunan diskler ({available.length})
              {cluster && viewHostname ? ` — ${viewHostname}` : ""}
              {wwidGate && matchedWwids === null ? " — WWID kontrolü gerekli" : ""} — sürükle →
            </p>
            {wwidGate && wwidCheckMsg ? (
              <p
                className={`mb-1 shrink-0 text-[10px] ${
                  unmatchedPaste.length
                    ? "text-[var(--color-destructive)]"
                    : "text-[var(--theme-success-strong)]"
                }`}
              >
                {wwidCheckMsg}
              </p>
            ) : null}
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
              {cluster ? (
                <>
                  {renderDiskSection("Ortak diskler", availableShared)}
                  {renderDiskSection(
                    viewHostname ? `Yalnızca ${viewHostname}` : "Yerel diskler",
                    availableLocal,
                  )}
                </>
              ) : (
                available.map((d) => renderCard(d, "left"))
              )}
              {!available.length ? (
                <p className="text-xs text-[var(--color-muted-foreground)]">Liste boş</p>
              ) : null}
            </div>
          </div>

          <div className="flex shrink-0 flex-row items-center justify-center gap-1 md:flex-col md:items-center md:justify-start md:gap-1 md:px-0.5 md:pt-1">
            {wwidGate ? (
              <IconButton
                icon={ClipboardList}
                label="WWID listesi kontrol"
                variant="secondary"
                className={`h-7 w-7 shrink-0 ${
                  wwidNeedsAttention ? "asm-wwid-blink ring-2 ring-amber-400/80" : ""
                }`}
                disabled={!scsiScanDone || (!available.length && !selected.length)}
                onClick={() => setWwidPanelOpen(true)}
              />
            ) : null}
            {/* Check ile diğer butonlar arasında 2 kademe boşluk */}
            {wwidGate ? (
              <>
                <div className="h-7 w-7 shrink-0" aria-hidden />
                <div className="h-7 w-7 shrink-0" aria-hidden />
              </>
            ) : null}
            <IconButton
              icon={RefreshCw}
              label={scanning ? "Taranıyor…" : rescanLabel}
              variant="secondary"
              className={`h-7 w-7 ${
                scanning
                  ? "ring-2 ring-sky-400/70"
                  : scanNeedsAttention
                    ? "asm-wwid-blink ring-2 ring-amber-400/80"
                    : ""
              }`}
              iconClassName={scanning || loadingList ? "animate-spin" : undefined}
              disabled={scanning || loadingList || !selectedIds.length}
              onClick={() => void loadDisks(true, true)}
            />
            <IconButton
              icon={CheckSquare}
              label="Soldakilerin hepsini seç"
              variant="secondary"
              className="h-7 w-7"
              disabled={wwidGate && matchedWwids === null}
              onClick={selectAllUsableLeft}
            />
            <IconButton
              icon={Eraser}
              label="Seçimi temizle"
              variant="secondary"
              className="h-7 w-7"
              disabled={!picked.size}
              onClick={clearPicked}
            />
            <IconButton
              icon={ArrowRight}
              label="Sağa al"
              variant="secondary"
              className="h-7 w-7"
              disabled={!picked.size}
              onClick={() => moveKeysToSelected([...picked])}
            />
            <IconButton
              icon={ArrowLeft}
              label="Sola al"
              variant="secondary"
              className="h-7 w-7"
              disabled={!picked.size}
              onClick={() => moveKeysToAvailable([...picked])}
            />
            {picked.size > 0 ? (
              <span className="text-[9px] tabular-nums text-[var(--color-muted-foreground)]">{picked.size}</span>
            ) : null}
          </div>

          <div
            ref={rightZoneRef}
            className={`flex min-h-0 flex-col overflow-hidden rounded-lg border border-dashed p-2 ${
              dropTarget === "right"
                ? "border-emerald-400 bg-emerald-500/15"
                : "border-emerald-500/40 bg-emerald-500/5"
            }`}
          >
            <p className="mb-1.5 shrink-0 text-xs font-medium text-emerald-200/90">
              İşlem yapılacak diskler ({selected.length})
            </p>
            <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
              {selected.map((d) => renderCard(d, "right"))}
              {!selected.length ? (
                <p className="text-xs text-[var(--color-muted-foreground)]">Buraya sürükleyin</p>
              ) : null}
            </div>
          </div>
        </div>
      </form>

      <Dialog open={wwidPanelOpen} onOpenChange={setWwidPanelOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Storage WWID listesi</DialogTitle>
          </DialogHeader>
          <p className="mb-2 text-xs text-[var(--color-muted-foreground)]">
            Storage ekibinden gelen WWID listesini yapıştırın. Her değer en az 16 karakter olmalı;
            eşleşme sunucudaki WWID&apos;nin <span className="font-medium">son 16 hanesi</span> ile
            yapılır (yapıştırılanın da son 16 hanesi kullanılır).
          </p>
          <textarea
            className="min-h-[140px] w-full resize-y rounded-md border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2 font-mono text-xs text-[var(--color-foreground)] outline-none focus:ring-1 focus:ring-[var(--color-primary)]"
            placeholder={"…son16haneler\n…veya_daha_uzun_wwid"}
            value={wwidPasteText}
            onChange={(e) => setWwidPasteText(e.target.value)}
            spellCheck={false}
          />
          {unmatchedPaste.length > 0 && matchedWwids ? (
            <div className="mt-2 max-h-24 overflow-y-auto rounded border border-[var(--color-destructive)]/40 bg-[var(--color-destructive)]/5 px-2 py-1 font-mono text-[10px] text-[var(--color-destructive)]">
              Taramada yok: {unmatchedPaste.join(", ")}
            </div>
          ) : null}
          <div className="mt-4 flex justify-end gap-2">
            <Button type="button" variant="secondary" size="sm" onClick={() => setWwidPanelOpen(false)}>
              İptal
            </Button>
            <Button type="button" size="sm" onClick={runWwidCheck}>
              Kontrol et
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {dragUi?.active ? (
        <div
          className="pointer-events-none fixed z-[9999] rounded-md border border-emerald-400 bg-[var(--color-card)] px-3 py-2 text-xs shadow-lg"
          style={{ left: dragUi.x + 12, top: dragUi.y + 12 }}
        >
          {dragUi.keys.length} disk taşınıyor…
        </div>
      ) : null}
    </div>
  );
}
