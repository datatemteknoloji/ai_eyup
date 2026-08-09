import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import type { ServerPublic } from "@dropt/api";
import { Input } from "@dropt/components/ui/input";
import { useT } from "@dropt/i18n/I18nProvider";
import { cn } from "@dropt/lib/utils";

type Props = {
  servers: ServerPublic[];
  /** Seçili sunucu id'leri */
  value: number[];
  onChange: (ids: number[]) => void;
  /** false = tek seçim */
  multiple?: boolean;
  disabled?: boolean;
  className?: string;
  /** Liste kutusu yüksekliği (örn. max-h-36) */
  listClassName?: string;
  label?: string;
  /** Çoklu seçimde en fazla kaç sunucu seçilebilir */
  maxSelected?: number;
};

export function ServerPicker({
  servers,
  value,
  onChange,
  multiple = false,
  disabled = false,
  className,
  listClassName,
  label,
  maxSelected,
}: Props) {
  const t = useT();
  const [q, setQ] = useState("");

  const sorted = useMemo(() => {
    return [...servers].sort((a, b) =>
      a.hostname.localeCompare(b.hostname, "tr", { sensitivity: "base" }),
    );
  }, [servers]);

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    if (!term) return sorted;
    return sorted.filter(
      (s) =>
        s.hostname.toLowerCase().includes(term) ||
        (s.ip || "").toLowerCase().includes(term),
    );
  }, [sorted, q]);

  const selectedSet = useMemo(() => new Set(value), [value]);

  function toggle(id: number) {
    if (disabled) return;
    if (!multiple) {
      onChange([id]);
      return;
    }
    if (selectedSet.has(id)) {
      onChange(value.filter((x) => x !== id));
    } else if (maxSelected && value.length >= maxSelected) {
      return;
    } else {
      onChange([...value, id]);
    }
  }

  return (
    <div className={cn("flex min-h-0 flex-col gap-2", className)}>
      <div className="flex shrink-0 items-center justify-between gap-2">
        <p className="text-xs text-[var(--color-muted-foreground)]">
          {label || t("server")}
          {multiple && value.length > 0 ? ` (${value.length})` : ""}
        </p>
        {multiple && value.length > 0 ? (
          <button
            type="button"
            className="text-[10px] text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]"
            onClick={() => onChange([])}
            disabled={disabled}
          >
            Temizle
          </button>
        ) : null}
      </div>
      <div className="relative shrink-0">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--color-muted-foreground)]" />
        <Input
          className="h-8 pl-8 text-xs"
          placeholder="Hostname veya IP ara…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          disabled={disabled}
        />
      </div>
      <div
        className={cn(
          "min-h-0 max-h-48 flex-1 overflow-y-auto rounded-md border border-[var(--color-border)] bg-[var(--color-background)]/40",
          listClassName,
          disabled && "opacity-50",
        )}
        role="listbox"
        aria-multiselectable={multiple}
      >
        {filtered.length === 0 ? (
          <p className="px-3 py-4 text-center text-xs text-[var(--color-muted-foreground)]">Sonuç yok</p>
        ) : (
          filtered.map((s) => {
            const on = selectedSet.has(s.id);
            return (
              <button
                key={s.id}
                type="button"
                role="option"
                aria-selected={on}
                disabled={disabled}
                onClick={() => toggle(s.id)}
                className={cn(
                  "flex w-full items-center gap-2 border-b border-[var(--color-border)] px-2.5 py-1 text-left text-sm last:border-b-0",
                  on
                    ? "bg-[var(--color-primary)]/15 text-[var(--color-foreground)]"
                    : "text-[var(--color-foreground)] hover:bg-[var(--color-accent)]",
                )}
              >
                <span
                  className={cn(
                    "flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-sm border text-[9px]",
                    on
                      ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-white"
                      : "border-[var(--color-border)]",
                    !multiple && "rounded-full",
                  )}
                >
                  {on ? (multiple ? "✓" : "") : null}
                </span>
                <span className="min-w-0 flex-1 truncate font-mono text-xs" title={s.hostname}>
                  {s.hostname}
                </span>
                {s.ip ? (
                  <span className="shrink-0 font-mono text-[10px] text-[var(--color-muted-foreground)]">
                    {s.ip}
                  </span>
                ) : null}
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
