import type { ComponentType } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import {
  applyJob,
  getJob,
  getServer,
  getServerFacts,
  jobEventsWsUrl,
  JobPublic,
  ServerFacts,
  ServerPublic,
} from "@dropt/api";
import { SERVER_OPS, buildOpsUrl, findOpsByPath } from "@dropt/components/ServerOpsMenu";
import { Badge } from "@dropt/components/ui/badge";
import { Button } from "@dropt/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@dropt/components/ui/dialog";
import { OpsWizardContext } from "@dropt/hooks/useOpsWizard";
import { useT } from "@dropt/i18n/I18nProvider";
import { cn } from "@dropt/lib/utils";
import { AsmPage } from "@dropt/pages/AsmPage";
import { FilesystemPage } from "@dropt/pages/FilesystemPage";
import { HostnamePage } from "@dropt/pages/HostnamePage";
import { LocalUsersPage } from "@dropt/pages/LocalUsersPage";
import { LogCollectPage } from "@dropt/pages/LogCollectPage";
import { MailConfigPage } from "@dropt/pages/MailConfigPage";
import { PackagesPage } from "@dropt/pages/PackagesPage";
import { PathPermsPage } from "@dropt/pages/PathPermsPage";
import { RebootPage } from "@dropt/pages/RebootPage";
import { ServicesPage } from "@dropt/pages/ServicesPage";
import { SudoersPage } from "@dropt/pages/SudoersPage";
import { SysctlPage } from "@dropt/pages/SysctlPage";
import { LimitsPage } from "@dropt/pages/LimitsPage";
import { NetworkPage } from "@dropt/pages/NetworkPage";
import { VlanPage } from "@dropt/pages/VlanPage";
import { getToken } from "@dropt/session";

const WIZARD_BY_PATH: Record<string, ComponentType> = {
  "/app/local-users": LocalUsersPage,
  "/app/hostname": HostnamePage,
  "/app/reboot": RebootPage,
  "/app/services": ServicesPage,
  "/app/sudoers": SudoersPage,
  "/app/filesystem": FilesystemPage,
  "/app/packages": PackagesPage,
  "/app/path-perms": PathPermsPage,
  "/app/logs": LogCollectPage,
  "/app/limits": LimitsPage,
  "/app/sysctl": SysctlPage,
  "/app/network": NetworkPage,
  "/app/vlan": VlanPage,
  "/app/asm": AsmPage,
  "/app/mail-config": MailConfigPage,
};

const MODULE_TO_WIZARD: Record<string, string> = {
  local_users: "/app/local-users",
  hostname: "/app/hostname",
  reboot: "/app/reboot",
  services: "/app/services",
  sudoers: "/app/sudoers",
  filesystem: "/app/filesystem",
  packages: "/app/packages",
  path_perms: "/app/path-perms",
  log_collect: "/app/logs",
  limits: "/app/limits",
  sysctl: "/app/sysctl",
  vlan: "/app/network",
  network: "/app/network",
  asm: "/app/asm",
  mail_config: "/app/mail-config",
};

function formatEventLine(ev: Record<string, unknown>): string {
  const type = String(ev.type || "");
  const host = ev.hostname ? `[${ev.hostname}] ` : "";
  switch (type) {
    case "subscribed":
      return `\r\n\x1b[90m# job #${ev.job_id} stream bağlı\x1b[0m\r\n`;
    case "job_start":
      return `\r\n\x1b[36m══ Uygulama başladı · ${ev.module}.${ev.action} · ${ev.talep_id}\x1b[0m\r\n`;
    case "run_start":
      return `\r\n\x1b[33m── ${host}${ev.summary || ""}\x1b[0m\r\n`;
    case "command":
      return `\x1b[32m${ev.line || ""}\x1b[0m\r\n`;
    case "stdout":
      return `${String(ev.text || "").replace(/\n/g, "\r\n")}\r\n`;
    case "stderr":
      return `\x1b[31m${String(ev.text || "").replace(/\n/g, "\r\n")}\x1b[0m\r\n`;
    case "run_end":
      return ev.ok
        ? `\x1b[32m✓ ${host}${ev.message || "ok"}\x1b[0m\r\n`
        : `\x1b[31m✗ ${host}${ev.message || "fail"}\x1b[0m\r\n`;
    case "run_skip":
      return `\x1b[90m⊘ ${host}${ev.message || "skip"}\x1b[0m\r\n`;
    case "progress": {
      const pct = ev.percent != null ? `${ev.percent}%` : `${ev.done}/${ev.total}`;
      return `\x1b[90m… ${pct} ${ev.label || ""}\x1b[0m\r\n`;
    }
    case "error":
      return `\x1b[31m! ${host}${ev.message || "error"}\x1b[0m\r\n`;
    case "job_end":
      return `\r\n\x1b[36m══ Bitti · ${ev.status} (ok=${ev.success} fail=${ev.failed} skip=${ev.skipped})\x1b[0m\r\n${
        ev.error ? `\x1b[31m! ${ev.error}\x1b[0m\r\n` : ""
      }`;
    default:
      return `\x1b[90m${JSON.stringify(ev)}\x1b[0m\r\n`;
  }
}

export function ServerConsolePage() {
  const { id } = useParams();
  const serverId = Number(id);
  const token = getToken()!;
  const t = useT();
  const navigate = useNavigate();

  const [server, setServer] = useState<ServerPublic | null>(null);
  const [facts, setFacts] = useState<ServerFacts | null>(null);
  const [factsError, setFactsError] = useState<string | null>(null);
  const [factsLoading, setFactsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeJob, setActiveJob] = useState<JobPublic | null>(null);
  const [busy, setBusy] = useState(false);
  const [showTech, setShowTech] = useState(false);
  const [wizardPath, setWizardPath] = useState<string | null>(null);
  const [wizardEpoch, setWizardEpoch] = useState(0);
  const [applyResult, setApplyResult] = useState<{
    status: string;
    success: number;
    failed: number;
    skipped: number;
    title: string;
  } | null>(null);
  const [jobProgress, setJobProgress] = useState<{
    percent: number;
    label: string;
    done: number;
    total: number;
  } | null>(null);

  const hostRef = useRef<HTMLDivElement | null>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const writeLine = useCallback((text: string) => {
    const term = termRef.current;
    if (!term) return;
    term.write(text);
    try {
      term.scrollToBottom();
    } catch {
      /* ignore */
    }
  }, []);

  const refitTerminal = useCallback(() => {
    const fit = fitRef.current;
    const term = termRef.current;
    if (!fit || !term) return;
    try {
      fit.fit();
      // Son satırın clip olmaması için 1 satır rezerv
      const dims = fit.proposeDimensions();
      if (dims && dims.rows > 2 && dims.cols > 2) {
        term.resize(dims.cols, Math.max(2, dims.rows - 1));
      }
      term.scrollToBottom();
    } catch {
      /* ignore */
    }
  }, []);

  const loadFacts = useCallback(async () => {
    if (!Number.isFinite(serverId)) return;
    setFactsLoading(true);
    setFactsError(null);
    try {
      const [s, f] = await Promise.all([getServer(token, serverId), getServerFacts(token, serverId)]);
      setServer(s);
      setFacts(f);
      if ((!f.ok && !f.reachable) || f.error) {
        const detail = (f.error || "").trim() || "SSH bağlantısı kurulamadı";
        setFactsError(
          `${detail}. Level 1 → Ayarlar’da otomasyon kimlik bilgilerini kontrol edin; Operasyon Merkezi’nden bağlantı testi yapın.`,
        );
      }
    } catch (err) {
      setFactsError(err instanceof Error ? err.message : "Özet okunamadı / SSH hatası");
    } finally {
      setFactsLoading(false);
    }
  }, [token, serverId]);

  useEffect(() => {
    void loadFacts();
  }, [loadFacts]);

  useEffect(() => {
    if (!hostRef.current) return;
    const host = hostRef.current;
    const term = new Terminal({
      convertEol: true,
      disableStdin: true,
      cursorBlink: false,
      fontFamily: "IBM Plex Mono, ui-monospace, monospace",
      fontSize: 12,
      theme: {
        background: "#0b1220",
        foreground: "#d6e2ff",
        cursor: "#0b1220",
      },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(host);
    termRef.current = term;
    fitRef.current = fit;
    requestAnimationFrame(() => refitTerminal());
    term.write(`\x1b[90m# ${t("console_log_hint")}\x1b[0m\r\n`);

    const onResize = () => refitTerminal();
    window.addEventListener("resize", onResize);
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => refitTerminal()) : null;
    ro?.observe(host);
    return () => {
      window.removeEventListener("resize", onResize);
      ro?.disconnect();
      wsRef.current?.close();
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
    };
  }, [t, refitTerminal]);

  useEffect(() => {
    // Success banner açılınca / kapanınca yükseklik değişir → yeniden fit
    const id = requestAnimationFrame(() => refitTerminal());
    return () => cancelAnimationFrame(id);
  }, [applyResult, activeJob, refitTerminal]);

  const dumpPreviewToConsole = useCallback(
    (job: JobPublic) => {
      writeLine(`\r\n\x1b[36m══ Önizleme #${job.id} · ${job.title} · ${job.talep_id}\x1b[0m\r\n`);
      if (job.preview?.summary_tr) {
        writeLine(`${job.preview.summary_tr}\r\n`);
      }
      for (const cmd of job.preview?.planned_commands || []) {
        writeLine(`\x1b[32m$ ${cmd}\x1b[0m\r\n`);
      }
      for (const h of job.preview?.host_summaries || []) {
        const mark = h.ok ? "\x1b[32m✓" : "\x1b[31m✗";
        writeLine(`${mark} [${h.hostname}] ${h.summary_tr || ""}\x1b[0m\r\n`);
        if (!h.ok && h.error) {
          writeLine(`\x1b[31m   → ${h.error}\x1b[0m\r\n`);
        }
      }
      writeLine(`\x1b[90m# ${t("console_apply_hint")}\x1b[0m\r\n`);
    },
    [t, writeLine],
  );

  const onAfterPreview = useCallback(
    (job: JobPublic) => {
      setWizardPath(null);
      setActiveJob(job);
      setShowTech(false);
      setApplyResult(null);
      dumpPreviewToConsole(job);
    },
    [dumpPreviewToConsole],
  );

  const wizardCtx = useMemo(
    () => ({
      embedded: true,
      serverId: String(serverId),
      serverIds: [String(serverId)],
      onAfterPreview,
      draftJob: activeJob,
    }),
    [serverId, onAfterPreview, activeJob],
  );

  function onEditSelections() {
    if (!activeJob || busy) return;
    const path = MODULE_TO_WIZARD[activeJob.module];
    if (!path) return;
    setWizardPath(path);
  }

  async function onApply() {
    if (!activeJob) return;
    const jobId = activeJob.id;
    setBusy(true);
    setError(null);
    setJobProgress({ percent: 0, label: "kuyruğa alındı…", done: 0, total: 0 });
    wsRef.current?.close();

    setApplyResult(null);
    let finished = false;
    let pollId = 0;

    const finishFromJob = (j: JobPublic, fromWs = false) => {
      if (finished) return;
      finished = true;
      if (pollId) window.clearInterval(pollId);
      setActiveJob(j);
      setApplyResult({
        status: j.status,
        success: j.status === "success" ? 1 : j.status === "partial" ? 1 : 0,
        failed: j.status === "failed" || j.status === "partial" ? 1 : 0,
        skipped: 0,
        title: j.title,
      });
      setJobProgress((p) =>
        p
          ? { ...p, percent: 100, label: j.status }
          : { percent: 100, label: j.status, done: 1, total: 1 },
      );
      setBusy(false);
      if (!fromWs && j.error_message) {
        writeLine(`\x1b[31m! ${j.error_message}\x1b[0m\r\n`);
      }
      void loadFacts();
    };

    const ws = new WebSocket(jobEventsWsUrl(jobId, token));
    wsRef.current = ws;
    ws.onmessage = (msg) => {
      try {
        const ev = JSON.parse(String(msg.data)) as Record<string, unknown>;
        if (ev.type === "progress") {
          setJobProgress({
            percent: Number(ev.percent ?? 0),
            label: String(ev.label || ""),
            done: Number(ev.done ?? 0),
            total: Number(ev.total ?? 0),
          });
        }
        writeLine(formatEventLine(ev));
        if (ev.type === "job_end") {
          if (pollId) window.clearInterval(pollId);
          finished = true;
          setApplyResult({
            status: String(ev.status || ""),
            success: Number(ev.success || 0),
            failed: Number(ev.failed || 0),
            skipped: Number(ev.skipped || 0),
            title: activeJob.title,
          });
          setJobProgress((p) =>
            p
              ? { ...p, percent: 100, label: String(ev.status || "bitti") }
              : { percent: 100, label: "bitti", done: 1, total: 1 },
          );
          setBusy(false);
          void getJob(token, jobId).then(setActiveJob).catch(() => undefined);
          void loadFacts();
        }
      } catch {
        writeLine(String(msg.data) + "\r\n");
      }
    };

    await new Promise<void>((resolve) => {
      if (ws.readyState === WebSocket.OPEN) resolve();
      else ws.onopen = () => resolve();
      window.setTimeout(() => resolve(), 1500);
    });

    try {
      // Arka plan (Celery) — UI WS + poll fallback
      const updated = await applyJob(token, jobId, { sync: false });
      setActiveJob(updated);
      pollId = window.setInterval(() => {
        if (finished) {
          window.clearInterval(pollId);
          return;
        }
        void getJob(token, jobId)
          .then((j) => {
            if (finished) return;
            if (!["approved", "running"].includes(j.status)) {
              finishFromJob(j);
              return;
            }
            setActiveJob(j);
            if (j.progress_total > 0) {
              const pct = Math.min(
                99,
                Math.round((100 * (j.progress_done || 0)) / j.progress_total),
              );
              setJobProgress({
                percent: pct,
                label: j.status === "approved" ? "kuyrukta…" : "çalışıyor…",
                done: j.progress_done || 0,
                total: j.progress_total,
              });
            }
          })
          .catch(() => undefined);
      }, 2500);
    } catch (err) {
      finished = true;
      if (pollId) window.clearInterval(pollId);
      setError(err instanceof Error ? err.message : "Uygulama başarısız");
      writeLine(`\x1b[31m! ${err instanceof Error ? err.message : "uygulama hatası"}\x1b[0m\r\n`);
      setApplyResult({
        status: "failed",
        success: 0,
        failed: 1,
        skipped: 0,
        title: activeJob.title,
      });
      setJobProgress(null);
      setBusy(false);
      window.setTimeout(() => {
        try {
          ws.close();
        } catch {
          /* ignore */
        }
      }, 800);
    }
  }

  function openOp(path: string) {
    if (path === "/app/terminal") {
      navigate(buildOpsUrl(path, { ids: [serverId], hostnames: [server?.hostname || ""] }));
      return;
    }
    setWizardEpoch((n) => n + 1);
    setWizardPath(path);
  }

  const Wizard = wizardPath ? WIZARD_BY_PATH[wizardPath] : null;
  const wizardTitle = wizardPath ? findOpsByPath(wizardPath) : undefined;
  const canApply = activeJob?.status === "previewed";
  const previewOk = (activeJob?.preview?.host_summaries || []).some((h) => h.ok);

  const machineLabel =
    facts?.machine_type === "physical"
      ? t("console_physical")
      : facts?.virtualization
        ? `${t("console_virtual")} (${facts.virtualization})`
        : t("console_virtual");

  const hostTitle = server?.hostname || facts?.hostname || `Server #${serverId}`;
  const hostIp = server?.ip || facts?.ip || "—";

  const factChips: { label: string; value: string; mono?: boolean }[] = [
    { label: t("console_type"), value: machineLabel || "—" },
    { label: t("console_os"), value: facts?.os_pretty || facts?.os_name || "—" },
    { label: t("console_kernel"), value: facts?.kernel || "—", mono: true },
    { label: t("console_uptime"), value: facts?.uptime_human || "—" },
    {
      label: t("console_cpu_ram"),
      value:
        [
          facts?.cpus != null ? `${facts.cpus} CPU` : "",
          facts?.memory_total_mb != null ? `${facts.memory_total_mb} MB` : "",
        ]
          .filter(Boolean)
          .join(" · ") || "—",
    },
    { label: t("console_load"), value: facts?.loadavg || "—", mono: true },
  ];

  const opTone = (path: string) => {
    if (path === "/app/terminal") return "l1-op-tile--accent";
    if (path === "/app/reboot") return "l1-op-tile--danger";
    if (path === "/app/packages" || path === "/app/services") return "l1-op-tile--info";
    return "l1-op-tile--default";
  };

  return (
    <div className="l1-server-console flex h-full min-h-0 flex-1 flex-col">
      {/* Genel üst bilgi — hostname sunucuya göre değişir */}
      <header className="l1-console-header shrink-0 border-b border-white/[0.06] bg-[var(--bg-surface)]/80 px-4 py-4 md:px-5">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <Link
              to="/level1"
              className="inline-flex items-center gap-1 text-[11px] font-medium text-[var(--text-secondary)] hover:text-[var(--accent)]"
            >
              ← {t("console_back")}
            </Link>
            <div className="mt-1.5 flex flex-wrap items-center gap-2.5">
              <h1 className="truncate text-xl font-bold tracking-tight text-[var(--text-primary)] md:text-[22px]">
                {hostTitle}
              </h1>
              <span className="rounded-md border border-white/[0.08] bg-[var(--bg-elevated)] px-2 py-0.5 font-mono text-[13px] text-[var(--info)]">
                {hostIp}
              </span>
              {server ? (
                <span
                  className={cn(
                    "rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide",
                    server.status === "ready"
                      ? "bg-[var(--success-bg)] text-[var(--success)]"
                      : "bg-white/[0.06] text-[var(--text-secondary)]",
                  )}
                >
                  {server.status}
                </span>
              ) : null}
            </div>
          </div>
          <Button
            variant="secondary"
            size="sm"
            className="shrink-0 border border-white/[0.08] bg-[var(--bg-elevated)] hover:bg-[var(--bg-overlay)]"
            disabled={factsLoading}
            onClick={() => void loadFacts()}
          >
            {t("refresh")}
          </Button>
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          {factsLoading && !facts
            ? Array.from({ length: 6 }).map((_, i) => (
                <div
                  key={i}
                  className="h-[3.25rem] animate-pulse rounded-lg border border-white/[0.05] bg-[var(--bg-elevated)]/60"
                />
              ))
            : factChips.map((chip) => (
                <div
                  key={chip.label}
                  className="min-w-0 rounded-lg border border-white/[0.06] bg-[var(--bg-elevated)]/50 px-2.5 py-2"
                  title={`${chip.label}: ${chip.value}`}
                >
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                    {chip.label}
                  </div>
                  <div
                    className={cn(
                      "mt-0.5 truncate text-[12px] text-[var(--text-primary)]",
                      chip.mono && "font-mono text-[11px] text-[var(--text-secondary)]",
                    )}
                  >
                    {chip.value}
                  </div>
                </div>
              ))}
        </div>

        {factsError ? (
          <p className="mt-3 rounded-lg border border-[var(--error)]/30 bg-[var(--error-bg)] px-3 py-2 text-xs text-[var(--error)]">
            {factsError}
          </p>
        ) : null}

        <div className="mt-4">
          <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)]">
            {t("operations")}
          </p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5">
            {SERVER_OPS.map((op) => {
              const Icon = op.icon;
              return (
                <button
                  key={op.path}
                  type="button"
                  onClick={() => openOp(op.path)}
                  className={cn("l1-op-tile", opTone(op.path))}
                >
                  <span className="l1-op-tile__icon">
                    <Icon className="h-4 w-4" />
                  </span>
                  <span className="l1-op-tile__label">{t(op.key)}</span>
                </button>
              );
            })}
          </div>
        </div>
      </header>

      {activeJob ? (
        <div className="shrink-0 border-b border-white/[0.06] bg-[var(--bg-elevated)]/40 px-4 py-3 md:px-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-[var(--text-primary)]">
                <span className="font-mono text-[var(--text-secondary)]">#{activeJob.id}</span>
                <span className="truncate">{activeJob.title}</span>
                <Badge variant="muted">{activeJob.status}</Badge>
              </p>
              <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
                {t("talep_id")}: <span className="font-mono text-[var(--text-primary)]">{activeJob.talep_id}</span>
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {["draft", "previewed", "failed", "partial"].includes(activeJob.status) &&
              MODULE_TO_WIZARD[activeJob.module] ? (
                <Button variant="secondary" size="sm" disabled={busy} onClick={() => onEditSelections()}>
                  Seçimleri düzenle
                </Button>
              ) : null}
              <Button disabled={!canApply || !previewOk || busy} onClick={() => void onApply()}>
                {busy ? "…" : activeJob.module === "log_collect" ? t("create_package") : t("apply")}
              </Button>
              <Button variant="outline" size="sm" asChild>
                <Link to={`/level1/jobs/${activeJob.id}`}>{t("console_open_job")}</Link>
              </Button>
            </div>
          </div>
          {activeJob.preview ? (
            <div className="mt-2 rounded-lg border border-white/[0.06] bg-[var(--bg-deep)]/50 px-3 py-2 text-sm text-[var(--text-primary)]">
              <p>{activeJob.preview.summary_tr}</p>
              <button
                type="button"
                className="mt-1 text-xs font-medium text-[var(--accent)] hover:underline"
                onClick={() => setShowTech((v) => !v)}
              >
                {showTech ? t("hide_technical") : t("technical_detail")}
              </button>
              {showTech ? (
                <pre className="mt-2 max-h-40 overflow-auto rounded-md border border-white/[0.06] bg-[var(--bg-base)] p-2 font-mono text-xs text-[var(--text-secondary)]">
                  {activeJob.preview.technical_detail || "(boş)"}
                </pre>
              ) : null}
            </div>
          ) : null}
          {error ? <p className="mt-2 text-sm text-[var(--error)]">{error}</p> : null}
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1 flex-col px-4 pb-4 pt-3 md:px-5">
        <div className="mb-2 flex shrink-0 items-center justify-between gap-2">
          <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)]">
            {t("console_log_title")}
          </p>
          <p className="text-[10px] text-[var(--text-muted)]">Salt okunur önizleme · etkileşimli shell değil</p>
        </div>
        {jobProgress && (busy || jobProgress.percent < 100) ? (
          <div className="mb-3 rounded-xl border border-white/[0.08] bg-[var(--bg-surface)] px-4 py-3">
            <div className="mb-1.5 flex items-center justify-between gap-2 text-xs">
              <span className="truncate text-[var(--text-secondary)]" title={jobProgress.label}>
                {jobProgress.label || "İlerleme"}
              </span>
              <span className="shrink-0 font-mono tabular-nums text-[var(--success)]">
                {jobProgress.percent}%
                {jobProgress.total > 0 ? ` · ${jobProgress.done}/${jobProgress.total}` : ""}
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-[var(--bg-deep)]">
              <div
                className={cn(
                  "h-full rounded-full bg-[var(--accent)] transition-[width] duration-500 ease-out",
                  busy && jobProgress.percent > 0 && jobProgress.percent < 100 && "animate-pulse",
                )}
                style={{ width: `${Math.min(100, Math.max(0, jobProgress.percent))}%` }}
              />
            </div>
          </div>
        ) : null}
        {applyResult ? (
          <div
            role="status"
            className={cn(
              "mb-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3",
              applyResult.status === "success" && "border-[var(--success)]/40 bg-[var(--success-bg)]",
              applyResult.status === "partial" && "border-[var(--warning)]/40 bg-[var(--warning-bg)]",
              applyResult.status !== "success" &&
                applyResult.status !== "partial" &&
                "border-[var(--error)]/40 bg-[var(--error-bg)]",
            )}
          >
            <div>
              <p className="text-sm font-semibold text-[var(--text-primary)]">
                {applyResult.status === "success"
                  ? `✓ ${t("console_done_success")}`
                  : applyResult.status === "partial"
                    ? `⚠ ${t("console_done_partial")}`
                    : `✗ ${t("console_done_failed")}`}
              </p>
              <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
                {applyResult.title} · {applyResult.status} (ok={applyResult.success} fail=
                {applyResult.failed} skip={applyResult.skipped})
              </p>
            </div>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => {
                setApplyResult(null);
                setJobProgress(null);
              }}
            >
              {t("console_done_dismiss")}
            </Button>
          </div>
        ) : null}
        <div
          ref={hostRef}
          className="l1-job-console min-h-[min(52vh,520px)] flex-1 overflow-hidden rounded-xl border border-white/[0.08] bg-[var(--theme-terminal-bg,#060a12)] shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
        />
      </div>

      <Dialog open={Boolean(wizardPath)} onOpenChange={(o) => !o && setWizardPath(null)}>
        <DialogContent
          data-console-wizard
          className={cn(
            "l1-wizard-dialog overflow-hidden border-white/[0.08] bg-[var(--bg-surface)] p-0 text-[var(--text-primary)] shadow-2xl",
            wizardPath === "/app/asm"
              ? "max-h-[96vh] w-[min(96vw,90rem)] max-w-[min(96vw,90rem)]"
              : wizardPath === "/app/filesystem"
                ? "max-h-[90vh] w-[min(96vw,56rem)] max-w-[min(96vw,56rem)]"
                : "max-h-[92vh] max-w-3xl overflow-y-auto",
          )}
        >
          {wizardPath === "/app/asm" ? (
            <DialogTitle className="sr-only">{wizardTitle ? t(wizardTitle.key) : t("operations")}</DialogTitle>
          ) : (
            <DialogHeader className="!mb-0 sticky top-0 z-10 space-y-0 border-b border-white/[0.06] bg-[var(--bg-surface)] px-5 py-3.5">
              <DialogTitle className="text-[15px] font-semibold tracking-tight">
                {wizardTitle ? t(wizardTitle.key) : t("operations")}
              </DialogTitle>
              <p className="mt-0.5 text-[11px] font-normal text-[var(--text-secondary)]">
                {hostTitle}
                {hostIp !== "—" ? ` · ${hostIp}` : ""}
              </p>
            </DialogHeader>
          )}
          <div
            className={cn(
              "ops-wizard-embed l1-wizard-body [&_.px-6]:px-5 [&_.py-6]:py-4",
              wizardPath === "/app/asm" &&
                "flex h-[calc(96vh-0.5rem)] max-h-[calc(96vh-0.5rem)] flex-col overflow-hidden",
              wizardPath === "/app/filesystem" && "max-h-[calc(90vh-4.5rem)] overflow-y-auto",
            )}
          >
            {Wizard ? (
              <OpsWizardContext.Provider value={wizardCtx}>
                <Wizard key={`${wizardPath}-${wizardEpoch}`} />
              </OpsWizardContext.Provider>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
