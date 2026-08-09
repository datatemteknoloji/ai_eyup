const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

async function readError(res: Response): Promise<string> {
  const data = await res.json().catch(() => null);
  if (typeof data?.detail === "string") return data.detail;
  return "İstek başarısız";
}

export type UserPublic = {
  id: number;
  username: string;
  role: "admin" | "operator" | "none";
  auth_source: string;
  is_active: boolean;
  theme?: "dark" | "light" | string;
  locale?: "tr" | "en" | string;
  last_login_at: string | null;
  mfa_enabled?: boolean;
};

export type LoginResponse = {
  token?: {
    access_token: string;
    token_type: string;
    expires_in_minutes: number;
  };
  user?: UserPublic;
  mfa_required?: boolean;
  mfa_enrollment_required?: boolean;
  mfa_token?: string;
};

export type PublicSettings = {
  app_name: string;
  version: string;
  sso_enabled?: boolean;
  ad_enabled?: boolean;
  sso_mode?: string;
  assistant_enabled?: boolean;
};

export type AdminSettings = {
  app_name: string;
  version: string;
  automation_username: string;
  automation_user_kind?: "root" | "local" | "ad" | string;
  automation_password_set: boolean;
  admin_terminal_user: string;
  smtp_host?: string;
  smtp_test_mail?: string;
  assistant_enabled?: boolean;
  assistant_ollama_mode?: "gateway" | "direct" | string;
  assistant_gateway_url?: string;
  assistant_gateway_api_key_set?: boolean;
  assistant_direct_host?: string;
  assistant_direct_port?: number;
  assistant_model?: string;
};

export type AssistantChatResult = {
  operation_id: string | null;
  title_tr: string | null;
  route: string | null;
  deep_link?: string | null;
  server_ids?: number[];
  server_hostnames?: string[];
  reference_server_ids?: number[];
  reference_hostnames?: string[];
  confidence: number;
  summary_tr: string;
  checklist_tr: string[];
  clarifying_questions: string[];
  out_of_scope_note?: string | null;
  required_inputs?: string[];
  analysis_tr?: string;
  analysis_probed?: boolean;
  source: string;
};

export type MailSettings = {
  smtp_host: string;
  smtp_test_mail: string;
};

export async function getHealth(): Promise<{ status: string; service: string; version: string }> {
  const res = await fetch(apiUrl("/health"));
  if (!res.ok) throw new Error("API sağlık kontrolü başarısız");
  return res.json();
}

export async function getPublicSettings(): Promise<PublicSettings> {
  const res = await fetch(apiUrl("/api/settings/public"));
  if (!res.ok) throw new Error("Ayarlar okunamadı");
  return res.json();
}

export async function getAdminSettings(token: string): Promise<AdminSettings> {
  const res = await fetch(apiUrl("/api/settings"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const res = await fetch(apiUrl("/api/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type MfaEnrollStartResponse = { secret: string; otpauth_url: string };

export async function mfaEnrollStart(mfaToken: string): Promise<MfaEnrollStartResponse> {
  const res = await fetch(apiUrl("/api/auth/mfa/enroll/start"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mfa_token: mfaToken }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function mfaEnrollConfirm(mfaToken: string, code: string): Promise<LoginResponse> {
  const res = await fetch(apiUrl("/api/auth/mfa/enroll/confirm"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mfa_token: mfaToken, code }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function mfaVerify(mfaToken: string, code: string): Promise<LoginResponse> {
  const res = await fetch(apiUrl("/api/auth/mfa/verify"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mfa_token: mfaToken, code }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function getMe(token: string): Promise<UserPublic> {
  const res = await fetch(apiUrl("/api/auth/me"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Oturum doğrulanamadı");
  return res.json();
}

export async function updatePreferences(
  token: string,
  body: { theme?: "dark" | "light"; locale?: "tr" | "en" },
): Promise<UserPublic> {
  const res = await fetch(apiUrl("/api/auth/preferences"), {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function logoutApi(token: string): Promise<void> {
  const res = await fetch(apiUrl("/api/auth/logout"), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
}

export async function changePassword(
  token: string,
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  const res = await fetch(apiUrl("/api/auth/change-password"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
  if (!res.ok) throw new Error(await readError(res));
}

export async function updateAdminSettings(
  token: string,
  body: {
    app_name?: string;
    automation_username?: string;
    automation_user_kind?: "root" | "local" | "ad" | string;
    automation_password?: string;
    smtp_host?: string;
    smtp_test_mail?: string;
    assistant_enabled?: boolean;
    assistant_ollama_mode?: string;
    assistant_gateway_url?: string;
    assistant_gateway_api_key?: string;
    assistant_direct_host?: string;
    assistant_direct_port?: number;
    assistant_model?: string;
  },
): Promise<AdminSettings> {
  const res = await fetch(apiUrl("/api/settings"), {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type SettingsBackupPayload = {
  format: string;
  exported_at: string;
  app_version: string;
  include_secrets: boolean;
  redacted_keys: string[];
  settings: Record<string, string>;
};

export async function exportSettingsBackup(
  token: string,
  includeSecrets = false,
): Promise<SettingsBackupPayload> {
  const qs = includeSecrets ? "?include_secrets=true" : "";
  const res = await fetch(apiUrl(`/api/settings/backup/settings${qs}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function importSettingsBackup(
  token: string,
  payload: SettingsBackupPayload | Record<string, unknown>,
): Promise<{ ok: boolean; created: number; updated: number; total: number }> {
  const res = await fetch(apiUrl("/api/settings/backup/settings"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function downloadDatabaseBackup(token: string): Promise<void> {
  const res = await fetch(apiUrl("/api/settings/backup/database"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") || "";
  const match = /filename="?([^"]+)"?/.exec(cd);
  const filename = match?.[1] || "dttportal-backup.sql.gz";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function importDatabaseBackup(
  token: string,
  file: File,
  confirm = true,
): Promise<{ ok: boolean; detail: string; log_tail?: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const qs = confirm ? "?confirm=true" : "";
  const res = await fetch(apiUrl(`/api/settings/backup/database${qs}`), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: fd,
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function assistantChat(token: string, message: string): Promise<AssistantChatResult> {
  const res = await fetch(apiUrl("/api/assistant/chat"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function assistantTestConnection(
  token: string,
): Promise<{ ok: boolean; message: string; models: string[] }> {
  const res = await fetch(apiUrl("/api/assistant/test"), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function assistantListModels(token: string): Promise<string[]> {
  const res = await fetch(apiUrl("/api/assistant/models"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  const data = await res.json();
  return data.models || [];
}

export async function assistantFeedback(
  token: string,
  body: {
    message: string;
    suggested_operation_id?: string;
    correct_operation_id: string;
  },
): Promise<void> {
  const res = await fetch(apiUrl("/api/assistant/feedback"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
}

export async function assistantCapabilities(
  token: string,
): Promise<{ id: string; title_tr: string; route: string }[]> {
  const res = await fetch(apiUrl("/api/assistant/capabilities"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  const data = await res.json();
  return data.capabilities || [];
}

export type AssistantHistoryItem = {
  id: number;
  role: "user" | "assistant" | string;
  content: string;
  operation_id?: string;
  result?: AssistantChatResult | null;
  created_at?: string | null;
};

export async function assistantHistory(token: string): Promise<AssistantHistoryItem[]> {
  const res = await fetch(apiUrl("/api/assistant/history"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  const data = await res.json();
  return data.items || [];
}

export async function assistantHistoryClear(token: string): Promise<void> {
  const res = await fetch(apiUrl("/api/assistant/history"), {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
}

export async function getMailSettings(token: string): Promise<MailSettings> {
  const res = await fetch(apiUrl("/api/settings/mail"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type PortalUser = {
  id: number;
  username: string;
  role: "admin" | "operator" | "none";
  auth_source: string;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
};

export type IdentitySettings = {
  ad_enabled: boolean;
  ad_ldap_url: string;
  ad_host: string;
  ad_port: number;
  ad_use_ssl: boolean;
  ad_tls_verify: boolean;
  ad_ca_cert_set: boolean;
  ad_ca_cert_pem: string;
  ad_domain: string;
  ad_base_dn: string;
  ad_bind_dn: string;
  ad_bind_password_set: boolean;
  ad_user_filter: string;
  ad_admin_group: string;
  ad_operator_group: string;
  sso_enabled: boolean;
  sso_mode: string;
  kerberos_realm: string;
  kerberos_spn: string;
  kerberos_keytab_uploaded: boolean;
  kerberos_keytab_path: string;
  sso_issuer: string;
  sso_client_id: string;
  sso_client_secret_set: boolean;
  sso_redirect_uri: string;
  sso_scopes: string;
  sso_admin_group: string;
  sso_operator_group: string;
  sso_frontend_redirect: string;
};

export async function listPortalUsers(token: string): Promise<{ items: PortalUser[]; total: number }> {
  const res = await fetch(apiUrl("/api/portal-users"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function createPortalUser(
  token: string,
  body: { username: string; password: string; role: "admin" | "operator"; is_active?: boolean },
): Promise<PortalUser> {
  const res = await fetch(apiUrl("/api/portal-users"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function updatePortalUser(
  token: string,
  id: number,
  body: { role?: "admin" | "operator" | "none"; is_active?: boolean; password?: string },
): Promise<PortalUser> {
  const res = await fetch(apiUrl(`/api/portal-users/${id}`), {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function syncAdPortalUsers(token: string): Promise<{
  ok: boolean;
  scanned: number;
  created: number;
  updated: number;
  skipped_local: number;
}> {
  const res = await fetch(apiUrl("/api/portal-users/sync-ad"), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function uploadKerberosKeytab(token: string, file: File): Promise<IdentitySettings> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(apiUrl("/api/identity/kerberos/keytab"), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: fd,
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function testKerberosConfig(token: string): Promise<{ ok: boolean; message: string }> {
  const res = await fetch(apiUrl("/api/identity/kerberos/test"), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function deletePortalUser(token: string, id: number): Promise<void> {
  const res = await fetch(apiUrl(`/api/portal-users/${id}`), {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
}

export async function getIdentitySettings(token: string): Promise<IdentitySettings> {
  const res = await fetch(apiUrl("/api/identity"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function updateIdentitySettings(
  token: string,
  body: Record<string, unknown>,
): Promise<IdentitySettings> {
  const res = await fetch(apiUrl("/api/identity"), {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function testAdConnection(
  token: string,
  body: { username?: string; password?: string } = {},
): Promise<{
  ok: boolean;
  message: string;
  role?: string | null;
  groups?: string[];
  resolved_host?: string | null;
  ldap_url?: string | null;
}> {
  const res = await fetch(apiUrl("/api/identity/test-ad"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export function ssoStartUrl(): string {
  return apiUrl("/api/auth/sso/start");
}

/** @deprecated use updateAdminSettings */
export async function updateAppName(token: string, appName: string): Promise<PublicSettings> {
  const updated = await updateAdminSettings(token, { app_name: appName });
  return { app_name: updated.app_name, version: updated.version };
}

export type ServerStatus = "unknown" | "ready" | "unreachable" | "disabled";

export type ServerPublic = {
  id: number;
  hostname: string;
  ip: string;
  port: number;
  status: ServerStatus;
  tags: string;
  description: string;
  username: string;
  has_password: boolean;
  ssh_key_installed: boolean;
  os_pretty?: string;
  machine_type?: string;
  virtualization?: string;
  last_connection_message: string;
  connection_ok?: boolean | null;
  created_at: string;
  updated_at: string;
};

export type ServerCreatePayload = {
  hostname: string;
  ip: string;
  password: string;
  port?: number;
  tags?: string;
  description?: string;
};

export type ServerUpdatePayload = {
  hostname?: string;
  ip?: string;
  password?: string;
  port?: number;
  tags?: string;
  description?: string;
  test_connection?: boolean;
};

export type ServerListParams = {
  q?: string;
  status?: ServerStatus | "";
  ssh_key_installed?: "" | "true" | "false";
  page?: number;
  page_size?: number;
};

export type ServerListResponse = {
  items: ServerPublic[];
  total: number;
  page: number;
  page_size: number;
};

export async function getServerDefaults(token: string): Promise<{ username: string; port: number }> {
  const res = await fetch(apiUrl("/api/servers/defaults"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function listServers(
  token: string,
  params: ServerListParams = {},
): Promise<ServerListResponse> {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.status) qs.set("status", params.status);
  if (params.ssh_key_installed) qs.set("ssh_key_installed", params.ssh_key_installed);
  qs.set("page", String(params.page ?? 1));
  qs.set("page_size", String(params.page_size ?? 50));
  const res = await fetch(apiUrl(`/api/servers?${qs.toString()}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function getServer(token: string, id: number): Promise<ServerPublic> {
  const res = await fetch(apiUrl(`/api/servers/${id}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type ServerFacts = {
  ok: boolean;
  error: string;
  hostname: string;
  short_hostname: string;
  ip: string;
  machine_type: string;
  virtualization: string;
  chassis: string;
  os_name: string;
  os_version: string;
  os_pretty: string;
  kernel: string;
  arch: string;
  uptime_sec: number | null;
  uptime_human: string;
  cpus: number | null;
  memory_total_mb: number | null;
  memory_avail_mb: number | null;
  loadavg: string;
  reachable: boolean;
};

export async function getServerFacts(token: string, id: number): Promise<ServerFacts> {
  const res = await fetch(apiUrl(`/api/servers/${id}/facts`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function createServer(token: string, body: ServerCreatePayload): Promise<ServerPublic> {
  const res = await fetch(apiUrl("/api/servers"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type ServerImportResult = {
  ok: boolean;
  total_rows: number;
  created: number;
  ready: number;
  unreachable: number;
  skipped: number;
  items: Array<{
    hostname: string;
    ip: string;
    status: string;
    message: string;
    server_id: number | null;
  }>;
};

export type ServerImportRowResult = {
  hostname: string;
  ip: string;
  status: string;
  message: string;
  server_id: number | null;
};

export async function parseServerImport(
  token: string,
  file: File,
): Promise<{ rows: Array<{ hostname: string; ip: string }>; total: number }> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(apiUrl("/api/servers/import/parse"), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: fd,
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function importServerRow(
  token: string,
  body: { hostname: string; ip: string },
): Promise<ServerImportRowResult> {
  const res = await fetch(apiUrl("/api/servers/import/row"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function importServers(token: string, file: File): Promise<ServerImportResult> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(apiUrl("/api/servers/import"), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: fd,
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function updateServer(
  token: string,
  id: number,
  body: ServerUpdatePayload,
): Promise<ServerPublic> {
  const res = await fetch(apiUrl(`/api/servers/${id}`), {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function testServerConnection(token: string, id: number): Promise<ServerPublic> {
  const res = await fetch(apiUrl(`/api/servers/${id}/test-connection`), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function deleteServer(token: string, id: number): Promise<void> {
  const res = await fetch(apiUrl(`/api/servers/${id}`), {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
}

export type JobStatus =
  | "draft"
  | "previewed"
  | "approved"
  | "running"
  | "success"
  | "failed"
  | "partial"
  | "cancelled";

export type JobRunStatus = "pending" | "running" | "success" | "failed" | "skipped";

export type JobRunPublic = {
  id: number;
  job_id: number;
  target_server_id: number;
  hostname: string;
  ip: string;
  status: JobRunStatus;
  dry_run: boolean;
  summary_tr: string;
  planned_commands: string[];
  before_state: Record<string, unknown>;
  after_state: Record<string, unknown>;
  stdout: string;
  stderr: string;
  error_message: string;
  started_at: string | null;
  finished_at: string | null;
};

export type PreviewPublic = {
  id: number;
  job_id: number;
  summary_tr: string;
  risk_notes: string;
  planned_commands: string[];
  host_summaries: Array<{
    server_id: number;
    hostname: string;
    ip: string;
    ok: boolean;
    summary_tr: string;
    planned_commands: string[];
    error?: string;
  }>;
  technical_detail: string;
  created_at: string;
};

export type JobPublic = {
  id: number;
  module: string;
  action: string;
  status: JobStatus;
  talep_id: string;
  title: string;
  summary_tr: string;
  created_by_username: string;
  created_by_role: string;
  server_ids: number[];
  hostnames?: string[];
  payload: Record<string, unknown>;
  dry_run: boolean;
  progress_done: number;
  progress_total: number;
  error_message: string;
  created_at: string;
  updated_at: string;
  previewed_at: string | null;
  applied_at: string | null;
  finished_at: string | null;
  preview?: PreviewPublic | null;
  runs?: JobRunPublic[];
};

export type JobListResponse = {
  items: JobPublic[];
  total: number;
  page: number;
  page_size: number;
};

export type AuditPublic = {
  id: number;
  user_id: number | null;
  username: string;
  role: string;
  client_ip: string;
  target_server_id: number | null;
  hostname: string;
  ip: string;
  talep_id: string;
  job_id: number | null;
  action: string;
  status: "success" | "failed" | "info";
  message: string;
  before_state: Record<string, unknown>;
  after_state: Record<string, unknown>;
  output: string;
  created_at: string;
};

export type AuditListResponse = {
  items: AuditPublic[];
  total: number;
  page: number;
  page_size: number;
};

export type LocalUserPublic = {
  username: string;
  uid: number | null;
  home: string;
  shell: string;
  groups: string[];
  status: string;
  protected: boolean;
};

export async function listLocalUsers(token: string, serverId: number): Promise<LocalUserPublic[]> {
  const res = await fetch(apiUrl(`/api/servers/${serverId}/local-users`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function createJob(
  token: string,
  body: {
    module?: string;
    action: string;
    talep_id: string;
    server_ids: number[];
    payload: Record<string, unknown>;
  },
): Promise<JobPublic> {
  const res = await fetch(apiUrl("/api/jobs"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ module: body.module ?? "local_user", ...body }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function listJobs(
  token: string,
  params: { q?: string; status?: JobStatus | ""; page?: number; page_size?: number } = {},
): Promise<JobListResponse> {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.status) qs.set("status", params.status);
  qs.set("page", String(params.page ?? 1));
  qs.set("page_size", String(params.page_size ?? 25));
  const res = await fetch(apiUrl(`/api/jobs?${qs}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function getJob(token: string, id: number): Promise<JobPublic> {
  const res = await fetch(apiUrl(`/api/jobs/${id}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function previewJob(token: string, id: number): Promise<JobPublic> {
  const res = await fetch(apiUrl(`/api/jobs/${id}/preview`), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function applyJob(
  token: string,
  id: number,
  opts: { sync?: boolean; only_failed?: boolean } = {},
): Promise<JobPublic> {
  const qs = new URLSearchParams();
  if (opts.sync) qs.set("sync", "true");
  if (opts.only_failed) qs.set("only_failed", "true");
  const res = await fetch(apiUrl(`/api/jobs/${id}/apply?${qs}`), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function listAudit(
  token: string,
  params: { q?: string; talep_id?: string; job_id?: number; page?: number; page_size?: number } = {},
): Promise<AuditListResponse> {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.talep_id) qs.set("talep_id", params.talep_id);
  if (params.job_id) qs.set("job_id", String(params.job_id));
  qs.set("page", String(params.page ?? 1));
  qs.set("page_size", String(params.page_size ?? 50));
  const res = await fetch(apiUrl(`/api/audit?${qs}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type LogTemplate = {
  id: string;
  label: string;
  paths: string[];
  include_journal: boolean;
};

export async function listLogTemplates(token: string): Promise<LogTemplate[]> {
  const res = await fetch(apiUrl("/api/jobs/meta/log-templates"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export function jobDownloadUrl(jobId: number, runId?: number): string {
  const qs = runId ? `?run_id=${runId}` : "";
  return apiUrl(`/api/jobs/${jobId}/download${qs}`);
}

export async function downloadJobArtifact(token: string, jobId: number, runId?: number): Promise<void> {
  const qs = runId ? `?run_id=${runId}` : "";
  const res = await fetch(apiUrl(`/api/jobs/${jobId}/download${qs}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") || "";
  const match = /filename="?([^"]+)"?/.exec(cd);
  const filename = match?.[1] || `logs-job-${jobId}.tgz`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export type HostnameState = {
  short_name: string;
  domain: string;
  fqdn: string;
  hosts_preview: string;
  warnings: string[];
  ip: string;
};

export async function getHostnameState(token: string, serverId: number): Promise<HostnameState> {
  const res = await fetch(apiUrl(`/api/servers/${serverId}/hostname`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type SudoTemplate = { id: string; label: string; commands: string[] };
export type FilesystemRow = {
  source: string;
  fstype: string;
  use_pct: string;
  mount: string;
  blacklisted: boolean;
  extendable: boolean;
  vg_name?: string;
  lv_name?: string;
  on_root_vg?: boolean;
  /** df -h Size / Used / Avail */
  size?: string;
  used?: string;
  avail?: string;
  size_kb?: number;
  avail_kb?: number;
  vg_free_gb?: number;
  vg_size_gb?: number;
};

export type VolumeGroup = {
  name: string;
  size_gb: number;
  free_gb: number;
  is_root_vg?: boolean;
  selectable?: boolean;
};

export type FsFreeDisk = {
  alias: string;
  wwid: string;
  size: string;
  size_bytes: number;
  usable: boolean;
  device: string;
  mode?: string;
};

export type FilesystemInventory = {
  root_vg: string;
  volume_groups: VolumeGroup[];
  filesystems: FilesystemRow[];
  free_disks: FsFreeDisk[];
  disk_mode: string;
  machine_type: string;
  cached_disks?: boolean;
  cached?: boolean;
};
export type PathMode = { id: string; label: string; mode: string };
export type SystemOverview = {
  generated_at: string;
  docker_available: boolean;
  counts: { jobs: number; audit: number };
  containers: Array<{ name: string; state: string; status: string; image: string }>;
  recent_jobs: Array<{ id: number; title: string; status: string; talep_id: string; updated_at: string | null }>;
  recent_audit: Array<Record<string, unknown>>;
};

export async function listSudoTemplates(token: string): Promise<SudoTemplate[]> {
  const res = await fetch(apiUrl("/api/ops/sudo-templates"), { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type SudoRuleRow = {
  who: string;
  is_group: boolean;
  hosts: string;
  runas: string;
  nopasswd: boolean;
  commands: string[];
  raw: string;
  source_file: string;
};

export async function listServerSudoRules(
  token: string,
  serverId: number,
  who?: string,
): Promise<{ server_id: number; hostname: string; rules: SudoRuleRow[] }> {
  const qs = new URLSearchParams();
  if (who?.trim()) qs.set("who", who.trim());
  const q = qs.toString() ? `?${qs}` : "";
  const res = await fetch(apiUrl(`/api/ops/servers/${serverId}/sudo-rules${q}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function lookupSudoRules(
  token: string,
  hostname: string,
  who: string,
): Promise<{ server_id: number; hostname: string; who: string; rules: SudoRuleRow[] }> {
  const qs = new URLSearchParams({ hostname: hostname.trim(), who: who.trim() });
  const res = await fetch(apiUrl(`/api/ops/sudo-lookup?${qs}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type SudoWhichResult = {
  server_id: number;
  hostname: string;
  query: string;
  path: string;
  source: "user" | "root" | "";
  as_user: string;
  user_exists?: boolean;
  user_tried?: boolean;
  fallback: boolean;
  note: string;
};

export async function sudoWhich(
  token: string,
  serverId: number,
  q: string,
  asUser?: string,
): Promise<SudoWhichResult> {
  const qs = new URLSearchParams({ q: q.trim() });
  if (asUser?.trim()) qs.set("as_user", asUser.trim());
  const res = await fetch(apiUrl(`/api/ops/servers/${serverId}/sudo-which?${qs}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}


export type SystemServiceRow = {
  unit: string;
  name: string;
  active: string;
  sub_state: string;
  enabled: string;
  load_state: string;
  fragment_path: string;
  description: string;
  operable: boolean;
};

export type SystemServicesResponse = {
  server_id: number;
  hostname: string;
  services: SystemServiceRow[];
};

export async function listSystemServices(token: string, serverId: number): Promise<SystemServicesResponse> {
  const res = await fetch(apiUrl(`/api/ops/servers/${serverId}/services`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function listFilesystems(token: string, serverId: number): Promise<FilesystemRow[]> {
  const res = await fetch(apiUrl(`/api/ops/servers/${serverId}/filesystems`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function listVolumeGroups(token: string, serverId: number): Promise<VolumeGroup[]> {
  const res = await fetch(apiUrl(`/api/ops/servers/${serverId}/volume-groups`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function getFilesystemInventory(
  token: string,
  serverId: number,
  opts?: { refresh?: boolean },
): Promise<FilesystemInventory> {
  const qs = opts?.refresh ? "?refresh=true" : "";
  const res = await fetch(apiUrl(`/api/ops/servers/${serverId}/filesystem-inventory${qs}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export function terminalWsUrl(serverId: number, params: Record<string, string>): string {
  const qs = new URLSearchParams(params);
  const base = API_BASE || window.location.origin;
  const proto = base.startsWith("https") ? "wss" : "ws";
  const host = base.replace(/^https?:\/\//, "").replace(/\/$/, "") || window.location.host;
  // relative API_BASE → same host
  if (!API_BASE) {
    const p = window.location.protocol === "https:" ? "wss" : "ws";
    return `${p}://${window.location.host}/api/terminal/ws/${serverId}?${qs}`;
  }
  return `${proto}://${host}/api/terminal/ws/${serverId}?${qs}`;
}

export function jobEventsWsUrl(jobId: number, token: string): string {
  const qs = new URLSearchParams({ token });
  if (!API_BASE) {
    const p = window.location.protocol === "https:" ? "wss" : "ws";
    return `${p}://${window.location.host}/api/jobs/ws/${jobId}?${qs}`;
  }
  const proto = API_BASE.startsWith("https") ? "wss" : "ws";
  const host = API_BASE.replace(/^https?:\/\//, "").replace(/\/$/, "");
  return `${proto}://${host}/api/jobs/ws/${jobId}?${qs}`;
}

export async function listPathWhitelist(token: string): Promise<Array<{ path: string }>> {
  const res = await fetch(apiUrl("/api/ops/path-whitelist"), { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function listPathModes(token: string): Promise<PathMode[]> {
  const res = await fetch(apiUrl("/api/ops/path-modes"), { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type SysctlTemplate = { id: string; label: string; params: string[]; reboot_hint?: boolean };

export async function listSysctlTemplates(token: string): Promise<SysctlTemplate[]> {
  const res = await fetch(apiUrl("/api/ops/sysctl-templates"), { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function listSysctlAllowed(token: string): Promise<string[]> {
  const res = await fetch(apiUrl("/api/ops/sysctl-allowed"), { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type SysctlCurrentResult = {
  values: Record<string, string>;
  cached: boolean;
  server_id: number;
};

export async function getServerSysctl(
  token: string,
  serverId: number,
  opts: { keys?: string[]; refresh?: boolean } = {},
): Promise<SysctlCurrentResult> {
  const qs = new URLSearchParams();
  if (opts.keys?.length) qs.set("keys", opts.keys.join(","));
  if (opts.refresh) qs.set("refresh", "true");
  const q = qs.toString() ? `?${qs}` : "";
  const res = await fetch(apiUrl(`/api/ops/servers/${serverId}/sysctl${q}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type LimitsEntry = {
  domain: string;
  type: string;
  item: string;
  value: string;
  source?: string;
};

export type LimitsCurrentResult = {
  entries: LimitsEntry[];
  cached: boolean;
  server_id: number;
  ulimit?: {
    user: string;
    soft: Record<string, string>;
    hard: Record<string, string>;
    ok: boolean;
    stderr?: string;
  };
  ulimit_error?: string;
};

export async function listLimitsItems(token: string): Promise<string[]> {
  const res = await fetch(apiUrl("/api/ops/limits-items"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function getServerLimits(
  token: string,
  serverId: number,
  opts: { refresh?: boolean; user?: string } = {},
): Promise<LimitsCurrentResult> {
  const qs = new URLSearchParams();
  if (opts.refresh) qs.set("refresh", "true");
  if (opts.user?.trim()) qs.set("user", opts.user.trim());
  const q = qs.toString() ? `?${qs}` : "";
  const res = await fetch(apiUrl(`/api/ops/servers/${serverId}/limits${q}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type VlanPool = { vlan_id: number; label: string; network: string; gateway: string };
export type NetInterface = {
  name: string;
  is_mgmt?: boolean;
  hidden?: boolean;
  state?: string;
  usable?: boolean;
};

export async function getNetworkInterfaces(
  token: string,
  serverId: number,
): Promise<{
  interfaces: NetInterface[];
  next_bond_name: string;
  bond_modes: { value: string; label: string }[];
}> {
  const res = await fetch(apiUrl(`/api/ops/servers/${serverId}/network-interfaces`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type IpChangeIface = {
  name: string;
  ip: string;
  subnet: number;
  ip_cidr: string;
  gateway: string;
  vlan_id: number | null;
  conn_name: string;
  is_primary: boolean;
  primary_reasons?: string[];
  has_vlan: boolean;
};

export type IpChangeNslookup = {
  forward_short?: string;
  forward_fqdn?: string;
  resolved_ip?: string;
  resolved_fqdn?: string;
  reverse_portal_ip?: { ok?: boolean; name?: string; error?: string };
};

export type IpChangeInventory = {
  server_id: number;
  hostname: string;
  portal_ip: string;
  short_name: string;
  domain: string;
  fqdn: string;
  dns: string[];
  dns_search: string[];
  interfaces: IpChangeIface[];
  default_route?: { raw?: string; dev?: string; src?: string };
  nslookup?: IpChangeNslookup;
};

export async function getIpChangeInventory(
  token: string,
  serverId: number,
): Promise<IpChangeInventory> {
  const res = await fetch(apiUrl(`/api/ops/servers/${serverId}/ip-change`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}
export type AsmDisk = {
  alias: string;
  wwid: string;
  size?: string;
  size_bytes?: number;
  usable: boolean;
  device: string;
  is_lv?: boolean;
  mode?: string;
  /** cluster modunda: her iki node'da da var mı */
  scope?: "shared" | "local";
};

export type AsmDiskGroup = {
  label: string;
  count: number;
  samples?: string[];
};

export type AsmScanResult = {
  disks: AsmDisk[];
  groups?: AsmDiskGroup[];
  /** @deprecated recent panel kaldırıldı; boş gelebilir */
  recent?: unknown[];
  cached: boolean;
  server_id: number;
  disk_mode?: "multipath" | "sd" | string;
  machine_type?: string;
};

export async function scanAsmDisks(
  token: string,
  serverId: number,
  opts: { refresh?: boolean } = {},
): Promise<AsmScanResult> {
  const qs = new URLSearchParams();
  if (opts.refresh) qs.set("refresh", "true");
  const res = await fetch(apiUrl(`/api/ops/servers/${serverId}/asm-disks?${qs}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  const data = await res.json();
  if (Array.isArray(data)) return { disks: data, cached: false, server_id: serverId };
  return data;
}

export type AsmSeqNext = {
  prefix: string;
  used_max: number;
  next_index: number;
  sample_alias: string;
  sample_asm_name: string;
};

export async function fetchAsmSeqNext(
  token: string,
  prefix: string,
  serverIds: number[],
): Promise<AsmSeqNext> {
  const qs = new URLSearchParams();
  qs.set("prefix", prefix);
  qs.set("server_ids", serverIds.slice(0, 2).join(","));
  const res = await fetch(apiUrl(`/api/ops/asm-seq-next?${qs}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function listVlanPools(token: string): Promise<VlanPool[]> {
  const res = await fetch(apiUrl("/api/ops/vlan-pools"), { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function listInterfaces(token: string, serverId: number): Promise<NetInterface[]> {
  const res = await fetch(apiUrl(`/api/ops/servers/${serverId}/interfaces`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function getSystemOverview(token: string): Promise<SystemOverview> {
  const res = await fetch(apiUrl("/api/admin/system/overview"), { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function getContainerLogs(
  token: string,
  name: string,
): Promise<{ available: boolean; lines: string[]; error?: string }> {
  const res = await fetch(apiUrl(`/api/admin/system/container-logs/${encodeURIComponent(name)}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

/* ---- Package repos / dnf (dynamic OS) ---- */

export type OsOption = {
  os_id: string;
  os_major: string;
  label: string;
  value: string;
  count: number;
};

export type PkgSubscriptionRow = {
  id: number;
  label: string;
  os_id: string;
  os_major: string;
  os_value: string;
  org: string;
  activation_key_set: boolean;
  enabled: boolean;
};

export type PkgLocalRepoRow = {
  id: number;
  keyword: string;
  label: string;
  os_id: string;
  os_major: string;
  os_value: string;
  source_type?: "nfs" | "portal_files" | "subscription" | string;
  nfs_path: string;
  mount_point: string;
  repo_id: string;
  baseurl_suffix: string;
  portal_path?: string;
  file_glob?: string;
  needs_data_mount: boolean;
  post_commands: string;
  enabled: boolean;
};

export type CentrifyCredentialRow = {
  id: number;
  label: string;
  username: string;
  domain: string;
  password_set: boolean;
  enabled: boolean;
};

export async function listCentrifyCredentials(
  token: string,
): Promise<{ credentials: CentrifyCredentialRow[] }> {
  const res = await fetch(apiUrl("/api/settings/centrify"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function createCentrifyCredential(
  token: string,
  body: {
    username: string;
    domain: string;
    password: string;
    label?: string;
    enabled?: boolean;
  },
): Promise<CentrifyCredentialRow> {
  const res = await fetch(apiUrl("/api/settings/centrify"), {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function updateCentrifyCredential(
  token: string,
  id: number,
  body: {
    username: string;
    domain: string;
    password?: string;
    label?: string;
    enabled?: boolean;
  },
): Promise<CentrifyCredentialRow> {
  const res = await fetch(apiUrl(`/api/settings/centrify/${id}`), {
    method: "PUT",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function deleteCentrifyCredential(token: string, id: number): Promise<void> {
  const res = await fetch(apiUrl(`/api/settings/centrify/${id}`), {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
}

export type PackageSearchHit = { name: string; summary: string };

export type PackageContext = {
  os: { os_id: string; version_major: string; pretty: string };
  subscription_key_set: boolean;
  keywords: PkgLocalRepoRow[];
  data_mounts: Array<{ mount: string; fstype?: string; size?: string; avail?: string; use_pct?: string }>;
};

export async function getPackageReposOverview(token: string): Promise<{
  os_options: OsOption[];
  subscriptions: PkgSubscriptionRow[];
  local_repos: PkgLocalRepoRow[];
  keywords: Array<{ keyword: string; label: string; needs_data_mount: boolean; source_type?: string }>;
  portal_rpm_root?: string;
}> {
  const res = await fetch(apiUrl("/api/settings/package-repos/overview"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function createPkgSubscription(
  token: string,
  body: { os_value: string; org?: string; activation_key?: string; label?: string; enabled?: boolean },
): Promise<PkgSubscriptionRow> {
  const res = await fetch(apiUrl("/api/settings/package-repos/subscriptions"), {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function deletePkgSubscription(token: string, id: number): Promise<void> {
  const res = await fetch(apiUrl(`/api/settings/package-repos/subscriptions/${id}`), {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
}

export async function createPkgLocalRepo(
  token: string,
  body: {
    keyword: string;
    label?: string;
    os_value: string;
    source_type?: "nfs" | "portal_files" | "subscription" | string;
    nfs_path?: string;
    mount_point?: string;
    repo_id?: string;
    baseurl_suffix?: string;
    portal_path?: string;
    file_glob?: string;
    needs_data_mount?: boolean;
    post_commands?: string;
    enabled?: boolean;
  },
): Promise<PkgLocalRepoRow> {
  const res = await fetch(apiUrl("/api/settings/package-repos/local-repos"), {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function updatePkgLocalRepo(
  token: string,
  id: number,
  body: {
    keyword: string;
    label?: string;
    os_value: string;
    source_type?: "nfs" | "portal_files" | "subscription" | string;
    nfs_path?: string;
    mount_point?: string;
    repo_id?: string;
    baseurl_suffix?: string;
    portal_path?: string;
    file_glob?: string;
    needs_data_mount?: boolean;
    post_commands?: string;
    enabled?: boolean;
  },
): Promise<PkgLocalRepoRow> {
  const res = await fetch(apiUrl(`/api/settings/package-repos/local-repos/${id}`), {
    method: "PUT",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function deletePkgLocalRepo(token: string, id: number): Promise<void> {
  const res = await fetch(apiUrl(`/api/settings/package-repos/local-repos/${id}`), {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
}

export async function getPackageContext(token: string, serverId: number): Promise<PackageContext> {
  const res = await fetch(apiUrl(`/api/ops/servers/${serverId}/package-context`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function dnfSearch(
  token: string,
  serverId: number,
  q: string,
): Promise<{ query: string; results: PackageSearchHit[]; subscription_used?: boolean }> {
  const qs = new URLSearchParams({ q });
  const res = await fetch(apiUrl(`/api/ops/servers/${serverId}/dnf-search?${qs}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type PackageVersionsResult = {
  keyword: string;
  package: string;
  os: { os_id: string; version_major: string; pretty: string };
  versions: string[];
  latest: string;
};

export async function listPackageVersions(
  token: string,
  serverId: number,
  opts?: { keyword?: string; package?: string },
): Promise<PackageVersionsResult> {
  const qs = new URLSearchParams({
    keyword: opts?.keyword || "docker",
    package: opts?.package || "docker-ce",
  });
  const res = await fetch(apiUrl(`/api/ops/servers/${serverId}/package-versions?${qs}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

/* ---- Security: policy / sessions / MFA admin ---- */

export type SecurityPolicy = {
  session_idle_minutes: number;
  session_absolute_minutes: number;
  session_max_concurrent: number;
  mfa_enabled: boolean;
  lockout_enabled: boolean;
  lockout_max_attempts: number;
  lockout_window_minutes: number;
  lockout_duration_minutes: number;
};

export async function getSecurityPolicy(token: string): Promise<SecurityPolicy> {
  const res = await fetch(apiUrl("/api/security/policy"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function updateSecurityPolicy(
  token: string,
  body: Partial<SecurityPolicy>,
): Promise<SecurityPolicy> {
  const res = await fetch(apiUrl("/api/security/policy"), {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type PortalSessionPublic = {
  id: number;
  user_id: number;
  username: string;
  auth_source: string;
  client_ip: string;
  user_agent: string;
  created_at: string;
  last_seen_at: string;
  absolute_expires_at: string;
  is_current: boolean;
  revoked: boolean;
};

export async function listSecuritySessions(
  token: string,
  activeOnly = true,
): Promise<PortalSessionPublic[]> {
  const qs = new URLSearchParams({ active_only: String(activeOnly) });
  const res = await fetch(apiUrl(`/api/security/sessions?${qs}`), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function listMySessions(token: string): Promise<PortalSessionPublic[]> {
  const res = await fetch(apiUrl("/api/security/sessions/mine"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function revokeSecuritySession(token: string, id: number): Promise<void> {
  const res = await fetch(apiUrl(`/api/security/sessions/${id}`), {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
}

export async function revokeOtherSessions(token: string): Promise<{ ok: boolean; revoked: number }> {
  const res = await fetch(apiUrl("/api/security/sessions/revoke-others"), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type MfaUserStatus = {
  user_id: number;
  username: string;
  auth_source: string;
  status: "disabled" | "pending" | "enabled" | string;
  enrolled_at: string | null;
  last_verified_at: string | null;
};

export async function listMfaUsers(token: string): Promise<MfaUserStatus[]> {
  const res = await fetch(apiUrl("/api/security/mfa/users"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function resetUserMfa(
  token: string,
  userId: number,
): Promise<{ ok: boolean; had_mfa: boolean; sessions_revoked: number }> {
  const res = await fetch(apiUrl(`/api/security/mfa/users/${userId}/reset`), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export type TlsStatus = {
  https_enabled: boolean;
  certs_dir: string;
  cert_present: boolean;
  key_present: boolean;
  source: string;
  subject: string | null;
  not_after: string | null;
  fingerprint_sha256: string | null;
  http_port: number;
  https_port: number;
  error?: string | null;
};

export async function getTlsStatus(token: string): Promise<TlsStatus> {
  const res = await fetch(apiUrl("/api/security/tls"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function setTlsEnabled(token: string, https_enabled: boolean): Promise<TlsStatus> {
  const res = await fetch(apiUrl("/api/security/tls"), {
    method: "PATCH",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ https_enabled }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function uploadTlsCert(
  token: string,
  body: { cert_pem: string; key_pem: string; chain_pem?: string },
): Promise<TlsStatus> {
  const res = await fetch(apiUrl("/api/security/tls/upload"), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function regenerateSelfSignedTls(token: string): Promise<TlsStatus> {
  const res = await fetch(apiUrl("/api/security/tls/self-signed"), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}
