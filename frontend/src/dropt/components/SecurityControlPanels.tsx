import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  getSecurityPolicy,
  getTlsStatus,
  listMfaUsers,
  listSecuritySessions,
  MfaUserStatus,
  PortalSessionPublic,
  regenerateSelfSignedTls,
  resetUserMfa,
  revokeOtherSessions,
  revokeSecuritySession,
  SecurityPolicy,
  setTlsEnabled,
  TlsStatus,
  updateSecurityPolicy,
  uploadTlsCert,
} from "@dropt/api";
import { Badge } from "@dropt/components/ui/badge";
import { Button } from "@dropt/components/ui/button";
import { Checkbox } from "@dropt/components/ui/checkbox";
import { Input } from "@dropt/components/ui/input";
import { useT } from "@dropt/i18n/I18nProvider";
import type { TranslationKey } from "@dropt/i18n/messages";
import { getToken } from "@dropt/session";

const panelClass =
  "space-y-4 rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] p-6 shadow-sm";

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function shortUa(ua: string): string {
  const s = (ua || "").trim();
  if (!s) return "—";
  if (s.length <= 48) return s;
  return `${s.slice(0, 45)}…`;
}

export function SecurityPolicyPanel() {
  const token = getToken()!;
  const t = useT();
  const [policy, setPolicy] = useState<SecurityPolicy | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const load = useCallback(async () => {
    const p = await getSecurityPolicy(token);
    setPolicy(p);
  }, [token]);

  useEffect(() => {
    void load().catch((e) => setError(e instanceof Error ? e.message : "Hata"));
  }, [load]);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    if (!policy) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const saved = await updateSecurityPolicy(token, policy);
      setPolicy(saved);
      setInfo(t("settings_saved"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  if (!policy) {
    return (
      <div className={panelClass}>
        <p className="text-sm text-[var(--color-muted-foreground)]">{t("loading")}</p>
      </div>
    );
  }

  return (
    <form onSubmit={onSave} className={panelClass}>
      <div>
        <h3 className="text-sm font-medium">{t("security_policy_sessions_title")}</h3>
        <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">{t("security_policy_sessions_help")}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
            {t("security_idle_minutes")}
          </label>
          <Input
            type="number"
            min={5}
            max={1440}
            value={policy.session_idle_minutes}
            onChange={(e) =>
              setPolicy({ ...policy, session_idle_minutes: Number(e.target.value) || policy.session_idle_minutes })
            }
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
            {t("security_absolute_minutes")}
          </label>
          <Input
            type="number"
            min={30}
            max={10080}
            value={policy.session_absolute_minutes}
            onChange={(e) =>
              setPolicy({
                ...policy,
                session_absolute_minutes: Number(e.target.value) || policy.session_absolute_minutes,
              })
            }
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
            {t("security_max_concurrent")}
          </label>
          <Input
            type="number"
            min={1}
            max={50}
            value={policy.session_max_concurrent}
            onChange={(e) =>
              setPolicy({
                ...policy,
                session_max_concurrent: Number(e.target.value) || policy.session_max_concurrent,
              })
            }
          />
        </div>
      </div>

      <div className="border-t border-[var(--color-border)] pt-4">
        <h3 className="text-sm font-medium">{t("security_lockout_title")}</h3>
        <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">{t("security_lockout_help")}</p>
        <label className="mt-3 flex items-center gap-2 text-sm">
          <Checkbox
            checked={policy.lockout_enabled}
            onCheckedChange={(v) => setPolicy({ ...policy, lockout_enabled: !!v })}
          />
          {t("security_lockout_enable")}
        </label>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <div>
            <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
              {t("security_lockout_max_attempts")}
            </label>
            <Input
              type="number"
              min={3}
              max={50}
              disabled={!policy.lockout_enabled}
              value={policy.lockout_max_attempts}
              onChange={(e) =>
                setPolicy({ ...policy, lockout_max_attempts: Number(e.target.value) || policy.lockout_max_attempts })
              }
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
              {t("security_lockout_window_minutes")}
            </label>
            <Input
              type="number"
              min={1}
              max={1440}
              disabled={!policy.lockout_enabled}
              value={policy.lockout_window_minutes}
              onChange={(e) =>
                setPolicy({
                  ...policy,
                  lockout_window_minutes: Number(e.target.value) || policy.lockout_window_minutes,
                })
              }
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
              {t("security_lockout_duration_minutes")}
            </label>
            <Input
              type="number"
              min={1}
              max={1440}
              disabled={!policy.lockout_enabled}
              value={policy.lockout_duration_minutes}
              onChange={(e) =>
                setPolicy({
                  ...policy,
                  lockout_duration_minutes: Number(e.target.value) || policy.lockout_duration_minutes,
                })
              }
            />
          </div>
        </div>
      </div>

      {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
      {info ? <p className="text-sm text-emerald-300">{info}</p> : null}
      <Button type="submit" disabled={busy}>
        {t("save")}
      </Button>
    </form>
  );
}

export function SecuritySessionsPanel() {
  const token = getToken()!;
  const t = useT();
  const [sessions, setSessions] = useState<PortalSessionPublic[]>([]);
  const [busyId, setBusyId] = useState<number | "others" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const load = useCallback(async () => {
    const rows = await listSecuritySessions(token, true);
    setSessions(rows);
  }, [token]);

  useEffect(() => {
    void load().catch((e) => setError(e instanceof Error ? e.message : "Hata"));
  }, [load]);

  async function onRevoke(row: PortalSessionPublic) {
    if (!window.confirm(t("security_session_revoke_confirm", { username: row.username }))) return;
    setBusyId(row.id);
    setError(null);
    setInfo(null);
    try {
      await revokeSecuritySession(token, row.id);
      setInfo(t("security_session_revoked", { username: row.username }));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusyId(null);
    }
  }

  async function onRevokeOthers() {
    if (!window.confirm(t("security_revoke_others_confirm"))) return;
    setBusyId("others");
    setError(null);
    setInfo(null);
    try {
      const r = await revokeOtherSessions(token);
      setInfo(t("security_revoke_others_result", { n: r.revoked }));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusyId(null);
    }
  }

  const busy = busyId !== null;

  return (
    <div className={panelClass}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-medium">{t("security_sessions_title")}</h3>
          <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">{t("security_sessions_help")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load()}>
            {t("refresh")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() => void onRevokeOthers()}
            title={t("security_revoke_others_help")}
          >
            {t("security_revoke_others")}
          </Button>
        </div>
      </div>

      {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
      {info ? <p className="text-sm text-emerald-300">{info}</p> : null}

      <div className="overflow-x-auto rounded-xl border border-[var(--color-border)]">
        <table className="w-full min-w-[920px] text-sm">
          <thead className="border-b border-[var(--color-border)] bg-[var(--color-muted)]/20 text-[var(--color-muted-foreground)]">
            <tr>
              <th className="px-4 py-3 text-left font-medium">{t("username")}</th>
              <th className="px-4 py-3 text-left font-medium">{t("security_col_source")}</th>
              <th className="px-4 py-3 text-left font-medium">{t("security_col_ip")}</th>
              <th className="px-4 py-3 text-left font-medium">{t("security_col_ua")}</th>
              <th className="px-4 py-3 text-left font-medium">{t("security_col_created")}</th>
              <th className="px-4 py-3 text-left font-medium">{t("security_col_last_seen")}</th>
              <th className="px-4 py-3 text-left font-medium">{t("security_col_expires")}</th>
              <th className="sticky right-0 bg-[var(--color-card)] px-4 py-3 text-right font-medium">
                {t("security_col_actions")}
              </th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((row) => (
              <tr key={row.id} className="border-t border-[var(--color-border)] hover:bg-[var(--color-muted)]/10">
                <td className="px-4 py-3 align-middle">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs">{row.username}</span>
                    {row.is_current ? <Badge variant="success">{t("security_current_session")}</Badge> : null}
                  </div>
                </td>
                <td className="px-4 py-3 align-middle">
                  <Badge variant="muted">{row.auth_source}</Badge>
                </td>
                <td className="px-4 py-3 font-mono text-xs align-middle">{row.client_ip || "—"}</td>
                <td className="max-w-[12rem] px-4 py-3 text-xs align-middle text-[var(--color-muted-foreground)]" title={row.user_agent}>
                  {shortUa(row.user_agent)}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-xs align-middle">{fmtDate(row.created_at)}</td>
                <td className="whitespace-nowrap px-4 py-3 text-xs align-middle">{fmtDate(row.last_seen_at)}</td>
                <td className="whitespace-nowrap px-4 py-3 text-xs align-middle">{fmtDate(row.absolute_expires_at)}</td>
                <td className="sticky right-0 bg-[var(--color-card)] px-4 py-3 text-right align-middle">
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={busy}
                    onClick={() => void onRevoke(row)}
                  >
                    {busyId === row.id ? t("loading") : t("security_revoke")}
                  </Button>
                </td>
              </tr>
            ))}
            {sessions.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-[var(--color-muted-foreground)]">
                  {t("no_records")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function mfaStatusLabel(status: string, t: (k: TranslationKey) => string): string {
  if (status === "enabled") return t("security_mfa_status_enabled");
  if (status === "pending") return t("security_mfa_status_pending");
  return t("security_mfa_status_disabled");
}

function mfaStatusVariant(status: string): "success" | "warning" | "muted" {
  if (status === "enabled") return "success";
  if (status === "pending") return "warning";
  return "muted";
}

export function SecurityMfaPanel() {
  const token = getToken()!;
  const t = useT();
  const [policy, setPolicy] = useState<SecurityPolicy | null>(null);
  const [users, setUsers] = useState<MfaUserStatus[]>([]);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [busyUserId, setBusyUserId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [p, rows] = await Promise.all([getSecurityPolicy(token), listMfaUsers(token)]);
    setPolicy(p);
    setUsers(rows);
  }, [token]);

  useEffect(() => {
    void load().catch((e) => setError(e instanceof Error ? e.message : "Hata"));
  }, [load]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return users;
    return users.filter(
      (u) => u.username.toLowerCase().includes(q) || u.auth_source.toLowerCase().includes(q) || u.status.includes(q),
    );
  }, [users, filter]);

  async function onToggleMfa(enabled: boolean) {
    if (!policy) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const saved = await updateSecurityPolicy(token, { mfa_enabled: enabled });
      setPolicy(saved);
      setInfo(enabled ? t("security_mfa_enabled_msg") : t("security_mfa_disabled_msg"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  async function onReset(row: MfaUserStatus) {
    if (!window.confirm(t("security_mfa_reset_confirm", { username: row.username }))) return;
    setBusyUserId(row.user_id);
    setError(null);
    setInfo(null);
    try {
      await resetUserMfa(token, row.user_id);
      setInfo(t("security_mfa_reset_done", { username: row.username }));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusyUserId(null);
    }
  }

  return (
    <div className="space-y-5">
      <div className={panelClass}>
        <h3 className="text-sm font-medium">{t("security_mfa_title")}</h3>
        <p className="text-xs text-[var(--color-muted-foreground)]">{t("security_mfa_help")}</p>
        <p className="text-xs text-[var(--color-muted-foreground)]">{t("security_mfa_scope_help")}</p>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={Boolean(policy?.mfa_enabled)}
            disabled={!policy || busy}
            onCheckedChange={(v) => void onToggleMfa(!!v)}
          />
          {t("security_mfa_enable")}
        </label>
        {policy && !policy.mfa_enabled ? (
          <p className="text-xs text-amber-600 dark:text-amber-300">{t("security_mfa_off_hint")}</p>
        ) : null}
      </div>

      <div className={panelClass}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-medium">{t("security_mfa_users_title")}</h3>
            <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">{t("security_mfa_users_help")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              className="h-8 w-48"
              placeholder={t("security_mfa_filter")}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <Button type="button" size="sm" variant="outline" disabled={busy || busyUserId !== null} onClick={() => void load()}>
              {t("refresh")}
            </Button>
          </div>
        </div>

        {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
        {info ? <p className="text-sm text-emerald-300">{info}</p> : null}

        <div className="overflow-x-auto rounded-xl border border-[var(--color-border)]">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="border-b border-[var(--color-border)] bg-[var(--color-muted)]/20 text-[var(--color-muted-foreground)]">
              <tr>
                <th className="px-4 py-3 text-left font-medium">{t("username")}</th>
                <th className="px-4 py-3 text-left font-medium">{t("security_col_source")}</th>
                <th className="px-4 py-3 text-left font-medium">{t("security_col_mfa_status")}</th>
                <th className="px-4 py-3 text-left font-medium">{t("security_col_enrolled")}</th>
                <th className="px-4 py-3 text-left font-medium">{t("security_col_last_verified")}</th>
                <th className="sticky right-0 bg-[var(--color-card)] px-4 py-3 text-right font-medium">
                  {t("security_col_actions")}
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => {
                const canReset = row.status === "enabled" || row.status === "pending";
                return (
                  <tr key={row.user_id} className="border-t border-[var(--color-border)] hover:bg-[var(--color-muted)]/10">
                    <td className="px-4 py-3 font-mono text-xs align-middle">{row.username}</td>
                    <td className="px-4 py-3 align-middle">
                      <Badge variant="muted">{row.auth_source}</Badge>
                    </td>
                    <td className="px-4 py-3 align-middle">
                      <Badge variant={mfaStatusVariant(row.status)}>{mfaStatusLabel(row.status, t)}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs align-middle">{fmtDate(row.enrolled_at)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs align-middle">{fmtDate(row.last_verified_at)}</td>
                    <td className="sticky right-0 bg-[var(--color-card)] px-4 py-3 text-right align-middle">
                      <Button
                        size="sm"
                        variant="destructive"
                        disabled={!canReset || busyUserId !== null}
                        title={canReset ? t("security_mfa_reset") : t("security_mfa_reset_unavailable")}
                        onClick={() => void onReset(row)}
                      >
                        {busyUserId === row.user_id ? t("loading") : t("security_mfa_reset")}
                      </Button>
                    </td>
                  </tr>
                );
              })}
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-[var(--color-muted-foreground)]">
                    {t("no_records")}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export function SecurityTlsPanel() {
  const token = getToken()!;
  const t = useT();
  const [status, setStatus] = useState<TlsStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [certPem, setCertPem] = useState("");
  const [keyPem, setKeyPem] = useState("");
  const [chainPem, setChainPem] = useState("");

  const load = useCallback(async () => {
    const s = await getTlsStatus(token);
    setStatus(s);
    if (s.error) setError(s.error);
  }, [token]);

  useEffect(() => {
    void load().catch((e) => setError(e instanceof Error ? e.message : "Hata"));
  }, [load]);

  async function onToggle(enabled: boolean) {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const s = await setTlsEnabled(token, enabled);
      setStatus(s);
      setInfo(enabled ? t("security_tls_enabled_msg") : t("security_tls_disabled_msg"));
      if (s.error) setError(s.error);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  async function onUpload(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const s = await uploadTlsCert(token, {
        cert_pem: certPem,
        key_pem: keyPem,
        chain_pem: chainPem || undefined,
      });
      setStatus(s);
      setCertPem("");
      setKeyPem("");
      setChainPem("");
      setInfo(t("security_tls_uploaded"));
      if (s.error) setError(s.error);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  async function onSelfSigned() {
    if (!window.confirm(t("security_tls_self_signed_confirm"))) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const s = await regenerateSelfSignedTls(token);
      setStatus(s);
      setInfo(t("security_tls_self_signed_done"));
      if (s.error) setError(s.error);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className={panelClass}>
        <h3 className="text-sm font-medium">{t("security_tls_title")}</h3>
        <p className="text-xs text-[var(--color-muted-foreground)]">{t("security_tls_help")}</p>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={Boolean(status?.https_enabled)}
            disabled={!status || busy}
            onCheckedChange={(v) => void onToggle(!!v)}
          />
          {t("security_tls_enable")}
        </label>
        {status ? (
          <dl className="grid gap-2 text-xs sm:grid-cols-2">
            <div>
              <dt className="text-[var(--color-muted-foreground)]">{t("security_tls_source")}</dt>
              <dd className="font-mono">{status.source}</dd>
            </div>
            <div>
              <dt className="text-[var(--color-muted-foreground)]">{t("security_tls_ports")}</dt>
              <dd className="font-mono">
                HTTP :{status.http_port} · HTTPS :{status.https_port}
              </dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-[var(--color-muted-foreground)]">{t("security_tls_subject")}</dt>
              <dd className="break-all font-mono">{status.subject || "—"}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-[var(--color-muted-foreground)]">{t("security_tls_fingerprint")}</dt>
              <dd className="break-all font-mono text-[10px]">{status.fingerprint_sha256 || "—"}</dd>
            </div>
            <div>
              <dt className="text-[var(--color-muted-foreground)]">{t("security_tls_expires")}</dt>
              <dd className="font-mono">{status.not_after || "—"}</dd>
            </div>
            <div>
              <dt className="text-[var(--color-muted-foreground)]">{t("security_tls_dir")}</dt>
              <dd className="font-mono">{status.certs_dir}</dd>
            </div>
          </dl>
        ) : (
          <p className="text-sm text-[var(--color-muted-foreground)]">{t("loading")}</p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load()}>
            {t("refresh")}
          </Button>
          <Button type="button" size="sm" variant="secondary" disabled={busy} onClick={() => void onSelfSigned()}>
            {t("security_tls_regen_self_signed")}
          </Button>
        </div>
      </div>

      <form onSubmit={onUpload} className={panelClass}>
        <h3 className="text-sm font-medium">{t("security_tls_upload_title")}</h3>
        <p className="text-xs text-[var(--color-muted-foreground)]">{t("security_tls_upload_help")}</p>
        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
            {t("security_tls_cert_pem")}
          </label>
          <textarea
            className="h-28 w-full rounded-md border border-[var(--color-border)] bg-[var(--theme-inset)] p-2 font-mono text-xs"
            value={certPem}
            onChange={(e) => setCertPem(e.target.value)}
            required
            placeholder="-----BEGIN CERTIFICATE-----"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
            {t("security_tls_key_pem")}
          </label>
          <textarea
            className="h-28 w-full rounded-md border border-[var(--color-border)] bg-[var(--theme-inset)] p-2 font-mono text-xs"
            value={keyPem}
            onChange={(e) => setKeyPem(e.target.value)}
            required
            placeholder="-----BEGIN PRIVATE KEY-----"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
            {t("security_tls_chain_pem")}
          </label>
          <textarea
            className="h-20 w-full rounded-md border border-[var(--color-border)] bg-[var(--theme-inset)] p-2 font-mono text-xs"
            value={chainPem}
            onChange={(e) => setChainPem(e.target.value)}
            placeholder={t("security_tls_chain_optional")}
          />
        </div>
        <Button type="submit" disabled={busy}>
          {t("security_tls_upload_btn")}
        </Button>
      </form>

      {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
      {info ? <p className="text-sm text-emerald-300">{info}</p> : null}
    </div>
  );
}
