import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
} from "@/api";
import { IconButton } from "@/components/IconButton";
import { PaginationBar } from "@/components/PaginationBar";
import { buildOpsUrl, SERVER_OPS, ServerOpsMenu, type OpsTarget } from "@/components/ServerOpsMenu";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
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
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useT } from "@/i18n/I18nProvider";
import { getToken } from "@/session";

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

export function ServersPage() {
  const { user } = useOutletContext<OutletCtx>();
  const isAdmin = user.role === "admin";
  const token = getToken()!;
  const t = useT();
  const navigate = useNavigate();

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

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ServerPublic | null>(null);
  const [form, setForm] = useState({ hostname: "", ip: "", password: "" });
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
      const data = await listServers(token, {
        q: q || undefined,
        status,
        page,
        page_size: pageSize,
      });
      setItems(data.items);
      setTotal(data.total);
      setRowSelection({});
    } catch (err) {
      setError(err instanceof Error ? err.message : t("list_failed"));
    } finally {
      setLoading(false);
    }
  }, [token, q, status, page, pageSize, t]);

  useEffect(() => {
    void getServerDefaults(token).then((d) => setAutomationUsername(d.username));
  }, [token]);

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
    setForm({ hostname: server.hostname, ip: server.ip, password: "" });
    setDialogOpen(true);
  }, []);

  const onTest = useCallback(
    async (server: ServerPublic) => {
      setInfo(null);
      setError(null);
      try {
        const result = await testServerConnection(token, server.id);
        setInfo(`${result.hostname}: ${result.last_connection_message}`);
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Test failed");
      }
    },
    [token, load],
  );

  const onDelete = useCallback(
    async (server: ServerPublic) => {
      if (!window.confirm(t("confirm_delete_server", { hostname: server.hostname }))) return;
      try {
        await deleteServer(token, server.id);
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Delete failed");
      }
    },
    [token, load, t],
  );

  const openOpsFor = useCallback((servers: ServerPublic[], x: number, y: number) => {
    if (servers.length === 0) return;
    setCtxMenu({
      open: true,
      x,
      y,
      target: { ids: servers.map((s) => s.id), hostnames: servers.map((s) => s.hostname) },
    });
  }, []);

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
        cell: ({ row }) => (
          <span className="block max-w-[200px] truncate text-xs" title={row.original.os_pretty || ""}>
            {row.original.os_pretty || "—"}
          </span>
        ),
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
        cell: ({ row }) => statusBadge(row.original.status),
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

    if (isAdmin) {
      cols.push({
        id: "actions",
        header: "",
        enableSorting: false,
        cell: ({ row }) => {
          const s = row.original;
          return (
            <div className="flex justify-end gap-1">
              <IconButton icon={Wifi} label={t("test_connection")} onClick={() => void onTest(s)} />
              <IconButton icon={Pencil} label={t("edit")} onClick={() => openEdit(s)} />
              <IconButton
                icon={Trash2}
                label={t("delete")}
                variant="destructive"
                onClick={() => void onDelete(s)}
              />
            </div>
          );
        },
      });
    }
    return cols;
  }, [isAdmin, onTest, openEdit, onDelete, t, navigate]);

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
      const r = await testServerConnectionsBulk(
        token,
        targets.map((s) => s.id),
        {
          onProgress: (p) => {
            setBulkTestDone(p.done);
            setBulkTestTotal(p.total);
            setBulkTestItems(
              p.items.map((it) => ({
                id: it.id,
                hostname: it.hostname || targets.find((s) => s.id === it.id)?.hostname || String(it.id),
                ok: it.ok,
                message: it.message || (it.ok ? "OK" : "Fail"),
              })),
            );
            if (p.current) {
              setBulkTestCurrent(p.current);
            }
          },
        },
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
      const parsed = await parseServerImport(token, file);
      setImportTotal(parsed.total);
      const results: ServerImportRowResult[] = [];
      let ready = 0;
      let unreachable = 0;
      let skipped = 0;
      let created = 0;
      for (let i = 0; i < parsed.rows.length; i += 1) {
        const row = parsed.rows[i];
        setImportCurrent(row.hostname);
        setImportDone(i);
        let item: ServerImportRowResult;
        try {
          item = await importServerRow(token, row);
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
      let result: ServerPublic;
      if (editing) {
        result = await updateServer(token, editing.id, {
          hostname: form.hostname,
          ip: form.ip,
          ...(form.password.trim() ? { password: form.password } : {}),
          test_connection: true,
        });
      } else {
        result = await createServer(token, {
          hostname: form.hostname,
          ip: form.ip,
          password: form.password,
        });
      }
      setDialogOpen(false);
      setInfo(`${result.hostname}: ${result.last_connection_message}`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-[var(--color-border)] bg-[var(--color-card)]/40 px-6 py-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold tracking-tight">{t("servers_title")}</h2>
            <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
              {t("servers_subtitle")}{" "}
              <span className="font-mono text-[var(--color-foreground)]">{automationUsername}</span>
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <IconButton icon={RefreshCw} label={t("refresh")} onClick={() => void load()} />
            {isAdmin ? (
              <>
                <input
                  ref={importInputRef}
                  type="file"
                  accept=".xlsx,.xlsm,.csv,.txt,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
                  className="hidden"
                  onChange={(e) => void onImportFile(e.target.files?.[0] ?? null)}
                />
                <Button
                  type="button"
                  variant="outline"
                  className="gap-2"
                  disabled={importing}
                  title={t("import_servers_help")}
                  onClick={() => importInputRef.current?.click()}
                >
                  <FileSpreadsheet className="h-4 w-4" />
                  {importing ? "…" : t("import_servers")}
                </Button>
                <Button onClick={openCreate} className="gap-2">
                  <Plus className="h-4 w-4" />
                  {t("add_server")}
                </Button>
              </>
            ) : null}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <div className="relative min-w-[240px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-muted-foreground)]" />
            <Input
              className="pl-9"
              placeholder={t("search_placeholder")}
              value={qDraft}
              onChange={(e) => setQDraft(e.target.value)}
            />
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

      {selected.length > 0 ? (
        <div className="flex items-center gap-3 border-b border-[var(--color-border)] bg-[var(--color-primary)]/10 px-6 py-2.5">
          <span className="text-sm font-medium">{t("selected_servers", { n: selected.length })}</span>
          <div className="flex gap-1">
            {isAdmin ? (
              <IconButton
                icon={Wifi}
                label={t("bulk_test")}
                disabled={bulkTesting}
                onClick={() => void onBulkTest()}
              />
            ) : null}
            <Button
              size="sm"
              variant="secondary"
              className="gap-2"
              onClick={(e) => {
                const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                openOpsFor(selected, rect.left, rect.bottom + 4);
              }}
            >
              <Wrench className="h-4 w-4" />
              {t("operations")}
            </Button>
          </div>
        </div>
      ) : null}

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
                      className="cursor-pointer border-t border-[var(--color-border)] hover:bg-[var(--color-accent)]/40"
                      data-state={row.getIsSelected() ? "selected" : undefined}
                      onDoubleClick={() => navigate(`/app/servers/${row.original.id}`)}
                      onContextMenu={(e) => {
                        e.preventDefault();
                        const targets =
                          selected.some((s) => s.id === row.original.id) && selected.length > 0
                            ? selected
                            : [row.original];
                        openOpsFor(targets, e.clientX, e.clientY);
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
            <p className="text-xs text-[var(--color-muted-foreground)]">
              {t("ssh_user_setting")}:{" "}
              <span className="font-mono text-[var(--color-foreground)]">{automationUsername}</span>
            </p>
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
                {t("password")} {editing ? t("password_keep") : ""}
              </label>
              <Input
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                required={!editing}
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
                className="h-full rounded-full bg-[var(--color-primary)] transition-[width] duration-300"
                style={{
                  width: `${bulkTestTotal > 0 ? Math.round((bulkTestDone / bulkTestTotal) * 100) : 0}%`,
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
