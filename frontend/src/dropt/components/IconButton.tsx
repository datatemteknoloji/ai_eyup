import type { LucideIcon } from "lucide-react";
import { Button } from "@dropt/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@dropt/components/ui/tooltip";

type Props = {
  icon: LucideIcon;
  label: string;
  onClick?: () => void;
  variant?: "default" | "secondary" | "outline" | "ghost" | "destructive";
  disabled?: boolean;
  className?: string;
  iconClassName?: string;
};

export function IconButton({
  icon: Icon,
  label,
  onClick,
  variant = "ghost",
  disabled,
  className,
  iconClassName,
}: Props) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          size="icon"
          variant={variant}
          aria-label={label}
          title={label}
          disabled={disabled}
          onClick={onClick}
          className={className}
        >
          <Icon className={iconClassName} />
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}
