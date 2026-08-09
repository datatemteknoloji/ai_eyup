import { FormEvent, useEffect, useState } from "react";
import {
  CentrifyCredentialRow,
  createCentrifyCredential,
  deleteCentrifyCredential,
  listCentrifyCredentials,
  updateCentrifyCredential,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getToken } from "@/session";

export function CentrifySettings() {
  const token = getToken()!;
  const [rows, setRows] = useState<CentrifyCredentialRow[]>([]);
  const [username, setUsername] = useState("");
  const [domain, setDomain] = useState("");
  const [password, setPassword] = useState("");
  const [label, setLabel] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function reload() {
    const data = await listCentrifyCredentials(token);
    setRows(data.credentials || []);
  }

  useEffect(() => {
    void reload().catch((e) => setError(e instanceof Error ? e.message : "Yüklenemedi"));
  }, [token]);

  function resetForm() {
    setUsername("");
    setDomain("");
    setPassword("");
    setLabel("");
    setEditingId(null);
  }

  function startEdit(r: CentrifyCredentialRow) {
    setEditingId(r.id);
    setUsername(r.username);
    setDomain(r.domain);
    setLabel(r.label || "");
    setPassword("");
    setMsg(null);
    setError(null);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const body = {
        username: username.trim(),
        domain: domain.trim().toLowerCase(),
        password: password.trim() || undefined,
        label: label.trim() || domain.trim().toLowerCase(),
        enabled: true,
      };
      if (editingId != null) {
        await updateCentrifyCredential(token, editingId, body);
        setMsg(`Güncellendi: ${body.domain}`);
      } else {
        if (!body.password) throw new Error("Yeni kayıt için password zorunlu");
        await createCentrifyCredential(token, { ...body, password: body.password });
        setMsg(`Eklendi: ${body.domain}`);
      }
      resetForm();
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-5">
      <div>
        <h3 className="text-sm font-medium">Centrify (AD leave / join)</h3>
        <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">
          Hostname değişikliğinde sunucudaki Current DC domain’i ile eşleşen hesap kullanılır. Leave:{" "}
          <span className="font-mono">adleave -f user</span> · Join:{" "}
          <span className="font-mono">echo pass | adjoin …</span>
        </p>
      </div>

      <form onSubmit={onSubmit} className="grid gap-2 sm:grid-cols-2">
        <Input
          className="h-8 font-mono"
          placeholder="username (örn. service_centrify)"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
        />
        <Input
          className="h-8 font-mono"
          placeholder="domain (örn. kfs.local)"
          value={domain}
          onChange={(e) => setDomain(e.target.value)}
          required
        />
        <Input
          className="h-8 font-mono"
          type="password"
          placeholder={editingId != null ? "password (boş = koru)" : "password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required={editingId == null}
        />
        <Input
          className="h-8"
          placeholder="etiket (ops.)"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
        <div className="flex gap-2 sm:col-span-2">
          <Button type="submit" size="sm" className="h-8" disabled={busy}>
            {editingId != null ? "Güncelle" : "Ekle"}
          </Button>
          {editingId != null ? (
            <Button type="button" size="sm" variant="secondary" className="h-8" onClick={resetForm}>
              İptal
            </Button>
          ) : null}
        </div>
      </form>

      {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
      {msg ? <p className="text-sm text-emerald-600">{msg}</p> : null}

      <ul className="space-y-1 font-mono text-[11px] text-[var(--color-muted-foreground)]">
        {rows.length === 0 ? (
          <li className="text-xs">(kayıt yok)</li>
        ) : (
          rows.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center justify-between gap-2">
              <span>
                {r.label || r.domain} · {r.username}@{r.domain} · pass=
                {r.password_set ? "set" : "yok"}
                {!r.enabled ? " · disabled" : ""}
              </span>
              <span className="flex gap-2">
                <button type="button" className="text-[var(--theme-link)] hover:underline" onClick={() => startEdit(r)}>
                  düzenle
                </button>
                <button
                  type="button"
                  className="text-red-300/90 hover:underline"
                  onClick={() =>
                    void deleteCentrifyCredential(token, r.id)
                      .then(reload)
                      .catch((e) => setError(e instanceof Error ? e.message : "Silinemedi"))
                  }
                >
                  sil
                </button>
              </span>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
