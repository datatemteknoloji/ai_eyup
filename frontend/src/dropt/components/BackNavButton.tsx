import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";
import { cn } from "@dropt/lib/utils";

const baseClass = cn(
  "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px]",
  "border border-white/[0.08] bg-[var(--bg-elevated,var(--color-secondary))]",
  "text-[var(--text-secondary,var(--color-muted-foreground))]",
  "shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] transition-colors",
  "hover:border-[var(--accent,var(--color-primary))]/40",
  "hover:bg-[var(--accent-subtle,rgba(59,130,246,0.12))]",
  "hover:text-[var(--accent,var(--color-primary))]",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40",
  "disabled:pointer-events-none disabled:opacity-40",
);

type Props = {
  label: string;
  to?: string;
  onClick?: () => void;
  className?: string;
  disabled?: boolean;
};

/** Level 1 geri navigasyon — metin link yerine temaya uygun ikon. */
export function BackNavButton({ label, to, onClick, className, disabled }: Props) {
  const cls = cn(baseClass, className);
  const icon = <ArrowLeft className="h-4 w-4" strokeWidth={2.25} />;

  if (to && !disabled) {
    return (
      <Link to={to} title={label} aria-label={label} className={cls}>
        {icon}
      </Link>
    );
  }

  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={cls}
    >
      {icon}
    </button>
  );
}
