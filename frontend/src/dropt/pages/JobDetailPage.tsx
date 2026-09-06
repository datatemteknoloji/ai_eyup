import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { applyJob, downloadJobArtifact, getJob, JobPublic, previewJob } from "@dropt/api";
import { BackNavButton } from "@dropt/components/BackNavButton";
import { Badge } from "@dropt/components/ui/badge";
import { Button } from "@dropt/components/ui/button";
import { useI18n } from "@dropt/i18n/I18nProvider";
import { getToken } from "@dropt/session";

export function JobDetailPage() {
  const { id } = useParams();
  const jobId = Number(id);
  const token = getToken()!;
  const { t, locale } = useI18n();
  const [job, setJob] = useState<JobPublic | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showTech, setShowTech] = useState(false);
  const [applyNotice, setApplyNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!Number.isFinite(jobId)) return;
    try {
      const data = await getJob(token, jobId);
      setJob(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "İş okunamadı");
    }
  }, [token, jobId]);

  useEffect(() => {
    void load();
  }, [load]);

  // job objesi her poll'da değişmesin diye yalnızca status'a bağla; interval reset fırtınası olmasın
  useEffect(() => {
    if (!job?.status) return;
    if (!["approved", "running"].includes(job.status)) return;
    let delay = 2000;
    let timer: number | undefined;
    let cancelled = false;

    const schedule = () => {
      timer = window.setTimeout(async () => {
        if (cancelled) return;
        await load();
        delay = Math.min(delay + 1000, 8000);
        if (!cancelled) schedule();
      }, delay);
    };
    schedule();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [job?.status, load]);

  async function onPreview() {
    setBusy(true);
    setError(null);
    try {
      setJob(await previewJob(token, jobId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Önizleme başarısız");
    } finally {
      setBusy(false);
    }
  }

  async function onApply(onlyFailed = false) {
    setBusy(true);
    setError(null);
    try {
      const updated = await applyJob(token, jobId, { sync: true, only_failed: onlyFailed });
      setJob(updated);
      setApplyNotice(updated.status);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Uygulama başarısız");
      setApplyNotice("failed");
    } finally {
      setBusy(false);
    }
  }

  async function onDownload(runId?: number) {
    setError(null);
    try {
      await downloadJobArtifact(token, jobId, runId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "İndirme başarısız");
    }
  }

  if (!job) {
    return (
      <div className="px-6 py-6 text-sm text-[var(--color-muted-foreground)]">
        {error || t("loading")}
      </div>
    );
  }

  const canPreview = ["draft", "previewed", "failed", "partial"].includes(job.status);
  const canApply = job.status === "previewed";
  const canRetry = job.status === "partial" || job.status === "failed";
  const previewOk = (job.preview?.host_summaries || []).some((h) => h.ok);
  const downloadRuns = (job.runs || []).filter(
    (r) => r.status === "success" && Boolean(r.after_state?.downloadable),
  );

  return (
    <div className="px-6 py-6">
      <div className="mb-4">
        <div className="mb-2 flex items-center gap-2">
          <BackNavButton to="/level1/jobs" label={t("back_jobs")} />
        </div>
        <h2 className="text-xl font-semibold">
          #{job.id} · {job.title}
        </h2>
        <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
          {t("talep_id")}: <span className="font-mono text-[var(--color-foreground)]">{job.talep_id}</span>
          {" · "}
          <Badge variant="muted">{job.status}</Badge>
        </p>
      </div>

      {error ? <p className="mb-3 text-sm text-[var(--color-destructive)]">{error}</p> : null}

      {applyNotice ? (
        <div
          role="status"
          className={`mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3 ${
            applyNotice === "success"
              ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-100"
              : applyNotice === "partial"
                ? "border-amber-500/50 bg-amber-500/15 text-amber-100"
                : "border-red-500/50 bg-red-500/15 text-red-100"
          }`}
        >
          <p className="text-sm font-semibold">
            {applyNotice === "success"
              ? `✓ ${t("console_done_success")}`
              : applyNotice === "partial"
                ? `⚠ ${t("console_done_partial")}`
                : `✗ ${t("console_done_failed")}`}
            <span className="ml-2 font-normal opacity-90">({applyNotice})</span>
          </p>
          <Button type="button" size="sm" variant="secondary" onClick={() => setApplyNotice(null)}>
            {t("console_done_dismiss")}
          </Button>
        </div>
      ) : null}

      <div className="mb-4 flex flex-wrap gap-2">
        <Button variant="secondary" disabled={!canPreview || busy} onClick={() => void onPreview()}>
          {t("preview")}
        </Button>
        <Button disabled={!canApply || !previewOk || busy} onClick={() => void onApply(false)}>
          {job.module === "log_collect" ? t("create_package") : t("apply")}
        </Button>
        {canRetry ? (
          <Button variant="outline" disabled={busy} onClick={() => void onApply(true)}>
            {t("retry_failed")}
          </Button>
        ) : null}
        {downloadRuns.length > 0 ? (
          <Button variant="outline" onClick={() => void onDownload(downloadRuns[0]?.id)}>
            {t("download_zip")}
          </Button>
        ) : null}
      </div>

      {job.preview ? (
        <div className="mb-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-4">
          <h3 className="text-sm font-medium">{t("preview_summary")}</h3>
          <p className="mt-2 text-sm">{job.preview.summary_tr}</p>
          {job.preview.risk_notes ? (
            <p className="mt-2 text-sm text-amber-200/90">{job.preview.risk_notes}</p>
          ) : null}
          <button
            type="button"
            className="mt-3 text-xs text-[var(--color-primary)] hover:underline"
            onClick={() => setShowTech((v) => !v)}
          >
            {showTech ? t("hide_technical") : t("technical_detail")}
          </button>
          {showTech ? (
            <pre className="mt-2 overflow-x-auto rounded-md bg-[var(--theme-inset)] p-3 font-mono text-xs">
              {job.preview.technical_detail || "(boş)"}
            </pre>
          ) : null}
        </div>
      ) : (
        <p className="mb-4 text-sm text-[var(--color-muted-foreground)]">
          {t("apply_after_preview")}
        </p>
      )}

      <div className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-card)]/80">
        <table className="w-full text-sm">
          <thead className="border-b border-[var(--color-border)] text-[var(--color-muted-foreground)]">
            <tr>
              <th className="px-3 py-3 text-left font-medium">{t("server")}</th>
              <th className="px-3 py-3 text-left font-medium">{t("status")}</th>
              <th className="px-3 py-3 text-left font-medium">Özet</th>
              <th className="px-3 py-3 text-left font-medium" />
            </tr>
          </thead>
          <tbody>
            {(job.runs || []).map((r) => (
              <tr key={r.id} className="border-t border-[var(--color-border)]">
                <td className="px-3 py-2.5 font-mono text-xs">
                  {r.hostname}
                  <div className="text-[var(--color-muted-foreground)]">{r.ip}</div>
                </td>
                <td className="px-3 py-2.5">
                  <Badge
                    variant={
                      r.status === "success" ? "success" : r.status === "failed" ? "danger" : "muted"
                    }
                  >
                    {r.status}
                  </Badge>
                </td>
                <td className="px-3 py-2.5 text-xs">
                  {r.summary_tr}
                  {r.after_state?.artifact_filename ? (
                    <div className="mt-1 font-mono text-[var(--color-muted-foreground)]">
                      {String(r.after_state.artifact_filename)} ·{" "}
                      {String(r.after_state.artifact_size_bytes ?? "?")} bayt
                    </div>
                  ) : null}
                  {Array.isArray(r.after_state?.post_notes) &&
                  (r.after_state.post_notes as string[]).length ? (
                    <ul className="mt-2 space-y-0.5 text-emerald-600">
                      {(r.after_state.post_notes as string[]).map((n, i) => (
                        <li key={i}>{n}</li>
                      ))}
                    </ul>
                  ) : null}
                  {(() => {
                    const en = r.after_state?.checklist_en;
                    const items =
                      locale === "en" && Array.isArray(en)
                        ? (en as string[])
                        : Array.isArray(r.after_state?.checklist)
                          ? (r.after_state.checklist as string[])
                          : null;
                    if (!items?.length) return null;
                    return (
                      <ol className="mt-2 list-decimal space-y-2 pl-4 text-[var(--color-muted-foreground)]">
                        {items.map((c, i) => (
                          <li key={i} className="whitespace-pre-wrap">
                            {c}
                          </li>
                        ))}
                      </ol>
                    );
                  })()}
                  {r.error_message ? (
                    <div className="mt-1 text-[var(--color-destructive)]">{r.error_message}</div>
                  ) : null}
                </td>
                <td className="px-3 py-2.5 text-right">
                  {r.status === "success" && r.after_state?.downloadable ? (
                    <Button size="sm" variant="outline" onClick={() => void onDownload(r.id)}>
                      İndir
                    </Button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
