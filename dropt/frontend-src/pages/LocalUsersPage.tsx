import { FormEvent, useEffect, useState } from "react";
import {
  createJob,
  listLocalUsers,
  listServers,
  LocalUserPublic,
  previewJob,
  ServerPublic,
} from "@/api";
import { ServerPicker } from "@/components/ServerPicker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useServerQuery } from "@/hooks/useServerQuery";
import { useAfterPreview } from "@/hooks/useOpsWizard";
import { useT } from "@/i18n/I18nProvider";
import { getToken } from "@/session";

type WizardAction =
  | "create"
  | "lock"
  | "unlock"
  | "delete"
  | "bulk_lock"
  | "password_reset"
  | "set_expire";

export function LocalUsersPage() {
  const token = getToken()!;
  const afterPreview = useAfterPreview();
  const t = useT();
  const { serverId: qServerId, serverIds: qServerIds } = useServerQuery();
  const qServerIdsKey = qServerIds.join(",");
  const [servers, setServers] = useState<ServerPublic[]>([]);
  const [serverId, setServerId] = useState<string>("");
  const [users, setUsers] = useState<LocalUserPublic[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [action, setAction] = useState<WizardAction>(qServerIds.length > 1 ? "bulk_lock" : "lock");
  const [talepId, setTalepId] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [groups, setGroups] = useState("");
  const [forceChange, setForceChange] = useState(false);
  const [removeHome, setRemoveHome] = useState(false);
  const [backupHome, setBackupHome] = useState(false);
  const [expireDate, setExpireDate] = useState("");
  const [bulkServerIds, setBulkServerIds] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void listServers(token, { page: 1, page_size: 200, status: "ready" }).then((d) => {
      setServers(d.items);
      if (qServerId) setServerId(qServerId);
      else if (d.items[0]) setServerId(String(d.items[0].id));
      if (qServerIds.length > 1) setBulkServerIds(qServerIds.map(Number));
    });
  }, [token, qServerId, qServerIdsKey]);

  useEffect(() => {
    if (!serverId || action === "bulk_lock") return;
    setLoadingUsers(true);
    void listLocalUsers(token, Number(serverId))
      .then(setUsers)
      .catch((err) => setError(err instanceof Error ? err.message : "Liste alınamadı"))
      .finally(() => setLoadingUsers(false));
  }, [token, serverId, action]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const tid = talepId.trim();
      if (!tid) throw new Error("Talep ID zorunlu");
      const uname = username.trim();
      if (!uname) throw new Error("Kullanıcı adı zorunlu");

      const server_ids =
        action === "bulk_lock"
          ? bulkServerIds
          : serverId
            ? [Number(serverId)]
            : [];
      if (server_ids.length === 0) throw new Error("Sunucu seçin");

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
        server_ids,
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
      <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
        Hedef sunucudaki OS kullanıcıları · Talep ID + önizleme zorunlu
      </p>

      <form
        onSubmit={onSubmit}
        className="mt-6 max-w-2xl space-y-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-5"
      >
        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">İşlem</label>
          <Select value={action} onValueChange={(v) => setAction(v as WizardAction)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="create">Kullanıcı oluştur</SelectItem>
              <SelectItem value="lock">Kilitle</SelectItem>
              <SelectItem value="unlock">Kilit aç</SelectItem>
              <SelectItem value="password_reset">Şifre sıfırla</SelectItem>
              <SelectItem value="set_expire">Süreyi ayarla</SelectItem>
              <SelectItem value="delete">Sil</SelectItem>
              <SelectItem value="bulk_lock">Birden fazla sunucuda kilitle</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">Talep ID</label>
          <Input
            value={talepId}
            onChange={(e) => setTalepId(e.target.value)}
            placeholder="Örn. TLP-2026-001"
            required
          />
        </div>

        {action !== "bulk_lock" ? (
          <ServerPicker
            servers={servers}
            value={serverId ? [Number(serverId)] : []}
            onChange={(ids) => setServerId(ids[0] ? String(ids[0]) : "")}
            multiple={false}
            label="Sunucu"
          />
        ) : (
          <ServerPicker
            servers={servers}
            value={bulkServerIds}
            onChange={setBulkServerIds}
            multiple
            label="Hedef sunucular"
          />
        )}

        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
            Kullanıcı adı
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
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">Parola</label>
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
                  Gruplar (virgülle)
                </label>
                <Input value={groups} onChange={(e) => setGroups(e.target.value)} placeholder="wheel,devops" />
              </div>
            ) : null}
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={forceChange} onCheckedChange={(v) => setForceChange(!!v)} />
              İlk girişte şifre değiştirilsin
            </label>
          </>
        ) : null}

        {action === "set_expire" ? (
          <div>
            <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
              Expire tarihi (YYYY-MM-DD)
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
              Ev dizinini de sil
            </label>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={backupHome} onCheckedChange={(v) => setBackupHome(!!v)} />
              Ev dizinini yedekle (tar)
            </label>
          </>
        ) : null}

        {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}

        <Button type="submit" disabled={busy}>
          {busy ? "Önizleme hazırlanıyor…" : "Değişiklikleri Önizle"}
        </Button>
      </form>

      {action !== "bulk_lock" && serverId ? (
        <div className="mt-8 overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-card)]/80">
          <div className="border-b border-[var(--color-border)] px-4 py-3 text-sm font-medium">
            Sunucudaki kullanıcılar
          </div>
          {loadingUsers ? (
            <p className="px-4 py-6 text-sm text-[var(--color-muted-foreground)]">Yükleniyor…</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-[var(--color-muted-foreground)]">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Kullanıcı</th>
                  <th className="px-3 py-2 text-left font-medium">UID</th>
                  <th className="px-3 py-2 text-left font-medium">Gruplar</th>
                  <th className="px-3 py-2 text-left font-medium">Durum</th>
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
                          korunan
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
      ) : null}
    </div>
  );
}
