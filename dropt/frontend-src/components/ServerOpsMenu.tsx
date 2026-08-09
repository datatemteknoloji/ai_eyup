import {
  ChevronRight,
  Database,
  FileArchive,
  FolderCog,
  HardDrive,
  KeyRound,
  Layers,
  Mail,
  Network,
  Package,
  Power,
  Scale,
  SlidersHorizontal,
  Terminal,
  Users,
  Cog,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { useT } from "@/i18n/I18nProvider";
import type { TranslationKey } from "@/i18n/messages";
import { cn } from "@/lib/utils";

export type OpsTarget = { ids: number[]; hostnames: string[] };

export type OpsChild = {
  key: TranslationKey;
  path: string;
};

export type OpsItem = {
  key: TranslationKey;
  path: string;
  icon: LucideIcon;
  /** Varsa sağ tık / ⋮ menüde yan alt menü; console parent → choice. */
  children?: OpsChild[];
};

const OPS: OpsItem[] = [
  { key: "ops_terminal", path: "/app/terminal", icon: Terminal },
  { key: "ops_local_users", path: "/app/local-users", icon: Users },
  { key: "ops_hostname", path: "/app/hostname", icon: Network },
  { key: "ops_reboot", path: "/app/reboot", icon: Power },
  { key: "ops_services", path: "/app/services", icon: Cog },
  { key: "ops_sudo", path: "/app/sudoers", icon: KeyRound },
  {
    key: "ops_filesystem",
    path: "/app/filesystem",
    icon: HardDrive,
    children: [
      { key: "fs_extend", path: "/app/filesystem?mode=extend" },
      { key: "fs_create", path: "/app/filesystem?mode=create" },
      { key: "fs_organize", path: "/app/filesystem?mode=organize" },
    ],
  },
  { key: "ops_packages", path: "/app/packages", icon: Package },
  { key: "ops_path_perms", path: "/app/path-perms", icon: FolderCog },
  { key: "ops_logs", path: "/app/logs", icon: FileArchive },
  { key: "ops_limits", path: "/app/limits", icon: Scale },
  { key: "ops_sysctl", path: "/app/sysctl", icon: SlidersHorizontal },
  {
    key: "ops_network",
    path: "/app/network",
    icon: Layers,
    children: [
      { key: "network_add_network", path: "/app/network?tab=network" },
      { key: "network_add_vlan", path: "/app/network?tab=vlan" },
      { key: "network_ip_change", path: "/app/network?tab=ipchange" },
    ],
  },
  { key: "ops_asm", path: "/app/asm", icon: Database },
  { key: "ops_mail_config", path: "/app/mail-config", icon: Mail },
];

/** Single-host-only ops — hidden when multiple servers selected. */
const MULTI_FORBIDDEN = new Set<TranslationKey>([
  "ops_terminal",
  "ops_hostname",
  "ops_reboot",
  "ops_services",
  "ops_sudo",
  "ops_filesystem",
  "ops_path_perms",
  "ops_sysctl",
  "ops_network",
]);

/** ASM supports single node or 2-node cluster only. */
const ASM_MAX_NODES = 2;

export function opsForTarget(target: OpsTarget): OpsItem[] {
  const n = target.ids.length;
  if (n <= 1) return OPS;
  return OPS.filter((op) => {
    if (op.key === "ops_asm") return n <= ASM_MAX_NODES;
    return !MULTI_FORBIDDEN.has(op.key);
  });
}

export function buildOpsUrl(path: string, target: OpsTarget): string {
  const qIndex = path.indexOf("?");
  const base = qIndex >= 0 ? path.slice(0, qIndex) : path;
  const existing = qIndex >= 0 ? path.slice(qIndex + 1) : "";
  const qs = new URLSearchParams(existing);
  qs.set("serverId", String(target.ids[0]));
  if (target.ids.length > 1) qs.set("serverIds", target.ids.join(","));
  return `${base}?${qs.toString()}`;
}

export function findOpsByPath(path: string): OpsItem | undefined {
  const base = path.split("?")[0];
  return OPS.find((o) => o.path === path || o.path === base);
}

type MenuProps = {
  open: boolean;
  x: number;
  y: number;
  target: OpsTarget | null;
  onClose: () => void;
};

type FlyPos = { top: number; left: number; key: string };

export function ServerOpsMenu({ open, x, y, target, onClose }: MenuProps) {
  const t = useT();
  const navigate = useNavigate();
  const menuRef = useRef<HTMLDivElement>(null);
  const closeTimer = useRef<number | null>(null);
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const [pos, setPos] = useState({ left: x, top: y, maxHeight: 320 });
  const [fly, setFly] = useState<FlyPos | null>(null);

  useLayoutEffect(() => {
    if (!open || !target) return;
    setFly(null);
    const pad = 8;
    const el = menuRef.current;
    const width = el?.offsetWidth || 240;
    const height = el?.scrollHeight || 420;

    let left = x;
    if (left + width > window.innerWidth - pad) {
      left = Math.max(pad, window.innerWidth - width - pad);
    }
    left = Math.max(pad, left);

    const spaceBelow = window.innerHeight - y - pad;
    const spaceAbove = y - pad;
    const preferDown = spaceBelow >= Math.min(height, 280) || spaceBelow >= spaceAbove;

    let top: number;
    let maxHeight: number;
    if (preferDown) {
      maxHeight = Math.max(160, Math.min(window.innerHeight * 0.85, spaceBelow));
      top = y;
      const visible = Math.min(height, maxHeight);
      if (top + visible > window.innerHeight - pad) {
        top = Math.max(pad, window.innerHeight - visible - pad);
      }
    } else {
      maxHeight = Math.max(160, Math.min(window.innerHeight * 0.85, spaceAbove));
      const used = Math.min(height, maxHeight);
      top = Math.max(pad, y - used);
    }

    setPos({ left, top, maxHeight });
  }, [open, x, y, target]);

  useEffect(() => {
    return () => {
      if (closeTimer.current) window.clearTimeout(closeTimer.current);
    };
  }, []);

  if (!open || !target || target.ids.length === 0) return null;

  function go(path: string) {
    navigate(buildOpsUrl(path, target!));
    onClose();
  }

  function clearCloseTimer() {
    if (closeTimer.current) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  }

  function openFly(key: string) {
    clearCloseTimer();
    const el = rowRefs.current[key];
    if (!el) {
      setFly({ key, top: 0, left: 0 });
      return;
    }
    const r = el.getBoundingClientRect();
    const flyW = 220;
    const pad = 8;
    const openLeft = r.right + flyW > window.innerWidth - pad;
    let left = openLeft ? r.left - flyW - 2 : r.right + 2;
    left = Math.max(pad, Math.min(left, window.innerWidth - flyW - pad));
    let top = r.top;
    const flyH = 140;
    if (top + flyH > window.innerHeight - pad) {
      top = Math.max(pad, window.innerHeight - flyH - pad);
    }
    setFly({ key, top, left });
  }

  function scheduleCloseFly() {
    clearCloseTimer();
    closeTimer.current = window.setTimeout(() => setFly(null), 180);
  }

  const visibleOps = opsForTarget(target);
  const openOp = fly ? visibleOps.find((o) => o.key === fly.key) : null;

  return (
    <>
      <div
        className="fixed inset-0 z-40"
        onClick={onClose}
        onContextMenu={(e) => {
          e.preventDefault();
          onClose();
        }}
      />
      <div
        ref={menuRef}
        className="fixed z-50 flex min-w-[240px] flex-col overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-popover)] shadow-xl"
        style={{ left: pos.left, top: pos.top, maxHeight: pos.maxHeight }}
        role="menu"
      >
        <p className="shrink-0 truncate border-b border-[var(--color-border)] px-3 py-1.5 text-[10px] uppercase tracking-wide text-[var(--color-muted-foreground)]">
          {target.hostnames[0]}
          {target.ids.length > 1 ? ` +${target.ids.length - 1}` : ""}
        </p>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain py-1">
          {visibleOps.length === 0 ? (
            <p className="px-3 py-2 text-xs text-[var(--color-muted-foreground)]">{t("ops_multi_none")}</p>
          ) : null}
          {visibleOps.map((op) => {
            const Icon = op.icon;
            const hasChildren = Boolean(op.children?.length);
            const isHot = fly?.key === op.key;

            if (!hasChildren) {
              return (
                <button
                  key={op.path}
                  type="button"
                  role="menuitem"
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-[var(--color-accent)]"
                  onMouseEnter={() => scheduleCloseFly()}
                  onClick={() => go(op.path)}
                >
                  <Icon className="h-4 w-4 shrink-0 text-[var(--color-muted-foreground)]" />
                  {t(op.key)}
                </button>
              );
            }

            return (
              <div
                key={op.path}
                ref={(node) => {
                  rowRefs.current[op.key] = node;
                }}
                onMouseEnter={() => openFly(op.key)}
                onMouseLeave={scheduleCloseFly}
              >
                <button
                  type="button"
                  role="menuitem"
                  aria-haspopup="menu"
                  aria-expanded={isHot}
                  className={cn(
                    "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-[var(--color-accent)]",
                    isHot && "bg-[var(--color-accent)]",
                  )}
                  onClick={(e) => {
                    e.preventDefault();
                    if (isHot) scheduleCloseFly();
                    else openFly(op.key);
                  }}
                >
                  <Icon className="h-4 w-4 shrink-0 text-[var(--color-muted-foreground)]" />
                  <span className="flex-1">{t(op.key)}</span>
                  <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[var(--color-muted-foreground)]" />
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {fly && openOp?.children?.length
        ? createPortal(
            <div
              role="menu"
              className="fixed z-[70] min-w-[210px] rounded-xl border border-[var(--color-border)] bg-[var(--color-popover)] py-1.5 shadow-xl"
              style={{ top: fly.top, left: fly.left }}
              onMouseEnter={clearCloseTimer}
              onMouseLeave={scheduleCloseFly}
            >
              {openOp.children.map((child) => (
                <button
                  key={child.path}
                  type="button"
                  role="menuitem"
                  className="flex w-full items-center px-3 py-1.5 text-left text-sm hover:bg-[var(--color-accent)]"
                  onClick={() => go(child.path)}
                >
                  {t(child.key)}
                </button>
              ))}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}

export { OPS as SERVER_OPS };
