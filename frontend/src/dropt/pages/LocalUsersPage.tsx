import { FormEvent, useEffect, useState } from "react";
import {
  createJob,
  listLocalUsers,
  listServers,
  LocalUserPublic,
  previewJob,
  ServerPublic,
} from "@dropt/api";
import { ServerPicker } from "@dropt/components/ServerPicker";
import { Badge } from "@dropt/components/ui/badge";
import { Button } from "@dropt/components/ui/button";
import { Checkbox } from "@dropt/components/ui/checkbox";
import { Input } from "@dropt/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@dropt/components/ui/select";
import { useServerQuery } from "@dropt/hooks/useServerQuery";
import { useAfterPreview } from "@dropt/hooks/useOpsWizard";
import { useT } from "@dropt/i18n/I18nProvider";
import { getToken } from "@dropt/session";

type WizardAction =
  | "create"
  | "lock"
  | "unlock"
  | "delete"
  | "password_reset"
  | "set_expire";

export function LocalUsersPage() {
  const token = getToken()!;
  const afterPreview = useAfterPreview();
  const t = useT();
  const { serverIds: qServerIds } = useServerQuery();
  const qServerIdsKey = qServerIds.join(",");
  const [servers, setServers] = useState<ServerPublic[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [users, setUsers] = useState<LocalUserPublic[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [action, setAction] = useState<WizardAction>("lock");
  const [talepId, setTalepId] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [groups, setGroups] = useState("");
  const [forceChange, setForceChange] = useState(false);
  const [removeHome, setRemoveHome] = useState(false);
  const [backupHome, setBackupHome] = useState(false);
  const [expireDate, setExpireDate] = useState("");
  const [busy, setBusy] = useState(false);

  const tableServerId = selectedIds.length === 1 ? selectedIds[0] : null;

  useEffect(() => {
    void listServers(token, { page: 1, page_size: 200, status: "ready" }).then((d) => {
      setServers(d.items);
      if (qServerIds.length) {
        const wanted = new Set(qServerIds.map(Number).filter((id) => Number.isFinite(id)));
        setSelectedIds(d.items.filter((s) => wanted.has(s.id)).map((s) => s.id));
      } else if (d.items[0]) {
        setSelectedIds([d.items[0].id]);
      }
    });
  }, [token, qServerIdsKey]);

  useEffect(() => {
    if (tableServerId == null) {
      setUsers([]);
      return;
    }
    setLoadingUsers(true);
    void listLocalUsers(token, tableServerId)
      .then(setUsers)
      .catch((err) => setError(err instanceof Error ? err.message : t("list_failed")))
      .finally(() => setLoadingUsers(false));
  }, [token, tableServerId, t]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const tid = talepId.trim();
      if (!tid) throw new Error("Talep ID zorunlu");
      const uname = username.trim();
      if (!uname) throw new Error("Kullanıcı adı zorunlu");
      if (selectedIds.length === 0) throw new Error("Sunucu seçin");

      const payload: Record<string, unknown> = { username: uname };
      if (action === "create") {
        if (password.length < 6) throw new Error("Parola en az 6 karakter");
        payload.password = password;
        payload.groups = groups
          .split(",")
          .map((g) => g.trim())
          .filter(Boolean);
        payload.force_password_change = forceChange;
      }
      if (action === "password_reset") {
        if (password.length < 6) throw new Error("Parola en az 6 karakter");
        payload.password = password;
        payload.force_password_change = forceChange;
      }
      if (action === "set_expire") {
        if (!expireDate.trim()) throw new Error("Expire tarihi gerekli (YYYY-MM-DD) veya -1 için boş bırakmayın");
        payload.expire_date = expireDate.trim();
      }
      if (action === "delete") {
        payload.remove_home = removeHome;
        payload.backup_home = backupHome;
      }

      const job = await createJob(token, {
        action,
        talep_id: tid,
        server_ids: selectedIds,
        payload,
      });
      afterPreview(await previewJob(token, job.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "İş oluşturulamadı");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="px-6 py-6">
      <h2 className="text-xl font-semibold">{t("wizard_local_users")}</h2>
      <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">{t("local_users_sub")}</p>

      <form
        onSubmit={onSubmit}
        className="mt-6 max-w-2xl space-y-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-5"
      >
        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">{t("local_users_action")}</label>
          <Select value={action} onValueChange={(v) => setAction(v as WizardAction)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="create">{t("local_users_op_create")}</SelectItem>
              <SelectItem value="lock">{t("local_users_op_lock")}</SelectItem>
              <SelectItem value="unlock">{t("local_users_op_unlock")}</SelectItem>
              <SelectItem value="password_reset">{t("local_users_op_password")}</SelectItem>
              <SelectItem value="set_expire">{t("local_users_op_expire")}</SelectItem>
              <SelectItem value="delete">{t("local_users_op_delete")}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">{t("talep_id")}</label>
          <Input
            value={talepId}
            onChange={(e) => setTalepId(e.target.value)}
            placeholder="Örn. TLP-2026-001"
            required
          />
        </div>

        <ServerPicker
          servers={servers}
          value={selectedIds}
          onChange={setSelectedIds}
          multiple
          label={t("local_users_targets")}
        />
        <p className="-mt-2 text-xs text-[var(--color-muted-foreground)]">{t("local_users_multi_hint")}</p>

        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
            {t("local_users_username")}
          </label>
          <Input
            className="font-mono"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </div>

        {action === "create" || action === "password_reset" ? (
          <>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">{t("password")}</label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                minLength={6}
                required
              />
            </div>
            {action === "create" ? (
              <div>
                <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                  {t("local_users_groups")}
                </label>
                <Input value={groups} onChange={(e) => setGroups(e.target.value)} placeholder="wheel,devops" />
              </div>
            ) : null}
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={forceChange} onCheckedChange={(v) => setForceChange(!!v)} />
              {t("local_users_force_change")}
            </label>
          </>
        ) : null}

        {action === "set_expire" ? (
          <div>
            <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
              {t("local_users_expire")}
            </label>
            <Input
              className="font-mono"
              value={expireDate}
              onChange={(e) => setExpireDate(e.target.value)}
              placeholder="2026-12-31"
              required
            />
          </div>
        ) : null}

        {action === "delete" ? (
          <>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={removeHome} onCheckedChange={(v) => setRemoveHome(!!v)} />
              {t("local_users_remove_home")}
            </label>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={backupHome} onCheckedChange={(v) => setBackupHome(!!v)} />
              {t("local_users_backup_home")}
            </label>
          </>
        ) : null}

        {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}

        <Button type="submit" disabled={busy}>
          {busy ? t("local_users_preview_busy") : t("preview")}
        </Button>
      </form>

      {tableServerId != null ? (
        <div className="mt-8 overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-card)]/80">
          <div className="border-b border-[var(--color-border)] px-4 py-3 text-sm font-medium">
            {t("local_users_list_title")}
          </div>
          {loadingUsers ? (
            <p className="px-4 py-6 text-sm text-[var(--color-muted-foreground)]">{t("loading")}</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-[var(--color-muted-foreground)]">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">{t("local_users_col_user")}</th>
                  <th className="px-3 py-2 text-left font-medium">UID</th>
                  <th className="px-3 py-2 text-left font-medium">{t("local_users_col_groups")}</th>
                  <th className="px-3 py-2 text-left font-medium">{t("local_users_col_status")}</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr
                    key={u.username}
                    className="cursor-pointer border-t border-[var(--color-border)] hover:bg-[var(--color-accent)]/40"
                    onClick={() => {
                      if (!u.protected) setUsername(u.username);
                    }}
                  >
                    <td className="px-3 py-2 font-mono text-xs">
                      {u.username}
                      {u.protected ? (
                        <Badge className="ml-2" variant="muted">
                          {t("local_users_protected")}
                        </Badge>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">{u.uid ?? "—"}</td>
                    <td className="px-3 py-2 text-xs text-[var(--color-muted-foreground)]">
                      {u.groups.join(", ") || "—"}
                    </td>
                    <td className="px-3 py-2">
                      <Badge variant={u.status === "locked" ? "danger" : "success"}>{u.status}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : (
        <p className="mt-6 text-sm text-[var(--color-muted-foreground)]">{t("local_users_list_hidden")}</p>
      )}
    </div>
  );
}
