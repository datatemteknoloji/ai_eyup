import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@dropt/lib/utils";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

function isPortaledOverlayTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  return Boolean(
    target.closest(
      "[data-radix-select-content],[data-radix-popper-content-wrapper],[data-radix-dropdown-menu-content],[data-radix-tooltip-content]",
    ),
  );
}

export function DialogContent({
  className,
  children,
  onPointerDownOutside,
  onInteractOutside,
  onFocusOutside,
  ...props
}: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay
        className="fixed inset-0 z-[80]"
        style={{ background: "var(--theme-overlay, rgba(2, 6, 16, 0.78))" }}
      />
      <DialogPrimitive.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-[90] w-full max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-xl border p-5 shadow-2xl",
          className,
        )}
        style={{
          background: "var(--color-card, #121a2c)",
          color: "var(--color-foreground, #eef3fb)",
          borderColor: "var(--color-border, rgba(255,255,255,0.2))",
        }}
        {...props}
        onPointerDownOutside={(e) => {
          if (isPortaledOverlayTarget(e.target)) e.preventDefault();
          onPointerDownOutside?.(e);
        }}
        onInteractOutside={(e) => {
          if (isPortaledOverlayTarget(e.target)) e.preventDefault();
          onInteractOutside?.(e);
        }}
        onFocusOutside={(e) => {
          if (isPortaledOverlayTarget(e.target)) e.preventDefault();
          onFocusOutside?.(e);
        }}
      >
        {children}
        <DialogPrimitive.Close
          className="absolute right-3 top-3 rounded-md p-1 hover:opacity-80"
          style={{ color: "var(--color-muted-foreground, #c5d0e8)" }}
        >
          <X className="h-4 w-4" />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export function DialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mb-4 space-y-1", className)} {...props} />;
}

export function DialogTitle({ className, ...props }: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      className={cn("text-lg font-semibold tracking-tight", className)}
      style={{ color: "var(--color-foreground, #eef3fb)" }}
      {...props}
    />
  );
}
