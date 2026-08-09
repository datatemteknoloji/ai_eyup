import { FormEvent, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@dropt/components/ui/button";
import { Input } from "@dropt/components/ui/input";
import { useT } from "@dropt/i18n/I18nProvider";

type Props = {
  page: number;
  pageCount: number;
  total: number;
  onPageChange: (page: number) => void;
  disabled?: boolean;
};

export function PaginationBar({ page, pageCount, total, onPageChange, disabled }: Props) {
  const t = useT();
  const safeCount = Math.max(1, pageCount);
  const [draft, setDraft] = useState(String(page));

  useEffect(() => {
    setDraft(String(page));
  }, [page]);

  function goTo(raw: string | number) {
    const n = typeof raw === "number" ? raw : Number.parseInt(String(raw).trim(), 10);
    if (!Number.isFinite(n)) {
      setDraft(String(page));
      return;
    }
    const next = Math.min(safeCount, Math.max(1, Math.trunc(n)));
    setDraft(String(next));
    if (next !== page) onPageChange(next);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    goTo(draft);
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--color-border)] px-3 py-2 text-xs text-[var(--color-muted-foreground)]">
      <span>{t("total_page", { total, page, pageCount: safeCount })}</span>
      <form className="flex flex-wrap items-center gap-2" onSubmit={onSubmit}>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={disabled || page <= 1}
          onClick={() => goTo(page - 1)}
          className="gap-1"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
          {t("prev_page")}
        </Button>
        <label className="flex items-center gap-1.5">
          <span className="whitespace-nowrap">{t("page_jump_label")}</span>
          <Input
            type="number"
            min={1}
            max={safeCount}
            inputMode="numeric"
            className="h-8 w-16 px-2 text-center text-xs"
            value={draft}
            disabled={disabled}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => goTo(draft)}
            aria-label={t("page_jump_label")}
          />
          <span className="whitespace-nowrap">/ {safeCount}</span>
        </label>
        <Button type="submit" size="sm" variant="secondary" disabled={disabled}>
          {t("page_jump_go")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={disabled || page >= safeCount}
          onClick={() => goTo(page + 1)}
          className="gap-1"
        >
          {t("next_page")}
          <ChevronRight className="h-3.5 w-3.5" />
        </Button>
      </form>
    </div>
  );
}
