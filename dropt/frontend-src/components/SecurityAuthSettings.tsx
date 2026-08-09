import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  getIdentitySettings,
  IdentitySettings,
  testAdConnection,
  testKerberosConfig,
  updateIdentitySettings,
  uploadKerberosKeytab,
} from "@/api";
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
import { useT } from "@/i18n/I18nProvider";
import { getToken } from "@/session";

type SubTab = "ad" | "sso";

export function SecurityAuthSettings() {
  const token = getToken()!;
  const t = useT();

  const [subTab, setSubTab] = useState<SubTab>("ad");
  const [identity, setIdentity] = useState<IdentitySettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showOidc, setShowOidc] = useState(false);

  const [adForm, setAdForm] = useState({
    ad_enabled: false,
    ad_host: "",
    ad_port: 636,
    ad_use_ssl: true,
    ad_tls_verify: false,
    ad_ca_cert_pem: "",
    ad_clear_ca: false,
    ad_domain: "",
    ad_base_dn: "",
    ad_bind_dn: "",
    ad_bind_password: "",
    ad_admin_group: "",
    ad_operator_group: "",
  });
  const [adTestUser, setAdTestUser] = useState({ username: "", password: "" });

  const [krbForm, setKrbForm] = useState({
    sso_enabled: false,
    sso_mode: "kerberos",
    kerberos_realm: "",
    kerberos_spn: "",
  });

  const [oidcForm, setOidcForm] = useState({
    sso_issuer: "",
    sso_client_id: "",
    sso_client_secret: "",
    sso_redirect_uri: "",
    sso_scopes: "openid profile email",
    sso_admin_group: "",
    sso_operator_group: "",
    sso_frontend_redirect: "",
  });

  const loadIdentity = useCallback(async () => {
    const cfg = await getIdentitySettings(token);
    setIdentity(cfg);
    setAdForm({
      ad_enabled: cfg.ad_enabled,
      ad_host: cfg.ad_host || "",
      ad_port: cfg.ad_port || 636,
      ad_use_ssl: cfg.ad_use_ssl !== false,
      ad_tls_verify: Boolean(cfg.ad_tls_verify),
      ad_ca_cert_pem: "",
      ad_clear_ca: false,
      ad_domain: cfg.ad_domain,
      ad_base_dn: cfg.ad_base_dn,
      ad_bind_dn: cfg.ad_bind_dn,
      ad_bind_password: "",
      ad_admin_group: cfg.ad_admin_group,
      ad_operator_group: cfg.ad_operator_group,
    });
    setKrbForm({
      sso_enabled: cfg.sso_enabled,
      sso_mode: cfg.sso_mode || "kerberos",
      kerberos_realm: cfg.kerberos_realm || "",
      kerberos_spn: cfg.kerberos_spn || "",
    });
    setOidcForm({
      sso_issuer: cfg.sso_issuer,
      sso_client_id: cfg.sso_client_id,
      sso_client_secret: "",
      sso_redirect_uri: cfg.sso_redirect_uri,
      sso_scopes: cfg.sso_scopes || "openid profile email",
      sso_admin_group: cfg.sso_admin_group,
      sso_operator_group: cfg.sso_operator_group,
      sso_frontend_redirect: cfg.sso_frontend_redirect,
    });
    if ((cfg.sso_mode || "kerberos") === "oidc") setShowOidc(true);
  }, [token]);

  useEffect(() => {
    void loadIdentity().catch((e) => setError(e instanceof Error ? e.message : "Hata"));
  }, [loadIdentity]);

  async function onSaveAd(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const payload: Record<string, unknown> = {
        ad_enabled: adForm.ad_enabled,
        ad_host: adForm.ad_host,
        ad_port: Number(adForm.ad_port) || (adForm.ad_use_ssl ? 636 : 389),
        ad_use_ssl: adForm.ad_use_ssl,
        ad_tls_verify: adForm.ad_tls_verify,
        ad_domain: adForm.ad_domain,
        ad_base_dn: adForm.ad_base_dn,
        ad_bind_dn: adForm.ad_bind_dn,
        ad_admin_group: adForm.ad_admin_group,
        ad_operator_group: adForm.ad_operator_group,
      };
      if (adForm.ad_bind_password.trim()) payload.ad_bind_password = adForm.ad_bind_password;
      if (adForm.ad_clear_ca) payload.ad_ca_cert_pem = "";
      else if (adForm.ad_ca_cert_pem.trim()) payload.ad_ca_cert_pem = adForm.ad_ca_cert_pem.trim();
      await updateIdentitySettings(token, payload);
      setInfo(t("identity_saved"));
      await loadIdentity();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  async function onTestAdBind() {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const r = await testAdConnection(token);
      setInfo(
        `${r.message}${r.resolved_host ? ` · host=${r.resolved_host}` : ""}${r.ldap_url ? ` · ${r.ldap_url}` : ""}`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  async function onTestAdUser() {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const r = await testAdConnection(token, adTestUser);
      setInfo(
        `${r.message}${r.role ? ` · rol=${r.role}` : ""}${r.groups?.length ? ` · grup=${r.groups.length}` : ""}${
          r.resolved_host ? ` · host=${r.resolved_host}` : ""
        }`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  async function onSaveKerberos(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      await updateIdentitySettings(token, {
        sso_enabled: krbForm.sso_enabled,
        sso_mode: "kerberos",
        kerberos_realm: krbForm.kerberos_realm.trim(),
        kerberos_spn: krbForm.kerberos_spn.trim(),
      });
      setInfo(t("identity_saved"));
      await loadIdentity();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  async function onUploadKeytab(file: File | null) {
    if (!file) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      await uploadKerberosKeytab(token, file);
      setInfo(t("portal_keytab_uploaded"));
      await loadIdentity();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  async function onTestKerberos() {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const r = await testKerberosConfig(token);
      setInfo(r.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  async function onSaveOidc(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const payload: Record<string, unknown> = {
        sso_enabled: krbForm.sso_enabled,
        sso_mode: "oidc",
        sso_issuer: oidcForm.sso_issuer,
        sso_client_id: oidcForm.sso_client_id,
        sso_redirect_uri: oidcForm.sso_redirect_uri,
        sso_scopes: oidcForm.sso_scopes,
        sso_admin_group: oidcForm.sso_admin_group,
        sso_operator_group: oidcForm.sso_operator_group,
        sso_frontend_redirect: oidcForm.sso_frontend_redirect,
      };
      if (oidcForm.sso_client_secret.trim()) payload.sso_client_secret = oidcForm.sso_client_secret;
      await updateIdentitySettings(token, payload);
      setInfo(t("identity_saved"));
      await loadIdentity();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {(
          [
            ["ad", t("portal_tab_ad")],
            ["sso", t("portal_tab_sso")],
          ] as const
        ).map(([key, label]) => (
          <Button key={key} size="sm" variant={subTab === key ? "default" : "outline"} onClick={() => setSubTab(key)}>
            {label}
          </Button>
        ))}
      </div>

      {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
      {info ? <p className="text-sm text-emerald-300">{info}</p> : null}

      {subTab === "ad" ? (
        <form
          onSubmit={onSaveAd}
          className="max-w-2xl space-y-4 rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] p-6 shadow-sm"
        >
          <p className="text-sm text-[var(--color-muted-foreground)]">{t("portal_ad_help")}</p>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={adForm.ad_enabled}
              onCheckedChange={(v) => setAdForm({ ...adForm, ad_enabled: !!v })}
            />
            {t("portal_ad_enable")}
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                {t("portal_ad_domain")} *
              </label>
              <Input
                className="font-mono"
                placeholder="datatem.local"
                value={adForm.ad_domain}
                onChange={(e) => setAdForm({ ...adForm, ad_domain: e.target.value })}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                {t("portal_ad_host")} *
              </label>
              <Input
                className="font-mono"
                placeholder="DC01.datatem.local"
                value={adForm.ad_host}
                onChange={(e) => setAdForm({ ...adForm, ad_host: e.target.value })}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                {t("portal_ad_port")} *
              </label>
              <Input
                className="font-mono"
                type="number"
                value={adForm.ad_port}
                onChange={(e) => setAdForm({ ...adForm, ad_port: Number(e.target.value) || 636 })}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                {t("portal_ad_ssl")}
              </label>
              <Select
                value={adForm.ad_use_ssl ? "ssl" : "plain"}
                onValueChange={(v) => {
                  const ssl = v === "ssl";
                  setAdForm({
                    ...adForm,
                    ad_use_ssl: ssl,
                    ad_port: ssl ? 636 : 389,
                  });
                }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ssl">{t("portal_ad_ssl_yes")}</SelectItem>
                  <SelectItem value="plain">{t("portal_ad_ssl_no")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="sm:col-span-2">
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">Base DN *</label>
              <Input
                className="font-mono"
                placeholder="DC=datatem,DC=local"
                value={adForm.ad_base_dn}
                onChange={(e) => setAdForm({ ...adForm, ad_base_dn: e.target.value })}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                {t("portal_ad_bind_user")} *
              </label>
              <Input
                className="font-mono"
                placeholder="Administrator@datatem.local"
                value={adForm.ad_bind_dn}
                onChange={(e) => setAdForm({ ...adForm, ad_bind_dn: e.target.value })}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                {t("portal_ad_bind_pass")} {identity?.ad_bind_password_set ? t("password_keep") : "*"}
              </label>
              <Input
                type="password"
                value={adForm.ad_bind_password}
                onChange={(e) => setAdForm({ ...adForm, ad_bind_password: e.target.value })}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                {t("portal_admin_group")}
              </label>
              <Input
                className="font-mono"
                value={adForm.ad_admin_group}
                onChange={(e) => setAdForm({ ...adForm, ad_admin_group: e.target.value })}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                {t("portal_operator_group")}
              </label>
              <Input
                className="font-mono"
                value={adForm.ad_operator_group}
                onChange={(e) => setAdForm({ ...adForm, ad_operator_group: e.target.value })}
              />
            </div>
          </div>

          <div className="rounded-lg border border-sky-500/30 bg-sky-500/10 p-3 text-sm">
            <p className="font-medium text-sky-100">{t("portal_ad_cert_title")}</p>
            <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">{t("portal_ad_cert_help")}</p>
            <label className="mt-3 flex items-center gap-2 text-xs">
              <Checkbox
                checked={adForm.ad_tls_verify}
                onCheckedChange={(v) => setAdForm({ ...adForm, ad_tls_verify: !!v })}
              />
              {t("portal_ad_tls_verify")}
            </label>
            <textarea
              className="mt-2 h-24 w-full rounded-md border border-[var(--color-border)] bg-[var(--theme-inset)] p-2 font-mono text-xs"
              placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
              value={adForm.ad_ca_cert_pem}
              onChange={(e) => setAdForm({ ...adForm, ad_ca_cert_pem: e.target.value, ad_clear_ca: false })}
            />
            {identity?.ad_ca_cert_set ? (
              <label className="mt-2 flex items-center gap-2 text-xs">
                <Checkbox
                  checked={adForm.ad_clear_ca}
                  onCheckedChange={(v) => setAdForm({ ...adForm, ad_clear_ca: !!v })}
                />
                {t("portal_ad_clear_ca")}
              </label>
            ) : null}
            <p className="mt-2 text-[10px] text-amber-100/90">{t("portal_ad_cert_cn_hint")}</p>
          </div>

          <p className="font-mono text-[10px] text-[var(--color-muted-foreground)]">
            URL:{" "}
            {adForm.ad_use_ssl ? "ldaps" : "ldap"}://{adForm.ad_host || "…"}:{adForm.ad_port || "…"}
          </p>

          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={busy}>
              {t("save")}
            </Button>
            <Button type="button" variant="secondary" disabled={busy} onClick={() => void onTestAdBind()}>
              {t("portal_test_bind")}
            </Button>
          </div>

          <div className="border-t border-[var(--color-border)] pt-4">
            <h4 className="text-sm font-medium">{t("portal_test_user")}</h4>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              <Input
                placeholder={t("username")}
                value={adTestUser.username}
                onChange={(e) => setAdTestUser({ ...adTestUser, username: e.target.value })}
              />
              <Input
                type="password"
                placeholder={t("password")}
                value={adTestUser.password}
                onChange={(e) => setAdTestUser({ ...adTestUser, password: e.target.value })}
              />
            </div>
            <Button
              type="button"
              className="mt-2"
              variant="outline"
              disabled={busy}
              onClick={() => void onTestAdUser()}
            >
              {t("portal_test_user_btn")}
            </Button>
          </div>
        </form>
      ) : null}

      {subTab === "sso" ? (
        <div className="max-w-xl space-y-4">
          <form
            onSubmit={onSaveKerberos}
            className="space-y-4 rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] p-6 shadow-sm"
          >
            <p className="text-sm text-[var(--color-muted-foreground)]">{t("portal_sso_help")}</p>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={krbForm.sso_enabled}
                onCheckedChange={(v) => setKrbForm({ ...krbForm, sso_enabled: !!v })}
              />
              {t("portal_sso_enable")}
            </label>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                {t("portal_krb_realm")} *
              </label>
              <Input
                className="font-mono"
                placeholder="DATATEM.LOCAL"
                value={krbForm.kerberos_realm}
                onChange={(e) => setKrbForm({ ...krbForm, kerberos_realm: e.target.value })}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                {t("portal_krb_spn")} *
              </label>
              <Input
                className="font-mono"
                placeholder="HTTP/portal.datatem.local@DATATEM.LOCAL"
                value={krbForm.kerberos_spn}
                onChange={(e) => setKrbForm({ ...krbForm, kerberos_spn: e.target.value })}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                {t("portal_krb_keytab")}
              </label>
              <Input
                type="file"
                accept=".keytab,application/octet-stream"
                disabled={busy}
                onChange={(e) => void onUploadKeytab(e.target.files?.[0] ?? null)}
              />
              <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">
                {identity?.kerberos_keytab_uploaded
                  ? t("portal_keytab_present")
                  : t("portal_keytab_missing")}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="submit" disabled={busy}>
                {t("save")}
              </Button>
              <Button type="button" variant="secondary" disabled={busy} onClick={() => void onTestKerberos()}>
                {t("portal_krb_test")}
              </Button>
            </div>
          </form>

          <div>
            <Button type="button" size="sm" variant="ghost" onClick={() => setShowOidc((v) => !v)}>
              {showOidc ? t("portal_oidc_hide") : t("portal_oidc_show")}
            </Button>
            {showOidc ? (
              <form
                onSubmit={onSaveOidc}
                className="mt-2 space-y-3 rounded-xl border border-dashed border-[var(--color-border)] bg-[var(--color-card)]/60 p-4"
              >
                <p className="text-xs text-[var(--color-muted-foreground)]">{t("portal_oidc_help")}</p>
                <div>
                  <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">Issuer URL</label>
                  <Input
                    className="font-mono"
                    value={oidcForm.sso_issuer}
                    onChange={(e) => setOidcForm({ ...oidcForm, sso_issuer: e.target.value })}
                  />
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  <div>
                    <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">Client ID</label>
                    <Input
                      className="font-mono"
                      value={oidcForm.sso_client_id}
                      onChange={(e) => setOidcForm({ ...oidcForm, sso_client_id: e.target.value })}
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                      Client secret {identity?.sso_client_secret_set ? t("password_keep") : ""}
                    </label>
                    <Input
                      type="password"
                      value={oidcForm.sso_client_secret}
                      onChange={(e) => setOidcForm({ ...oidcForm, sso_client_secret: e.target.value })}
                    />
                  </div>
                </div>
                <div>
                  <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">Redirect URI</label>
                  <Input
                    className="font-mono"
                    value={oidcForm.sso_redirect_uri}
                    onChange={(e) => setOidcForm({ ...oidcForm, sso_redirect_uri: e.target.value })}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                    Frontend redirect
                  </label>
                  <Input
                    className="font-mono"
                    value={oidcForm.sso_frontend_redirect}
                    onChange={(e) => setOidcForm({ ...oidcForm, sso_frontend_redirect: e.target.value })}
                  />
                </div>
                <Button type="submit" disabled={busy}>
                  {t("portal_oidc_save")}
                </Button>
              </form>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
