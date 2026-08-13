import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate, useOutletContext } from "react-router-dom";
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  RowSelectionState,
  SortingState,
  useReactTable,
} from "@tanstack/react-table";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  CloudDownload,
  FileSpreadsheet,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Wifi,
  Wrench,
} from "lucide-react";
import {
  createServer,
  deleteServer,
  getAdminSettings,
  getServerDefaults,
  importServerRow,
  listServers,
  parseServerImport,
  ServerImportRowResult,
  ServerPublic,
  ServerStatus,
  testServerConnection,
  testServerConnectionsBulk,
  updateServer,
  UserPublic,
} from "@dropt/api";
import { getToken as getAinewToken } from "../../auth/authStore";
import { API_BASE_URL } from "../../config/api";
import { fullOsLabel, shortenOsLabel } from "../../lib/osLabel";
import { OsIcon } from "../../components/OsIcon";
import { IconButton } from "@dropt/components/IconButton";
import { PaginationBar } from "@dropt/components/PaginationBar";
import { buildOpsUrl, SERVER_OPS, ServerOpsMenu, type OpsTarget } from "@dropt/components/ServerOpsMenu";
import { Badge } from "@dropt/components/ui/badge";
import { Button } from "@dropt/components/ui/button";
import { Checkbox } from "@dropt/components/ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@dropt/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@dropt/components/ui/dropdown-menu";
import { Input } from "@dropt/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@dropt/components/ui/select";
import { useT } from "@dropt/i18n/I18nProvider";
import { getStoredUser, getToken } from "@dropt/session";

type OutletCtx = { user: UserPublic; appName: string };

function statusBadge(status: ServerStatus) {
  if (status === "ready") return <Badge variant="success">ready</Badge>;
  if (status === "unreachable") return <Badge variant="danger">unreachable</Badge>;
  if (status === "disabled") return <Badge variant="muted">disabled</Badge>;
  return <Badge variant="warning">unknown</Badge>;
}

function SortableHeader({
  label,
  sorted,
}: {
  label: string;
  sorted: false | "asc" | "desc";
}) {
  const Icon = sorted === "asc" ? ArrowUp : sorted === "desc" ? ArrowDown : ArrowUpDown;
  return (
    <span className="inline-flex items-center gap-1">
      {label}
      <Icon className="h-3.5 w-3.5 opacity-70" />
    </span>
  );
}

type ServersPageProps = {
  /** Level 1 embed: hide Dropt CRUD/import; navigate to /level1/console */
  level1Mode?: boolean;
  /** Ainew Linux → Dropt envanter senkronu (Operasyon Merkezi) */
  onSyncAinewInventory?: () => void;
  syncingAinewInventory?: boolean;
};

export function ServersPage({
  level1Mode = false,
  onSyncAinewInventory,
  syncingAinewInventory = false,
}: ServersPageProps = {}) {
  const outletCtx = useOutletContext<OutletCtx | undefined>();
  const storedRaw = getStoredUser();
  let storedUser: UserPublic | null = null;
  try {
    storedUser = storedRaw ? (JSON.parse(storedRaw) as UserPublic) : null;
  } catch {
    storedUser = null;
  }
  const user =
    outletCtx?.user ||
    storedUser ||
    ({ id: 0, username: "admin", role: "admin" } as UserPublic);
  const isAdmin = user.role === "admin";
  /** Sunucu ekle / Excel import / düzenle — admin (Level 1 Ops Center dahil) */
  const showInventoryCrud = isAdmin;
  const canTestConnection = isAdmin || level1Mode;
  const t = useT();
  const navigate = useNavigate();
  const consoleBase = level1Mode ? "/level1/console" : "/app/servers";

  /** Level 1: JWT cache stale olabilir — her API için canlı oturum al / 401'de yenile. */
  const withAuth = useCallback(
    async <T,>(fn: (token: string) => Promise<T>): Promise<T> => {
      if (level1Mode) {
        const { withDroptToken } = await import("../../pages/level1/Level1Shell");
        return withDroptToken(fn);
      }
      const tok = getToken();
      if (!tok) throw new Error("Oturum gerekli");
      return fn(tok);
    },
    [level1Mode],
  );

  const [items, setItems] = useState<ServerPublic[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);
  const [q, setQ] = useState("");
  const [qDraft, setQDraft] = useState("");
  const [status, setStatus] = useState<ServerStatus | "">("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [sorting, setSorting] = useState<SortingState>([{ id: "hostname", desc: false }]);
  const [automationUsername, setAutomationUsername] = useState("root");
  const [automationPasswordSet, setAutomationPasswordSet] = useState(true);
  const automationOpsEnabled = automationPasswordSet;
  const AUTOMATION_CRED_HINT =
    "Önce Level 1 → Ayarlar’da otomasyon kullanıcı şifresini kaydedin (vCenter / Linux envanter kaydı yeterli değildir).";

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ServerPublic | null>(null);
  const [form, setForm] = useState({
    hostname: "",
    ip: "",
    password: "",
  });
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [importDone, setImportDone] = useState(0);
  const [importTotal, setImportTotal] = useState(0);
  const [importCurrent, setImportCurrent] = useState("");
  const [importItems, setImportItems] = useState<ServerImportRowResult[]>([]);
  const [importFinished, setImportFinished] = useState(false);
  const importInputRef = useRef<HTMLInputElement>(null);

  type BulkTestItem = {
    id: number;
    hostname: string;
    ok: boolean;
    message: string;
  };
  const [bulkTestOpen, setBulkTestOpen] = useState(false);
  const [bulkTestMinimized, setBulkTestMinimized] = useState(false);
  const [bulkTesting, setBulkTesting] = useState(false);
  const [bulkTestDone, setBulkTestDone] = useState(0);
  const [bulkTestTotal, setBulkTestTotal] = useState(0);
  const [bulkTestCurrent, setBulkTestCurrent] = useState("");
  const [bulkTestItems, setBulkTestItems] = useState<BulkTestItem[]>([]);
  const [bulkTestFinished, setBulkTestFinished] = useState(false);

  const [ctxMenu, setCtxMenu] = useState<{ open: boolean; x: number; y: number; target: OpsTarget | null }>({
    open: false,
    x: 0,
    y: 0,
    target: null,
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await withAuth((token) =>
        listServers(token, {
          q: q || undefined,
          status,
          page,
          page_size: pageSize,
        }),
      );
      setItems(data.items);
      setTotal(data.total);
      setRowSelection({});
    } catch (err) {
      setError(err instanceof Error ? err.message : t("list_failed"));
    } finally {
      setLoading(false);
    }
  }, [withAuth, q, status, page, pageSize, t]);

  useEffect(() => {
    void withAuth((token) => getServerDefaults(token)).then((d) => setAutomationUsername(d.username));
    void withAuth((token) => getAdminSettings(token))
      .then((s) => setAutomationPasswordSet(Boolean(s.automation_password_set)))
      .catch(() => setAutomationPasswordSet(false));
  }, [withAuth]);

  useEffect(() => {
    void load();
  }, [load]);

  // Live search: her karakterde (kısa debounce)
  useEffect(() => {
    const handle = window.setTimeout(() => {
      setPage(1);
      setQ(qDraft.trim());
    }, 250);
    return () => window.clearTimeout(handle);
  }, [qDraft]);

  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  function openCreate() {
    setEditing(null);
    setForm({ hostname: "", ip: "", password: "" });
    setDialogOpen(true);
  }

  const openEdit = useCallback((server: ServerPublic) => {
    setEditing(server);
    setForm({
      hostname: server.hostname,
      ip: server.ip,
      password: "",
    });
    setDialogOpen(true);
  }, []);

  async function ainewInventoryFetch(path: string, init?: RequestInit) {
    const ainewTok = getAinewToken() || "";
    const res = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        ...(init?.headers || {}),
        Authorization: ainewTok ? `Bearer ${ainewTok}` : "",
      },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(
        typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail || err) || res.statusText,
      );
    }
    if (res.status === 204) return null;
    return res.json();
  }

  const onTest = useCallback(
    async (server: ServerPublic) => {
      setInfo(null);
      setError(null);
      if (!automationOpsEnabled) {
        setError(AUTOMATION_CRED_HINT);
        return;
      }
      try {
        const result = await withAuth((tok) => testServerConnection(tok, server.id));
        setInfo(`${result.hostname}: ${result.last_connection_message}`);
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Test failed");
      }
    },
    [withAuth, load, automationOpsEnabled],
  );

  const onDelete = useCallback(
    async (server: ServerPublic) => {
      if (!window.confirm(t("confirm_delete_server", { hostname: server.hostname }))) return;
      try {
        if (level1Mode) {
          await withAuth(async (tok) =>
            ainewInventoryFetch("/level1/inventory/servers/delete", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                dropt_token: tok,
                ip: server.ip,
                dropt_server_id: server.id,
              }),
            }),
          );
        } else {
          await withAuth((tok) => deleteServer(tok, server.id));
        }
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Delete failed");
      }
    },
    [withAuth, load, t, level1Mode],
  );

  const openOpsFor = useCallback((servers: ServerPublic[], x: number, y: number) => {
    if (servers.length === 0) return;
    if (!automationOpsEnabled) {
      setError(AUTOMATION_CRED_HINT);
      return;
    }
    setCtxMenu({
      open: true,
      x,
      y,
      target: { ids: servers.map((s) => s.id), hostnames: servers.map((s) => s.hostname) },
    });
  }, [automationOpsEnabled]);

  const columns = useMemo<ColumnDef<ServerPublic>[]>(() => {
    const cols: ColumnDef<ServerPublic>[] = [
      {
        id: "select",
        header: ({ table }) => (
          <Checkbox
            checked={
              table.getIsAllPageRowsSelected()
                ? true
                : table.getIsSomePageRowsSelected()
                  ? "indeterminate"
                  : false
            }
            onCheckedChange={(v) => table.toggleAllPageRowsSelected(!!v)}
          />
        ),
        cell: ({ row }) => (
          <Checkbox checked={row.getIsSelected()} onCheckedChange={(v) => row.toggleSelected(!!v)} />
        ),
        enableSorting: false,
        size: 36,
      },
      {
        accessorKey: "hostname",
        header: ({ column }) => (
          <SortableHeader label={t("hostname")} sorted={column.getIsSorted()} />
        ),
        cell: ({ row }) => <span className="font-mono text-sm">{row.original.hostname}</span>,
      },
      {
        accessorKey: "ip",
        header: ({ column }) => <SortableHeader label={t("ip")} sorted={column.getIsSorted()} />,
        sortingFn: "alphanumeric",
        cell: ({ row }) => (
          <span className="font-mono text-sm text-[var(--color-muted-foreground)]">{row.original.ip}</span>
        ),
      },
      {
        accessorKey: "os_pretty",
        header: ({ column }) => (
          <SortableHeader label={t("col_os")} sorted={column.getIsSorted()} />
        ),
        cell: ({ row }) => {
          const pretty = row.original.os_pretty || "";
          const short = shortenOsLabel({ os_pretty: pretty, os_version: pretty });
          const full = fullOsLabel({ os_pretty: pretty, os_version: pretty }) || pretty;
          return (
            <div className="flex max-w-[220px] items-center gap-2">
              <OsIcon os={pretty || "linux"} size={18} />
              <span className="truncate text-xs" title={full || undefined}>
                {short !== "—" ? short : "—"}
              </span>
            </div>
          );
        },
      },
      {
        accessorKey: "machine_type",
        header: ({ column }) => (
          <SortableHeader label={t("col_machine")} sorted={column.getIsSorted()} />
        ),
        cell: ({ row }) => {
          const mt = row.original.machine_type;
          if (mt === "physical") return <Badge variant="muted">{t("console_physical")}</Badge>;
          if (mt === "virtual") {
            const virt = row.original.virtualization;
            const label = virt ? `${t("console_virtual")} · ${virt}` : t("console_virtual");
            return (
              <Badge variant="success" title={label}>
                {label}
              </Badge>
            );
          }
          return <span className="text-xs text-[var(--color-muted-foreground)]">—</span>;
        },
      },
      {
        accessorKey: "username",
        header: t("user"),
        enableSorting: false,
        cell: ({ row }) => <span className="font-mono text-xs">{row.original.username}</span>,
      },
      {
        accessorKey: "status",
        header: t("status"),
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex flex-wrap items-center gap-1">
            {statusBadge(row.original.status)}
          </div>
        ),
      },
      {
        id: "row_ops",
        header: "",
        enableSorting: false,
        cell: ({ row }) => (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="icon" variant="ghost" aria-label={t("operations")}>
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>{t("operations")}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {SERVER_OPS.map((op) => {
                const Icon = op.icon;
                if (op.children?.length) {
                  return (
                    <DropdownMenuSub key={op.path}>
                      <DropdownMenuSubTrigger>
                        <Icon className="h-4 w-4" />
                        {t(op.key)}
                      </DropdownMenuSubTrigger>
                      <DropdownMenuSubContent>
                        {op.children.map((child) => (
                          <DropdownMenuItem
                            key={child.path}
                            onClick={() =>
                              navigate(
                                buildOpsUrl(child.path, {
                                  ids: [row.original.id],
                                  hostnames: [row.original.hostname],
                                }),
                              )
                            }
                          >
                            {t(child.key)}
                          </DropdownMenuItem>
                        ))}
                      </DropdownMenuSubContent>
                    </DropdownMenuSub>
                  );
                }
                return (
                  <DropdownMenuItem
                    key={op.path}
                    onClick={() =>
                      navigate(
                        buildOpsUrl(op.path, {
                          ids: [row.original.id],
                          hostnames: [row.original.hostname],
                        }),
                      )
                    }
                  >
                    <Icon className="h-4 w-4" />
                    {t(op.key)}
                  </DropdownMenuItem>
                );
              })}
            </DropdownMenuContent>
          </DropdownMenu>
        ),
      },
    ];

    if (canTestConnection || showInventoryCrud) {
      cols.push({
        id: "actions",
        header: "",
        enableSorting: false,
        cell: ({ row }) => {
          const s = row.original;
          return (
            <div className="flex justify-end gap-1">
              {canTestConnection ? (
                <IconButton
                  icon={Wifi}
                  label={t("test_connection")}
                  disabled={!automationOpsEnabled}
                  onClick={() => void onTest(s)}
                />
              ) : null}
              {showInventoryCrud ? (
                <>
                  <IconButton icon={Pencil} label={t("edit")} onClick={() => openEdit(s)} />
                  <IconButton
                    icon={Trash2}
                    label={t("delete")}
                    variant="destructive"
                    onClick={() => void onDelete(s)}
                  />
                </>
              ) : null}
            </div>
          );
        },
      });
    }
    return cols;
  }, [canTestConnection, showInventoryCrud, onTest, openEdit, onDelete, t, navigate, automationOpsEnabled]);

  const table = useReactTable({
    data: items,
    columns,
    state: { rowSelection, sorting },
    onRowSelectionChange: setRowSelection,
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: (row) => String(row.id),
    enableRowSelection: true,
  });

  const selected = table.getSelectedRowModel().rows.map((r) => r.original);

  function minimizeBulkTest() {
    setBulkTestOpen(false);
    setBulkTestMinimized(true);
  }

  function expandBulkTest() {
    setBulkTestMinimized(false);
    setBulkTestOpen(true);
  }

  function dismissBulkTest() {
    if (bulkTesting) return;
    setBulkTestOpen(false);
    setBulkTestMinimized(false);
    setBulkTestFinished(false);
    setBulkTestItems([]);
    setBulkTestCurrent("");
    setBulkTestDone(0);
    setBulkTestTotal(0);
  }

  async function onBulkTest() {
    if (selected.length === 0 || bulkTesting) return;
    if (!automationOpsEnabled) {
      setError(AUTOMATION_CRED_HINT);
      return;
    }
    const targets = [...selected];
    setInfo(null);
    setError(null);
    setBulkTestMinimized(false);
    setBulkTestOpen(true);
    setBulkTesting(true);
    setBulkTestFinished(false);
    setBulkTestDone(0);
    setBulkTestTotal(targets.length);
    setBulkTestCurrent("");
    setBulkTestItems([]);
    try {
      setBulkTestCurrent(t("bulk_test_parallel", { total: targets.length }));
      const r = await withAuth((tok) =>
        testServerConnectionsBulk(
          tok,
          targets.map((s) => s.id),
        ),
      );
      const results: BulkTestItem[] = r.items.map((it) => ({
        id: it.id,
        hostname: it.hostname || targets.find((s) => s.id === it.id)?.hostname || String(it.id),
        ok: it.ok,
        message: it.message || (it.ok ? "OK" : "Fail"),
      }));
      setBulkTestItems(results);
      setBulkTestDone(r.total);
      setBulkTestCurrent("");
      setBulkTestFinished(true);
      setInfo(t("bulk_test_summary", { ok: r.ok, total: r.total }));
      await load();
    } catch (err) {
      setBulkTestFinished(true);
      setError(err instanceof Error ? err.message : "Toplu bağlantı testi başarısız");
    } finally {
      setBulkTesting(false);
      setBulkTestCurrent("");
    }
  }

  async function onImportFile(file: File | null) {
    if (!file) return;
    setImporting(true);
    setImportOpen(true);
    setImportFinished(false);
    setImportDone(0);
    setImportTotal(0);
    setImportCurrent("");
    setImportItems([]);
    setError(null);
    setInfo(null);
    try {
      let rows: Array<{ hostname: string; ip: string }> = [];
      if (level1Mode) {
        const fd = new FormData();
        fd.append("file", file);
        const parsed = await ainewInventoryFetch("/level1/inventory/import/parse", {
          method: "POST",
          body: fd,
        });
        rows = parsed.rows || [];
      } else {
        const parsed = await withAuth((tok) => parseServerImport(tok, file));
        rows = parsed.rows;
      }
      setImportTotal(rows.length);
      const results: ServerImportRowResult[] = [];
      let ready = 0;
      let unreachable = 0;
      let skipped = 0;
      let created = 0;
      for (let i = 0; i < rows.length; i += 1) {
        const row = rows[i];
        setImportCurrent(row.hostname);
        setImportDone(i);
        let item: ServerImportRowResult;
        try {
          if (level1Mode) {
            const r = await withAuth(async (tok) =>
              ainewInventoryFetch("/level1/inventory/import/row", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  dropt_token: tok,
                  hostname: row.hostname,
                  ip: row.ip,
                  os_type: "linux",
                }),
              }),
            );
            item = {
              hostname: r.hostname,
              ip: r.ip,
              status: r.status,
              message: r.message,
              server_id: r.server_id ?? r.dropt_server_id ?? null,
            };
          } else {
            item = await withAuth((tok) => importServerRow(tok, row));
          }
        } catch (err) {
          item = {
            hostname: row.hostname,
            ip: row.ip,
            status: "error",
            message: err instanceof Error ? err.message : "Hata",
            server_id: null,
          };
        }
        results.push(item);
        setImportItems([...results]);
        setImportDone(i + 1);
        if (item.status === "ready") {
          ready += 1;
          created += 1;
        } else if (item.status === "unreachable") {
          unreachable += 1;
          created += 1;
        } else if (item.status === "skipped") {
          skipped += 1;
        } else if (item.server_id) {
          unreachable += 1;
          created += 1;
        }
      }
      setImportFinished(true);
      setImportCurrent("");
      setInfo(
        t("import_servers_result", {
          created,
          ready,
          unreachable,
          skipped,
        }),
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
      setImportOpen(false);
    } finally {
      setImporting(false);
      if (importInputRef.current) importInputRef.current.value = "";
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      if (level1Mode) {
        if (editing) {
          const result = await withAuth(async (tok) =>
            ainewInventoryFetch("/level1/inventory/servers/update", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                dropt_token: tok,
                current_ip: editing.ip,
                hostname: form.hostname,
                ip: form.ip,
                dropt_server_id: editing.id,
              }),
            }),
          );
          setDialogOpen(false);
          setInfo(result.message || `${form.hostname} güncellendi`);
        } else {
          const result = await withAuth(async (tok) => {
            const body: Record<string, unknown> = {
              dropt_token: tok,
              hostname: form.hostname,
              ip: form.ip,
              os_type: "linux",
            };
            if (form.password.trim()) {
              body.ssh_password = form.password.trim();
            }
            return ainewInventoryFetch("/level1/inventory/servers", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body),
            });
          });
          setDialogOpen(false);
          setInfo(result.message || `${result.hostname} eklendi`);
        }
        await load();
      } else {
        let result: ServerPublic;
        if (editing) {
          result = await withAuth((tok) =>
            updateServer(tok, editing.id, {
              hostname: form.hostname,
              ip: form.ip,
              ...(form.password.trim() ? { password: form.password } : {}),
              test_connection: true,
            }),
          );
        } else {
          result = await withAuth((tok) =>
            createServer(tok, {
              hostname: form.hostname,
              ip: form.ip,
              password: form.password,
            }),
          );
        }
        setDialogOpen(false);
        setInfo(`${result.hostname}: ${result.last_connection_message}`);
        await load();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  const [headerSlot, setHeaderSlot] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (!level1Mode) {
      setHeaderSlot(null);
      return;
    }
    const el = document.getElementById("level1-ops-header-slot");
    setHeaderSlot(el);
  }, [level1Mode, automationUsername, onSyncAinewInventory, syncingAinewInventory]);

  return (
    <div className="flex h-full flex-col">
      {level1Mode && !automationOpsEnabled ? (
        <div
          className="border-b px-4 py-2 text-xs sm:text-sm"
          style={{
            borderColor: "var(--color-border)",
            background: "rgba(234, 179, 8, 0.08)",
            color: "var(--text-secondary)",
          }}
        >
          {AUTOMATION_CRED_HINT}
        </div>
      ) : null}
      {level1Mode && headerSlot
        ? createPortal(
            <>
              <span className="shrink-0 opacity-40" aria-hidden>
                ·
              </span>
              <span className="shrink-0 text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                {t("servers_title")}
              </span>
              <span className="min-w-0 truncate text-xs sm:text-sm" style={{ color: "var(--text-muted)" }}>
                {t("servers_subtitle")}{" "}
                <span className="font-mono" style={{ color: "var(--text-secondary)" }}>
                  {automationUsername}
                </span>
              </span>
              <div className="ml-auto shrink-0 flex items-center gap-1">
                {onSyncAinewInventory ? (
                  <IconButton
                    icon={CloudDownload}
                    label="Envanteri senkronize et"
                    onClick={() => {
                      if (!automationOpsEnabled) {
                        setError(AUTOMATION_CRED_HINT);
                        return;
                      }
                      onSyncAinewInventory();
                    }}
                    disabled={syncingAinewInventory || !automationOpsEnabled}
                    iconClassName={syncingAinewInventory ? "animate-spin" : undefined}
                  />
                ) : null}
                <IconButton icon={RefreshCw} label={t("refresh")} onClick={() => void load()} />
              </div>
            </>,
            headerSlot,
          )
        : null}

      <div className="border-b border-[var(--color-border)] bg-[var(--color-card)]/40 px-6 py-3">
        {!level1Mode ? (
          <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold tracking-tight">{t("servers_title")}</h2>
              <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
                {t("servers_subtitle")}{" "}
                <span className="font-mono text-[var(--color-foreground)]">{automationUsername}</span>
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <IconButton icon={RefreshCw} label={t("refresh")} onClick={() => void load()} />
            </div>
          </div>
        ) : null}

        {showInventoryCrud ? (
          <input
            ref={importInputRef}
            type="file"
            accept=".xlsx,.xlsm,.csv,.txt,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
            className="hidden"
            onChange={(e) => void onImportFile(e.target.files?.[0] ?? null)}
          />
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-[200px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-muted-foreground)]" />
            <Input
              className="pl-9"
              placeholder={t("search_placeholder")}
              value={qDraft}
              onChange={(e) => setQDraft(e.target.value)}
            />
          </div>

          {/* Search ↔ durum: Excel import + Sunucu ekle */}
          {showInventoryCrud ? (
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-9 gap-2"
                disabled={importing}
                title={t("import_servers_help")}
                onClick={() => importInputRef.current?.click()}
              >
                <FileSpreadsheet className="h-4 w-4" />
                {importing ? "…" : t("import_servers")}
              </Button>
              <Button type="button" size="sm" className="h-9 gap-2" onClick={openCreate}>
                <Plus className="h-4 w-4" />
                {t("add_server")}
              </Button>
            </div>
          ) : null}

          {/* Selection actions — between search/actions and status (fixed slot, no list jump) */}
          <div
            className="flex min-h-9 min-w-[12rem] flex-wrap items-center gap-2 rounded-lg border px-2.5 py-1"
            style={{
              borderColor:
                selected.length > 0
                  ? "color-mix(in srgb, var(--color-primary) 45%, var(--color-border))"
                  : "transparent",
              background:
                selected.length > 0
                  ? "color-mix(in srgb, var(--color-primary) 12%, transparent)"
                  : "transparent",
            }}
            aria-live="polite"
          >
            {selected.length > 0 ? (
              <>
                <span className="whitespace-nowrap text-sm font-medium">
                  {t("selected_servers", { n: selected.length })}
                </span>
                {canTestConnection ? (
                  <IconButton
                    icon={Wifi}
                    label={t("bulk_test")}
                    disabled={bulkTesting || !automationOpsEnabled}
                    onClick={() => void onBulkTest()}
                  />
                ) : null}
                <Button
                  size="sm"
                  variant="secondary"
                  className="h-8 gap-2"
                  disabled={!automationOpsEnabled}
                  onClick={(e) => {
                    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                    openOpsFor(selected, rect.left, rect.bottom + 4);
                  }}
                >
                  <Wrench className="h-4 w-4" />
                  {t("operations")}
                </Button>
              </>
            ) : (
              <span className="text-xs text-[var(--color-muted-foreground)] opacity-0 select-none">
                —
              </span>
            )}
          </div>

          <Select
            value={status || "all"}
            onValueChange={(v) => {
              setPage(1);
              setStatus(v === "all" ? "" : (v as ServerStatus));
            }}
          >
            <SelectTrigger className="w-[160px]">
              <SelectValue placeholder={t("status")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("all_statuses")}</SelectItem>
              <SelectItem value="ready">ready</SelectItem>
              <SelectItem value="unreachable">unreachable</SelectItem>
              <SelectItem value="unknown">unknown</SelectItem>
              <SelectItem value="disabled">disabled</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="flex-1 px-6 py-4">
        {error ? <p className="mb-3 text-sm text-[var(--color-destructive)]">{error}</p> : null}
        {info ? <p className="mb-3 text-sm text-emerald-300">{info}</p> : null}

        <div className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-card)]/80">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-[var(--color-border)] bg-[var(--color-muted)]/40 text-[var(--color-muted-foreground)]">
                {table.getHeaderGroups().map((hg) => (
                  <tr key={hg.id}>
                    {hg.headers.map((h) => (
                      <th
                        key={h.id}
                        className={`px-3 py-3 text-left font-medium ${
                          h.column.getCanSort()
                            ? "cursor-pointer select-none hover:text-[var(--color-foreground)]"
                            : ""
                        }`}
                        onClick={h.column.getToggleSortingHandler()}
                      >
                        {h.isPlaceholder ? null : flexRender(h.column.columnDef.header, h.getContext())}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={columns.length} className="px-3 py-10 text-center text-[var(--color-muted-foreground)]">
                      {t("loading")}
                    </td>
                  </tr>
                ) : items.length === 0 ? (
                  <tr>
                    <td colSpan={columns.length} className="px-3 py-10 text-center text-[var(--color-muted-foreground)]">
                      {t("no_records")}
                    </td>
                  </tr>
                ) : (
                  table.getRowModel().rows.map((row) => (
                    <tr
                      key={row.id}
                      className="ops-row cursor-pointer border-t border-[var(--color-border)] data-[state=selected]:bg-[var(--color-primary)]/25"
                      data-state={row.getIsSelected() ? "selected" : undefined}
                      onClick={(e) => {
                        const el = e.target as HTMLElement;
                        // Checkbox / action buttons handle their own clicks
                        if (el.closest('button, a, input, [role="checkbox"], [role="menuitem"]')) return;
                        if (e.shiftKey || e.metaKey || e.ctrlKey) {
                          row.toggleSelected();
                        } else {
                          // Single select on click; keep multi via checkbox / ctrl
                          table.toggleAllRowsSelected(false);
                          row.toggleSelected(true);
                        }
                      }}
                      onDoubleClick={() => {
                        if (row.original.status === "unreachable") {
                          window.alert(
                            "Sunucu unreachable — otomasyon SSH bağlantısı yok. Önce «Bağlantıyı test et» ile doğrulayın.",
                          );
                          return;
                        }
                        navigate(`${consoleBase}/${row.original.id}`);
                      }}
                      onContextMenu={(e) => {
                        e.preventDefault();
                        const inMulti =
                          selected.some((s) => s.id === row.original.id) && selected.length > 0;
                        if (!inMulti) {
                          table.toggleAllRowsSelected(false);
                          row.toggleSelected(true);
                          openOpsFor([row.original], e.clientX, e.clientY);
                          return;
                        }
                        openOpsFor(selected, e.clientX, e.clientY);
                      }}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id} className="px-3 py-2.5 align-middle">
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          <PaginationBar
            page={page}
            pageCount={pageCount}
            total={total}
            disabled={loading}
            onPageChange={setPage}
          />
        </div>
      </div>

      <ServerOpsMenu
        open={ctxMenu.open}
        x={ctxMenu.x}
        y={ctxMenu.y}
        target={ctxMenu.target}
        onClose={() => setCtxMenu((m) => ({ ...m, open: false }))}
      />

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing ? t("edit_server") : t("new_server")}</DialogTitle>
          </DialogHeader>
          <form onSubmit={onSubmit} className="space-y-3">
            {level1Mode ? (
              <p className="text-xs text-[var(--color-muted-foreground)] leading-relaxed">
                Kayıt ainew envantere yazılır. Fiziksel/sanal tip, SSH sonrası otomatik tespit edilir
                (Ops: Level 1 otomasyon user —{" "}
                <span className="font-mono text-[var(--color-foreground)]">{automationUsername}</span>
                ; ainew yönetim: Global Credential). Aşağıdaki parola opsiyonel ainew SSH override.
              </p>
            ) : (
              <p className="text-xs text-[var(--color-muted-foreground)]">
                {t("ssh_user_setting")}:{" "}
                <span className="font-mono text-[var(--color-foreground)]">{automationUsername}</span>
              </p>
            )}
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">{t("hostname")}</label>
              <Input
                value={form.hostname}
                onChange={(e) => setForm({ ...form, hostname: e.target.value })}
                required
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">{t("ip")}</label>
              <Input
                className="font-mono"
                value={form.ip}
                onChange={(e) => setForm({ ...form, ip: e.target.value })}
                required
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                {level1Mode
                  ? editing
                    ? "Ainew SSH parola (opsiyonel)"
                    : "Ainew SSH parola (opsiyonel — boşsa global credential)"
                  : `${t("password")} ${editing ? t("password_keep") : ""}`}
              </label>
              <Input
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                required={!level1Mode && !editing}
                autoComplete="new-password"
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
                {t("cancel")}
              </Button>
              <Button type="submit" disabled={saving}>
                {saving ? t("saving") : t("save")}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={importOpen}
        onOpenChange={(open) => {
          if (!importing) setImportOpen(open);
        }}
      >
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {importFinished ? t("import_done_title") : t("import_servers")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-[var(--color-muted-foreground)]">
              {t("import_progress", { done: importDone, total: importTotal || "…" })}
            </p>
            {importCurrent ? (
              <p className="font-mono text-xs text-[var(--color-foreground)]">
                {t("import_progress_current", { hostname: importCurrent })}
              </p>
            ) : null}
            <div className="h-2 overflow-hidden rounded-full bg-[var(--color-muted)]">
              <div
                className="h-full rounded-full bg-[var(--color-primary)] transition-[width] duration-300"
                style={{
                  width: `${importTotal > 0 ? Math.round((importDone / importTotal) * 100) : 0}%`,
                }}
              />
            </div>
            {importItems.length > 0 ? (
              <div className="max-h-56 overflow-auto rounded-md border border-[var(--color-border)]">
                <table className="w-full text-xs">
                  <tbody>
                    {importItems.map((item) => (
                      <tr key={`${item.hostname}-${item.ip}`} className="border-t border-[var(--color-border)]">
                        <td className="px-2 py-1.5 font-mono">{item.hostname}</td>
                        <td className="px-2 py-1.5">
                          <Badge
                            variant={
                              item.status === "ready"
                                ? "success"
                                : item.status === "skipped"
                                  ? "muted"
                                  : "danger"
                            }
                          >
                            {item.status === "ready"
                              ? t("import_status_ready")
                              : item.status === "skipped"
                                ? t("import_status_skipped")
                                : item.status === "unreachable"
                                  ? t("import_status_unreachable")
                                  : t("import_status_error")}
                          </Badge>
                        </td>
                        <td className="max-w-[180px] truncate px-2 py-1.5 text-[var(--color-muted-foreground)]" title={item.message}>
                          {item.message}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            {importFinished ? (
              <>
                {importItems.some((i) => i.status === "unreachable" || i.status === "error") ? (
                  <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
                    <p className="font-medium text-amber-100">{t("import_failed_list")}</p>
                    <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-amber-50/90">
                      {importItems
                        .filter((i) => i.status === "unreachable" || i.status === "error")
                        .map((i) => (
                          <li key={`fail-${i.hostname}`}>
                            <span className="font-mono">{i.hostname}</span>
                            {i.message ? ` — ${i.message}` : ""}
                          </li>
                        ))}
                    </ul>
                  </div>
                ) : null}
                <div className="flex justify-end">
                  <Button type="button" onClick={() => setImportOpen(false)}>
                    {t("import_close")}
                  </Button>
                </div>
              </>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={bulkTestOpen}
        onOpenChange={(open) => {
          if (!open) {
            if (bulkTesting || bulkTestFinished) {
              minimizeBulkTest();
              return;
            }
            setBulkTestOpen(false);
            return;
          }
          setBulkTestOpen(true);
          setBulkTestMinimized(false);
        }}
      >
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {bulkTestFinished ? t("bulk_test_done_title") : t("bulk_test")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-[var(--color-muted-foreground)]">
              {t("bulk_test_progress", { done: bulkTestDone, total: bulkTestTotal || "…" })}
            </p>
            {bulkTestCurrent ? (
              <p className="font-mono text-xs text-[var(--color-foreground)]">
                {t("bulk_test_current", { hostname: bulkTestCurrent })}
              </p>
            ) : null}
            <div className="h-2 overflow-hidden rounded-full bg-[var(--color-muted)]">
              <div
                className={`h-full rounded-full bg-[var(--color-primary)] transition-[width] duration-300 ${
                  bulkTesting && !bulkTestFinished && bulkTestDone === 0 ? "w-1/3 animate-pulse" : ""
                }`}
                style={{
                  width:
                    bulkTesting && !bulkTestFinished && bulkTestDone === 0
                      ? undefined
                      : `${bulkTestTotal > 0 ? Math.round((bulkTestDone / bulkTestTotal) * 100) : 0}%`,
                }}
              />
            </div>
            {bulkTestItems.length > 0 ? (
              <div className="max-h-56 overflow-auto rounded-md border border-[var(--color-border)]">
                <table className="w-full text-xs">
                  <tbody>
                    {bulkTestItems.map((item) => (
                      <tr key={item.id} className="border-t border-[var(--color-border)]">
                        <td className="px-2 py-1.5 font-mono">{item.hostname}</td>
                        <td className="px-2 py-1.5">
                          <Badge variant={item.ok ? "success" : "danger"}>
                            {item.ok ? t("bulk_test_ok") : t("bulk_test_fail")}
                          </Badge>
                        </td>
                        <td
                          className="max-w-[180px] truncate px-2 py-1.5 text-[var(--color-muted-foreground)]"
                          title={item.message}
                        >
                          {item.message}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            <div className="flex justify-end gap-2">
              {bulkTesting ? (
                <Button type="button" variant="secondary" onClick={minimizeBulkTest}>
                  {t("bulk_test_background")}
                </Button>
              ) : null}
              {bulkTestFinished ? (
                <Button type="button" onClick={dismissBulkTest}>
                  {t("import_close")}
                </Button>
              ) : null}
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {bulkTestMinimized && (bulkTesting || bulkTestFinished) ? (
        <div className="fixed bottom-4 right-4 z-50 w-[min(360px,calc(100vw-2rem))] rounded-xl border border-[var(--color-border)] bg-[var(--color-card)]/95 p-3 shadow-lg backdrop-blur">
          <button
            type="button"
            className="w-full text-left"
            onClick={expandBulkTest}
          >
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium">
                {bulkTestFinished
                  ? t("bulk_test_done_title")
                  : t("bulk_test_chip_running", {
                      done: bulkTestDone,
                      total: bulkTestTotal || "…",
                    })}
              </p>
              <span className="text-xs text-[var(--color-primary)]">{t("bulk_test_show")}</span>
            </div>
            {!bulkTestFinished && bulkTestCurrent ? (
              <p className="mt-1 truncate font-mono text-xs text-[var(--color-muted-foreground)]">
                {bulkTestCurrent}
              </p>
            ) : null}
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[var(--color-muted)]">
              <div
                className="h-full rounded-full bg-[var(--color-primary)] transition-[width] duration-300"
                style={{
                  width: `${bulkTestTotal > 0 ? Math.round((bulkTestDone / bulkTestTotal) * 100) : 0}%`,
                }}
              />
            </div>
          </button>
          {bulkTestFinished ? (
            <div className="mt-2 flex justify-end">
              <Button type="button" size="sm" variant="secondary" onClick={dismissBulkTest}>
                {t("import_close")}
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
