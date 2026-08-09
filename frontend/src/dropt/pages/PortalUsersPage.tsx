import { FormEvent, useCallback, useEffect, useState } from "react";
import { Navigate, useOutletContext } from "react-router-dom";
import { createPortalUser, deletePortalUser, listPortalUsers, PortalUser, syncAdPortalUsers, updatePortalUser, UserPublic } from "@dropt/api";
import { Badge } from "@dropt/components/ui/badge";
import { Button } from "@dropt/components/ui/button";
import { Input } from "@dropt/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@dropt/components/ui/select";
import { useT } from "@dropt/i18n/I18nProvider";
import type { TranslationKey } from "@dropt/i18n/messages";
import { getToken } from "@dropt/session";

type OutletCtx = { user: UserPublic; appName: string };
type PortalRole = "admin" | "operator" | "none";

function userTypeLabel(source: string, t: (k: TranslationKey) => string): string {
  if (source === "local") return t("user_type_local");
  if (source === "ad") return t("user_type_ad");
  if (source === "sso") return t("user_type_sso");
  return source;
}

export function PortalUsersPage() {
  const { user } = useOutletContext<OutletCtx>();
  const token = getToken()!;
  const t = useT();

  const [users, setUsers] = useState<PortalUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [newUser, setNewUser] = useState({
    username: "",
    password: "",
    role: "operator" as "admin" | "operator",
  });

  const loadUsers = useCallback(async () => {
    const data = await listPortalUsers(token);
    setUsers(data.items);
  }, [token]);

  useEffect(() => {
    if (user.role !== "admin") return;
    void loadUsers().catch((e) => setError(e instanceof Error ? e.message : "Hata"));
  }, [user.role, loadUsers]);

  if (user.role !== "admin") {
    return <Navigate to="/app" replace />;
  }

  async function onCreateUser(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      await createPortalUser(token, newUser);
      setNewUser({ username: "", password: "", role: "operator" });
      setInfo(t("portal_user_created"));
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  async function onChangeRole(u: PortalUser, role: PortalRole) {
    setError(null);
    try {
      await updatePortalUser(token, u.id, { role });
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    }
  }

  async function onDelete(u: PortalUser) {
    if (!window.confirm(t("portal_user_delete_confirm", { username: u.username }))) return;
    setError(null);
    try {
      await deletePortalUser(token, u.id);
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    }
  }

  async function onSyncAd() {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const r = await syncAdPortalUsers(token);
      setInfo(
        t("portal_sync_ad_result", {
          scanned: String(r.scanned),
          created: String(r.created),
          updated: String(r.updated),
        }),
      );
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="px-6 py-6">
      <h2 className="text-xl font-semibold">{t("nav_portal_users")}</h2>
      <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">{t("portal_users_subtitle")}</p>
      <p className="mt-2 text-xs text-[var(--color-muted-foreground)]">{t("portal_ad_sso_moved_hint")}</p>

      {error ? <p className="mt-3 text-sm text-[var(--color-destructive)]">{error}</p> : null}
      {info ? <p className="mt-3 text-sm text-emerald-300">{info}</p> : null}

      <div className="mt-6 space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <form onSubmit={onCreateUser} className="flex flex-wrap items-end gap-2">
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">{t("username")}</label>
              <Input
                className="w-40"
                value={newUser.username}
                onChange={(e) => setNewUser({ ...newUser, username: e.target.value })}
                required
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">{t("password")}</label>
              <Input
                className="w-40"
                type="password"
                value={newUser.password}
                onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
                required
                minLength={6}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">{t("portal_role")}</label>
              <Select
                value={newUser.role}
                onValueChange={(v) => setNewUser({ ...newUser, role: v as "admin" | "operator" })}
              >
                <SelectTrigger className="w-[130px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="operator">{t("role_operator")}</SelectItem>
                  <SelectItem value="admin">{t("role_admin")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button type="submit" disabled={busy}>
              {t("portal_create_user")}
            </Button>
          </form>
          <Button type="button" variant="secondary" disabled={busy} onClick={() => void onSyncAd()}>
            {t("portal_sync_ad")}
          </Button>
        </div>

        <div className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-card)]/80">
          <table className="w-full text-sm">
            <thead className="border-b border-[var(--color-border)] text-[var(--color-muted-foreground)]">
              <tr>
                <th className="px-3 py-2.5 text-left font-medium">{t("username")}</th>
                <th className="px-3 py-2.5 text-left font-medium">{t("portal_role")}</th>
                <th className="px-3 py-2.5 text-left font-medium">{t("portal_user_type")}</th>
                <th className="px-3 py-2.5 text-left font-medium" />
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-t border-[var(--color-border)]">
                  <td className="px-3 py-2 font-mono text-xs">{u.username}</td>
                  <td className="px-3 py-2">
                    <Select value={u.role} onValueChange={(v) => void onChangeRole(u, v as PortalRole)}>
                      <SelectTrigger className="h-8 w-[140px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="none">{t("role_none")}</SelectItem>
                        <SelectItem value="operator">{t("role_operator")}</SelectItem>
                        <SelectItem value="admin">{t("role_admin")}</SelectItem>
                      </SelectContent>
                    </Select>
                  </td>
                  <td className="px-3 py-2">
                    <Badge variant="muted">{userTypeLabel(u.auth_source, t)}</Badge>
                  </td>
                  <td className="px-3 py-2 text-right">
                    {u.auth_source === "local" ? (
                      <Button size="sm" variant="destructive" onClick={() => void onDelete(u)}>
                        {t("delete")}
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))}
              {users.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-3 py-6 text-center text-[var(--color-muted-foreground)]">
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
