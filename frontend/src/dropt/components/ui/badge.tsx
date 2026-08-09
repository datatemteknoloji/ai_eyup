import * as React from "react";
import { cn } from "@dropt/lib/utils";

export function Badge({
  className,
  variant = "default",
  ...props
}: React.HTMLAttributes<HTMLDivElement> & {
  variant?: "default" | "success" | "warning" | "danger" | "muted";
}) {
  const styles =
    variant === "success"
      ? "bg-emerald-500/15 text-[var(--theme-success-fg)] border-emerald-500/30"
      : variant === "warning"
        ? "bg-amber-500/15 text-[var(--theme-warning-fg)] border-amber-500/30"
        : variant === "danger"
          ? "bg-red-500/15 text-[var(--theme-danger-fg)] border-red-500/30"
          : variant === "muted"
            ? "bg-[var(--color-muted)] text-[var(--color-muted-foreground)] border-[var(--color-border)]"
            : "bg-[var(--color-primary)]/15 text-[var(--theme-success-fg)] border-[var(--color-primary)]/30";

  return (
    <div
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium",
        styles,
        className,
      )}
      {...props}
    />
  );
}
