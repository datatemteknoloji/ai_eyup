import * as React from "react";
import { cn } from "@dropt/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => (
    <input
      type={type}
      className={cn(
        "flex h-9 w-full rounded-md border border-(--color-input) bg-(--color-card) px-3 py-1 text-sm text-(--color-foreground) shadow-xs transition-colors placeholder:text-(--color-muted-foreground) focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--color-ring) disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      ref={ref}
      {...props}
    />
  ),
);
Input.displayName = "Input";
