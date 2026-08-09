import { FormEvent, useEffect, useMemo, useState } from "react";
import { useOutletContext } from "react-router-dom";
import {
  assistantListModels,
  assistantTestConnection,
  changePassword,
  downloadDatabaseBackup,
  exportSettingsBackup,
  getAdminSettings,
  importDatabaseBackup,
  importSettingsBackup,
  updateAdminSettings,
  UserPublic,
} from "@/api";
import { CentrifySettings } from "@/components/CentrifySettings";
import { PackageReposSettings } from "@/components/PackageReposSettings";
import { SecurityAuthSettings } from "@/components/SecurityAuthSettings";
import {
  SecurityMfaPanel,
  SecurityPolicyPanel,
  SecuritySessionsPanel,
  SecurityTlsPanel,
} from "@/components/SecurityControlPanels";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useT } from "@/i18n/I18nProvider";
import { getToken } from "@/session";
import { cn } from "@/lib/utils";

type OutletCtx = { user: UserPublic; appName: string; setAppName?: (n: string) => void };

type AdminTab =
  | "general"
  | "automation"
  | "mail"
  | "assistant"
  | "repos"
  | "centrify"
  | "security"
  | "account"
  | "backup";
type UserTab = "account";
type SecuritySubTab = "auth" | "sessions" | "mfa" | "policy" | "tls";

function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function SettingsPage() {
  const { user, setAppName: setShellAppName } = useOutletContext<OutletCtx>();
  const token = getToken()!;
  const t = useT();
  const isAdmin = user.role === "admin";

  const [tab, setTab] = useState<AdminTab | UserTab>(isAdmin ? "general" : "account");
  const [securitySubTab, setSecuritySubTab] = useState<SecuritySubTab>("auth");

  const [appName, setAppName] = useState("");
  const [automationUsername, setAutomationUsername] = useState("root");
  const [automationUserKind, setAutomationUserKind] = useState<"root" | "local" | "ad">("root");
  const [automationPassword, setAutomationPassword] = useState("");
  const [passwordSet, setPasswordSet] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [passMsg, setPassMsg] = useState<string | null>(null);
  const [passError, setPassError] = useState<string | null>(null);
  const [smtpHost, setSmtpHost] = useState("");
  const [smtpTestMail, setSmtpTestMail] = useState("");
  const [mailMsg, setMailMsg] = useState<string | null>(null);
  const [mailError, setMailError] = useState<string | null>(null);
  const [assistantEnabled, setAssistantEnabled] = useState(false);
  const [ollamaMode, setOllamaMode] = useState<"gateway" | "direct">("direct");
  const [gatewayUrl, setGatewayUrl] = useState("");
  const [gatewayApiKey, setGatewayApiKey] = useState("");
  const [gatewayKeySet, setGatewayKeySet] = useState(false);
  const [directHost, setDirectHost] = useState("");
  const [directPort, setDirectPort] = useState("11434");
  const [assistantModel, setAssistantModel] = useState("");
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [asstMsg, setAsstMsg] = useState<string | null>(null);
  const [asstError, setAsstError] = useState<string | null>(null);
  const [asstBusy, setAsstBusy] = useState(false);

  const [backupBusy, setBackupBusy] = useState(false);
  const [backupMsg, setBackupMsg] = useState<string | null>(null);
  const [backupError, setBackupError] = useState<string | null>(null);
  const [includeSecrets, setIncludeSecrets] = useState(false);
  const [dbConfirm, setDbConfirm] = useState(false);

  const navItems = useMemo(() => {
    if (!isAdmin) return [{ id: "account" as const, label: t("settings_tab_account") }];
    return [
      { id: "general" as const, label: t("settings_tab_general") },
      { id: "automation" as const, label: t("settings_tab_automation") },
      { id: "mail" as const, label: t("settings_tab_mail") },
      { id: "assistant" as const, label: t("settings_tab_assistant") },
      { id: "repos" as const, label: t("settings_tab_repos") },
      { id: "centrify" as const, label: t("settings_tab_centrify") },
      { id: "security" as const, label: t("settings_tab_security") },
      { id: "account" as const, label: t("settings_tab_account") },
      { id: "backup" as const, label: t("settings_tab_backup") },
    ];
  }, [isAdmin, t]);

  useEffect(() => {
    if (!isAdmin) return;
    void getAdminSettings(token).then((s) => {
      setAppName(s.app_name);
      setAutomationUsername(s.automation_username);
      setAutomationUserKind(
        s.automation_user_kind === "local" || s.automation_user_kind === "ad"
          ? s.automation_user_kind
          : "root",
      );
      setPasswordSet(Boolean(s.automation_password_set));
      setSmtpHost(s.smtp_host || "");
      setSmtpTestMail(s.smtp_test_mail || "");
      setAssistantEnabled(Boolean(s.assistant_enabled));
      setOllamaMode(s.assistant_ollama_mode === "gateway" ? "gateway" : "direct");
      setGatewayUrl(s.assistant_gateway_url || "");
      setGatewayKeySet(Boolean(s.assistant_gateway_api_key_set));
      setDirectHost(s.assistant_direct_host || "");
      setDirectPort(String(s.assistant_direct_port || 11434));
      setAssistantModel(s.assistant_model || "");
    });
  }, [token, isAdmin]);

  async function onSaveGeneral(e: FormEvent) {
    e.preventDefault();
    if (!isAdmin) return;
    setError(null);
    setMsg(null);
    try {
      const s = await updateAdminSettings(token, { app_name: appName });
      setMsg(t("settings_saved"));
      setAppName(s.app_name);
      document.title = s.app_name;
      setShellAppName?.(s.app_name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    }
  }

  async function onSaveAutomation(e: FormEvent) {
    e.preventDefault();
    if (!isAdmin) return;
    setError(null);
    setMsg(null);
    try {
      const body: {
        automation_username: string;
        automation_user_kind: "root" | "local" | "ad";
        automation_password?: string;
      } = {
        automation_username: automationUsername,
        automation_user_kind: automationUsername.trim() === "root" ? "root" : automationUserKind,
      };
      if (automationPassword.trim()) {
        body.automation_password = automationPassword.trim();
      }
      const s = await updateAdminSettings(token, body);
      setMsg(t("settings_saved"));
      setAutomationUsername(s.automation_username);
      setAutomationUserKind(
        s.automation_user_kind === "local" || s.automation_user_kind === "ad"
          ? s.automation_user_kind
          : "root",
      );
      setPasswordSet(Boolean(s.automation_password_set));
      setAutomationPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    }
  }

  async function onSaveMail(e: FormEvent) {
    e.preventDefault();
    if (!isAdmin) return;
    setMailError(null);
    setMailMsg(null);
    try {
      const s = await updateAdminSettings(token, {
        smtp_host: smtpHost.trim(),
        smtp_test_mail: smtpTestMail.trim(),
      });
      setSmtpHost(s.smtp_host || "");
      setSmtpTestMail(s.smtp_test_mail || "");
      setMailMsg(t("settings_saved"));
    } catch (err) {
      setMailError(err instanceof Error ? err.message : "Hata");
    }
  }

  async function onSaveAssistant(e: FormEvent) {
    e.preventDefault();
    if (!isAdmin) return;
    setAsstError(null);
    setAsstMsg(null);
    setAsstBusy(true);
    try {
      const s = await persistAssistantSettings();
      setAssistantEnabled(Boolean(s.assistant_enabled));
      setOllamaMode(s.assistant_ollama_mode === "gateway" ? "gateway" : "direct");
      setGatewayUrl(s.assistant_gateway_url || "");
      setGatewayKeySet(Boolean(s.assistant_gateway_api_key_set));
      setGatewayApiKey("");
      setDirectHost(s.assistant_direct_host || "");
      setDirectPort(String(s.assistant_direct_port || 11434));
      setAssistantModel(s.assistant_model || "");
      setAsstMsg(t("settings_saved"));
      window.dispatchEvent(
        new CustomEvent("dropt-assistant-enabled", { detail: { enabled: Boolean(s.assistant_enabled) } }),
      );
    } catch (err) {
      setAsstError(err instanceof Error ? err.message : "Hata");
    } finally {
      setAsstBusy(false);
    }
  }

  async function persistAssistantSettings() {
    const port = Number(directPort) || 11434;
    const body: Parameters<typeof updateAdminSettings>[1] = {
      assistant_enabled: assistantEnabled,
      assistant_ollama_mode: ollamaMode,
      assistant_gateway_url: gatewayUrl.trim(),
      assistant_direct_host: directHost.trim(),
      assistant_direct_port: port,
      assistant_model: assistantModel.trim(),
    };
    if (gatewayApiKey.trim()) body.assistant_gateway_api_key = gatewayApiKey.trim();
    return updateAdminSettings(token, body);
  }

  async function onTestAssistant() {
    setAsstError(null);
    setAsstMsg(null);
    setAsstBusy(true);
    try {
      const s = await persistAssistantSettings();
      setGatewayApiKey("");
      setGatewayKeySet(Boolean(s.assistant_gateway_api_key_set));
      window.dispatchEvent(
        new CustomEvent("dropt-assistant-enabled", { detail: { enabled: Boolean(s.assistant_enabled) } }),
      );
      const r = await assistantTestConnection(token);
      if (r.ok) {
        setModelOptions(r.models || []);
        setAsstMsg(r.message);
        if (!assistantModel && r.models?.[0]) setAssistantModel(r.models[0]);
      } else {
        setAsstError(r.message);
      }
    } catch (err) {
      setAsstError(err instanceof Error ? err.message : "Bağlantı testi başarısız");
    } finally {
      setAsstBusy(false);
    }
  }

  async function onRefreshModels() {
    setAsstError(null);
    setAsstBusy(true);
    try {
      const models = await assistantListModels(token);
      setModelOptions(models);
      setAsstMsg(`${models.length} model listelendi`);
    } catch (err) {
      setAsstError(err instanceof Error ? err.message : "Model listesi alınamadı");
    } finally {
      setAsstBusy(false);
    }
  }

  async function onChangePortalPassword(e: FormEvent) {
    e.preventDefault();
    setPassError(null);
    setPassMsg(null);
    try {
      await changePassword(token, currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setPassMsg(t("password_updated"));
    } catch (err) {
      setPassError(err instanceof Error ? err.message : "Hata");
    }
  }

  async function onExportSettings() {
    setBackupError(null);
    setBackupMsg(null);
    setBackupBusy(true);
    try {
      const payload = await exportSettingsBackup(token, includeSecrets);
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      downloadJson(`dropt-settings-${stamp}.json`, payload);
      setBackupMsg(t("backup_settings_exported"));
    } catch (err) {
      setBackupError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBackupBusy(false);
    }
  }

  async function onImportSettingsFile(file: File | null) {
    if (!file) return;
    setBackupError(null);
    setBackupMsg(null);
    setBackupBusy(true);
    try {
      const text = await file.text();
      const json = JSON.parse(text) as Record<string, unknown>;
      const result = await importSettingsBackup(token, json);
      setBackupMsg(t("backup_settings_imported").replace("{n}", String(result.total)));
    } catch (err) {
      setBackupError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBackupBusy(false);
    }
  }

  async function onExportDatabase() {
    setBackupError(null);
    setBackupMsg(null);
    setBackupBusy(true);
    try {
      await downloadDatabaseBackup(token);
      setBackupMsg(t("backup_db_exported"));
    } catch (err) {
      setBackupError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBackupBusy(false);
    }
  }

  async function onImportDatabaseFile(file: File | null) {
    if (!file) return;
    if (!dbConfirm) {
      setBackupError(t("backup_db_confirm_required"));
      return;
    }
    setBackupError(null);
    setBackupMsg(null);
    setBackupBusy(true);
    try {
      const result = await importDatabaseBackup(token, file, true);
      setBackupMsg(result.detail || t("backup_db_imported"));
      setDbConfirm(false);
    } catch (err) {
      setBackupError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBackupBusy(false);
    }
  }

  const panelClass =
    "space-y-4 rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] p-6 shadow-sm";

  return (
    <div className="px-6 py-6">
      <h2 className="text-xl font-semibold">{t("settings_title")}</h2>
      <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">{t("settings_subtitle")}</p>

      <div className="mt-6 flex flex-col gap-6 lg:flex-row lg:items-start">
        <nav
          className="flex shrink-0 gap-1 overflow-x-auto lg:w-52 lg:flex-col lg:overflow-visible"
          aria-label={t("settings_title")}
        >
          {navItems.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={cn(
                "whitespace-nowrap rounded-xl px-3 py-2 text-left text-sm transition-colors",
                tab === item.id
                  ? "bg-[var(--color-accent)] font-medium text-[var(--color-accent-foreground)]"
                  : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-muted)]/40 hover:text-[var(--color-foreground)]",
              )}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className={cn("min-w-0 flex-1", tab === "security" ? "max-w-6xl" : "max-w-3xl")}>
          {isAdmin && tab === "general" ? (
            <form onSubmit={onSaveGeneral} className={panelClass}>
              <h3 className="text-sm font-medium">{t("settings_section_general")}</h3>
              <div>
                <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">{t("app_name")}</label>
                <Input value={appName} onChange={(e) => setAppName(e.target.value)} required />
              </div>
              {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
              {msg ? <p className="text-sm text-emerald-300">{msg}</p> : null}
              <Button type="submit">{t("save")}</Button>
            </form>
          ) : null}

          {isAdmin && tab === "automation" ? (
            <form onSubmit={onSaveAutomation} className={panelClass}>
              <h3 className="text-sm font-medium">{t("settings_section_automation")}</h3>
              <div>
                <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                  {t("automation_user_kind")}
                </label>
                <Select
                  value={automationUsername.trim() === "root" ? "root" : automationUserKind}
                  onValueChange={(v) => {
                    const kind = v as "root" | "local" | "ad";
                    setAutomationUserKind(kind);
                    if (kind === "root") setAutomationUsername("root");
                    else if (automationUsername.trim() === "root") setAutomationUsername("");
                  }}
                >
                  <SelectTrigger className="h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="root">{t("automation_user_kind_root")}</SelectItem>
                    <SelectItem value="local">{t("automation_user_kind_local")}</SelectItem>
                    <SelectItem value="ad">{t("automation_user_kind_ad")}</SelectItem>
                  </SelectContent>
                </Select>
                <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">
                  {t("automation_user_kind_help")}
                </p>
              </div>
              <div>
                <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                  {t("automation_user")}
                </label>
                <Input
                  className="font-mono"
                  value={automationUsername}
                  onChange={(e) => {
                    const v = e.target.value;
                    setAutomationUsername(v);
                    if (v.trim() === "root") setAutomationUserKind("root");
                  }}
                  required
                  disabled={automationUserKind === "root"}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                  {t("automation_password")} {passwordSet ? t("password_keep") : ""}
                </label>
                <Input
                  type="password"
                  autoComplete="new-password"
                  value={automationPassword}
                  onChange={(e) => setAutomationPassword(e.target.value)}
                  placeholder={passwordSet ? "••••••••" : t("automation_password_hint")}
                />
                <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">
                  {t("automation_password_help")}
                </p>
              </div>
              {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
              {msg ? <p className="text-sm text-emerald-300">{msg}</p> : null}
              <Button type="submit">{t("save")}</Button>
            </form>
          ) : null}

          {isAdmin && tab === "mail" ? (
            <form onSubmit={onSaveMail} className={panelClass}>
              <h3 className="text-sm font-medium">{t("settings_section_mail")}</h3>
              <p className="text-xs text-[var(--color-muted-foreground)]">{t("settings_mail_help")}</p>
              <div>
                <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">{t("smtp_host")}</label>
                <Input
                  className="font-mono"
                  value={smtpHost}
                  onChange={(e) => setSmtpHost(e.target.value)}
                  placeholder="bulksmtp.domain.local"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                  {t("smtp_test_mail")}
                </label>
                <Input
                  className="font-mono"
                  type="email"
                  value={smtpTestMail}
                  onChange={(e) => setSmtpTestMail(e.target.value)}
                  placeholder="ops@domain.local"
                />
              </div>
              {mailError ? <p className="text-sm text-[var(--color-destructive)]">{mailError}</p> : null}
              {mailMsg ? <p className="text-sm text-emerald-300">{mailMsg}</p> : null}
              <Button type="submit">{t("save")}</Button>
            </form>
          ) : null}

          {isAdmin && tab === "assistant" ? (
            <form onSubmit={onSaveAssistant} className={panelClass}>
              <h3 className="text-sm font-medium">{t("settings_section_assistant")}</h3>
              <p className="text-xs text-[var(--color-muted-foreground)]">{t("settings_assistant_help")}</p>

              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={assistantEnabled}
                  onChange={(e) => setAssistantEnabled(e.target.checked)}
                />
                {t("assistant_enabled")}
              </label>

              <div>
                <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                  {t("assistant_ollama_mode")}
                </label>
                <Select
                  value={ollamaMode}
                  onValueChange={(v) => setOllamaMode(v === "gateway" ? "gateway" : "direct")}
                >
                  <SelectTrigger className="h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="direct">{t("assistant_mode_direct")}</SelectItem>
                    <SelectItem value="gateway">{t("assistant_mode_gateway")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {ollamaMode === "gateway" ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="sm:col-span-2">
                    <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                      {t("assistant_gateway_url")}
                    </label>
                    <Input
                      className="font-mono"
                      value={gatewayUrl}
                      onChange={(e) => setGatewayUrl(e.target.value)}
                      placeholder="https://ollama-gateway.example.com"
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                      {t("assistant_gateway_api_key")} {gatewayKeySet ? t("password_keep") : ""}
                    </label>
                    <Input
                      type="password"
                      className="font-mono"
                      value={gatewayApiKey}
                      onChange={(e) => setGatewayApiKey(e.target.value)}
                      placeholder={gatewayKeySet ? "••••••••" : "sk-…"}
                      autoComplete="new-password"
                    />
                  </div>
                </div>
              ) : (
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="sm:col-span-2">
                    <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                      {t("assistant_direct_host")}
                    </label>
                    <Input
                      className="font-mono"
                      value={directHost}
                      onChange={(e) => setDirectHost(e.target.value)}
                      placeholder="192.168.1.50"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                      {t("assistant_direct_port")}
                    </label>
                    <Input
                      className="font-mono"
                      value={directPort}
                      onChange={(e) => setDirectPort(e.target.value)}
                      placeholder="11434"
                    />
                  </div>
                </div>
              )}

              <div>
                <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                  {t("assistant_model")}
                </label>
                {modelOptions.length ? (
                  <Select value={assistantModel || undefined} onValueChange={setAssistantModel}>
                    <SelectTrigger className="h-9 font-mono">
                      <SelectValue placeholder={t("assistant_model")} />
                    </SelectTrigger>
                    <SelectContent>
                      {modelOptions.map((m) => (
                        <SelectItem key={m} value={m}>
                          {m}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    className="font-mono"
                    value={assistantModel}
                    onChange={(e) => setAssistantModel(e.target.value)}
                    placeholder="llama3.2"
                  />
                )}
              </div>

              {asstError ? <p className="text-sm text-[var(--color-destructive)]">{asstError}</p> : null}
              {asstMsg ? <p className="text-sm text-emerald-300">{asstMsg}</p> : null}
              <div className="flex flex-wrap gap-2">
                <Button type="submit" disabled={asstBusy}>
                  {t("save")}
                </Button>
                <Button type="button" variant="outline" disabled={asstBusy} onClick={() => void onTestAssistant()}>
                  {t("assistant_test")}
                </Button>
                <Button type="button" variant="outline" disabled={asstBusy} onClick={() => void onRefreshModels()}>
                  {t("assistant_refresh_models")}
                </Button>
              </div>
            </form>
          ) : null}

          {isAdmin && tab === "repos" ? <PackageReposSettings /> : null}

          {isAdmin && tab === "centrify" ? <CentrifySettings /> : null}

          {isAdmin && tab === "security" ? (
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
              <nav className="flex shrink-0 gap-1 overflow-x-auto sm:w-44 sm:flex-col sm:overflow-visible">
                {(
                  [
                    ["auth", t("security_subtab_auth")],
                    ["sessions", t("security_subtab_sessions")],
                    ["mfa", t("security_subtab_mfa")],
                    ["tls", t("security_subtab_tls")],
                    ["policy", t("security_subtab_policy")],
                  ] as const
                ).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setSecuritySubTab(key)}
                    className={cn(
                      "whitespace-nowrap rounded-xl px-3 py-2 text-left text-sm transition-colors",
                      securitySubTab === key
                        ? "bg-[var(--color-accent)] font-medium text-[var(--color-accent-foreground)]"
                        : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-muted)]/40 hover:text-[var(--color-foreground)]",
                    )}
                  >
                    {label}
                  </button>
                ))}
              </nav>
              <div className="min-w-0 flex-1">
                {securitySubTab === "auth" ? <SecurityAuthSettings /> : null}
                {securitySubTab === "sessions" ? <SecuritySessionsPanel /> : null}
                {securitySubTab === "mfa" ? <SecurityMfaPanel /> : null}
                {securitySubTab === "tls" ? <SecurityTlsPanel /> : null}
                {securitySubTab === "policy" ? <SecurityPolicyPanel /> : null}
              </div>
            </div>
          ) : null}

          {tab === "account" ? (
            user.auth_source === "local" ? (
              <form onSubmit={onChangePortalPassword} className={panelClass}>
                <h3 className="text-sm font-medium">{t("portal_password_change")}</h3>
                <p className="text-xs text-[var(--color-muted-foreground)]">{t("portal_password_help")}</p>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                      {t("current_password")}
                    </label>
                    <Input
                      type="password"
                      autoComplete="current-password"
                      value={currentPassword}
                      onChange={(e) => setCurrentPassword(e.target.value)}
                      required
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                      {t("new_password")}
                    </label>
                    <Input
                      type="password"
                      autoComplete="new-password"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      minLength={6}
                      required
                    />
                  </div>
                </div>
                {passError ? <p className="text-sm text-[var(--color-destructive)]">{passError}</p> : null}
                {passMsg ? <p className="text-sm text-emerald-300">{passMsg}</p> : null}
                <Button type="submit">{t("update")}</Button>
              </form>
            ) : (
              <div className={panelClass}>
                <p className="text-sm text-[var(--color-muted-foreground)]">{t("portal_password_ad_hint")}</p>
              </div>
            )
          ) : null}

          {isAdmin && tab === "backup" ? (
            <div className="space-y-5">
              <div className={panelClass}>
                <h3 className="text-sm font-medium">{t("backup_settings_title")}</h3>
                <p className="text-xs text-[var(--color-muted-foreground)]">{t("backup_settings_help")}</p>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={includeSecrets}
                    onChange={(e) => setIncludeSecrets(e.target.checked)}
                  />
                  {t("backup_include_secrets")}
                </label>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" disabled={backupBusy} onClick={() => void onExportSettings()}>
                    {t("backup_export_settings")}
                  </Button>
                  <Button type="button" variant="outline" disabled={backupBusy} asChild>
                    <label className="cursor-pointer">
                      {t("backup_import_settings")}
                      <input
                        type="file"
                        accept="application/json,.json"
                        className="hidden"
                        onChange={(e) => {
                          const f = e.target.files?.[0] || null;
                          e.target.value = "";
                          void onImportSettingsFile(f);
                        }}
                      />
                    </label>
                  </Button>
                </div>
              </div>

              <div className={panelClass}>
                <h3 className="text-sm font-medium">{t("backup_db_title")}</h3>
                <p className="text-xs text-[var(--color-muted-foreground)]">{t("backup_db_help")}</p>
                <p className="text-xs text-amber-600 dark:text-amber-300">{t("backup_db_warning")}</p>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={dbConfirm}
                    onChange={(e) => setDbConfirm(e.target.checked)}
                  />
                  {t("backup_db_confirm")}
                </label>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" disabled={backupBusy} onClick={() => void onExportDatabase()}>
                    {t("backup_export_db")}
                  </Button>
                  <Button type="button" variant="outline" disabled={backupBusy || !dbConfirm} asChild>
                    <label className={cn("cursor-pointer", (!dbConfirm || backupBusy) && "pointer-events-none opacity-50")}>
                      {t("backup_import_db")}
                      <input
                        type="file"
                        accept=".gz,.sql,application/gzip,application/sql"
                        className="hidden"
                        disabled={!dbConfirm || backupBusy}
                        onChange={(e) => {
                          const f = e.target.files?.[0] || null;
                          e.target.value = "";
                          void onImportDatabaseFile(f);
                        }}
                      />
                    </label>
                  </Button>
                </div>
              </div>

              {backupError ? <p className="text-sm text-[var(--color-destructive)]">{backupError}</p> : null}
              {backupMsg ? <p className="text-sm text-emerald-300">{backupMsg}</p> : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
