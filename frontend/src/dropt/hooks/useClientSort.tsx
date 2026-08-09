import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { cn } from "@dropt/lib/utils";

export type SortDir = "asc" | "desc";

export function useClientSort<T>(
  items: T[],
  defaultKey: keyof T | string,
  defaultDir: SortDir = "desc",
) {
  const [sortKey, setSortKey] = useState<string>(String(defaultKey));
  const [sortDir, setSortDir] = useState<SortDir>(defaultDir);

  function toggle(key: string) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  const sorted = useMemo(() => {
    const copy = [...items];
    const dir = sortDir === "asc" ? 1 : -1;
    copy.sort((a, b) => {
      const av = (a as Record<string, unknown>)[sortKey];
      const bv = (b as Record<string, unknown>)[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
      const as = String(av).toLocaleLowerCase();
      const bs = String(bv).toLocaleLowerCase();
      return as.localeCompare(bs, undefined, { numeric: true, sensitivity: "base" }) * dir;
    });
    return copy;
  }, [items, sortKey, sortDir]);

  return { sorted, sortKey, sortDir, toggle };
}

export function SortHeader({
  label,
  active,
  dir,
  onClick,
  className,
}: {
  label: string;
  active: boolean;
  dir: SortDir;
  onClick: () => void;
  className?: string;
}) {
  const Icon = !active ? ArrowUpDown : dir === "asc" ? ArrowUp : ArrowDown;
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1 font-medium hover:text-[var(--color-foreground)]",
        active ? "text-[var(--color-foreground)]" : "text-[var(--color-muted-foreground)]",
        className,
      )}
    >
      {label}
      <Icon className="h-3.5 w-3.5 opacity-70" />
    </button>
  );
}
