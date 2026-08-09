import { FormEvent, useEffect, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import {
  getMe,
  getPublicSettings,
  login,
  LoginResponse,
  mfaEnrollConfirm,
  mfaEnrollStart,
  mfaVerify,
  ssoStartUrl,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useT } from "@/i18n/I18nProvider";
import { getToken, saveSession } from "@/session";

type Stage = "credentials" | "mfa_verify" | "mfa_enroll";

function trySaveSession(result: LoginResponse): boolean {
  if (!result.token || !result.user) return false;
  saveSession(result.token.access_token, JSON.stringify(result.user));
  return true;
}

export function LoginPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const t = useT();
  const [appName, setAppName] = useState("Dr OPT");
  const [ssoEnabled, setSsoEnabled] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [ssoHandling, setSsoHandling] = useState(false);

  const [stage, setStage] = useState<Stage>("credentials");
  const [mfaToken, setMfaToken] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [enrollSecret, setEnrollSecret] = useState("");
  const [enrollOtpauthUrl, setEnrollOtpauthUrl] = useState("");

  useEffect(() => {
    void getPublicSettings()
      .then((s) => {
        setAppName(s.app_name);
        setSsoEnabled(Boolean(s.sso_enabled));
        document.title = s.app_name;
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const ssoError = params.get("sso_error");
    if (ssoError) {
      setError(ssoError);
      return;
    }
    const ssoToken = params.get("sso_token");
    if (!ssoToken) return;
    setSsoHandling(true);
    void (async () => {
      try {
        const me = await getMe(ssoToken);
        saveSession(ssoToken, JSON.stringify(me));
        navigate("/app", { replace: true });
      } catch {
        setError(t("login_failed"));
        setSsoHandling(false);
      }
    })();
  }, [params, navigate, t]);

  if (getToken() && !ssoHandling) {
    return <Navigate to="/app" replace />;
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const result = await login(username.trim(), password);
      if (trySaveSession(result)) {
        navigate("/app", { replace: true });
        return;
      }
      if (!result.mfa_token) throw new Error(t("login_failed"));
      setMfaToken(result.mfa_token);
      if (result.mfa_enrollment_required) {
        const enrollment = await mfaEnrollStart(result.mfa_token);
        setEnrollSecret(enrollment.secret);
        setEnrollOtpauthUrl(enrollment.otpauth_url);
        setStage("mfa_enroll");
      } else if (result.mfa_required) {
        setStage("mfa_verify");
      } else {
        throw new Error(t("login_failed"));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("login_failed"));
    } finally {
      setLoading(false);
    }
  }

  async function onSubmitMfaVerify(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const result = await mfaVerify(mfaToken, mfaCode.trim());
      if (!trySaveSession(result)) throw new Error(t("login_failed"));
      navigate("/app", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : t("login_failed"));
    } finally {
      setLoading(false);
    }
  }

  async function onSubmitMfaEnroll(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const result = await mfaEnrollConfirm(mfaToken, mfaCode.trim());
      if (!trySaveSession(result)) throw new Error(t("login_failed"));
      navigate("/app", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : t("login_failed"));
    } finally {
      setLoading(false);
    }
  }

  function onBackToCredentials() {
    setStage("credentials");
    setMfaToken("");
    setMfaCode("");
    setEnrollSecret("");
    setEnrollOtpauthUrl("");
    setError(null);
  }

  return (
    <div className="flex min-h-full items-center justify-center px-4">
      <div className="w-full max-w-md">
        <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--color-primary)]">{t("portal")}</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">{appName}</h1>
        <p className="mt-2 text-sm text-[var(--color-muted-foreground)]">{t("login_subtitle")}</p>

        {stage === "credentials" ? (
          <form
            onSubmit={onSubmit}
            className="mt-8 space-y-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)]/90 p-6 shadow-xl backdrop-blur"
          >
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">{t("username")}</label>
              <Input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                required
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">{t("password")}</label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>
            {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
            <Button type="submit" className="w-full" disabled={loading || ssoHandling}>
              {loading ? t("login_submitting") : t("login_submit")}
            </Button>
            {ssoEnabled ? (
              <Button
                type="button"
                variant="outline"
                className="w-full"
                disabled={ssoHandling}
                onClick={() => {
                  window.location.href = ssoStartUrl();
                }}
              >
                {t("login_sso")}
              </Button>
            ) : null}
          </form>
        ) : null}

        {stage === "mfa_verify" ? (
          <form
            onSubmit={onSubmitMfaVerify}
            className="mt-8 space-y-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)]/90 p-6 shadow-xl backdrop-blur"
          >
            <h2 className="text-sm font-medium">{t("login_mfa_title")}</h2>
            <p className="text-sm text-[var(--color-muted-foreground)]">{t("login_mfa_verify_help")}</p>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                {t("login_mfa_code")}
              </label>
              <Input
                className="font-mono tracking-widest"
                inputMode="numeric"
                autoFocus
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value)}
                required
                minLength={6}
                maxLength={12}
              />
            </div>
            {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? t("login_submitting") : t("login_mfa_submit")}
            </Button>
            <Button type="button" variant="ghost" className="w-full" onClick={onBackToCredentials}>
              {t("login_mfa_back")}
            </Button>
          </form>
        ) : null}

        {stage === "mfa_enroll" ? (
          <form
            onSubmit={onSubmitMfaEnroll}
            className="mt-8 space-y-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)]/90 p-6 shadow-xl backdrop-blur"
          >
            <h2 className="text-sm font-medium">{t("login_mfa_enroll_title")}</h2>
            <p className="text-sm text-[var(--color-muted-foreground)]">{t("login_mfa_enroll_help")}</p>
            <div className="space-y-2 rounded-lg border border-[var(--color-border)] bg-[var(--theme-inset)] p-3">
              <div>
                <p className="text-xs text-[var(--color-muted-foreground)]">{t("login_mfa_secret")}</p>
                <p className="break-all font-mono text-xs">{enrollSecret}</p>
              </div>
              <div>
                <p className="text-xs text-[var(--color-muted-foreground)]">{t("login_mfa_otpauth_url")}</p>
                <p className="break-all font-mono text-[10px] text-[var(--color-muted-foreground)]">
                  {enrollOtpauthUrl}
                </p>
              </div>
            </div>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                {t("login_mfa_code")}
              </label>
              <Input
                className="font-mono tracking-widest"
                inputMode="numeric"
                autoFocus
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value)}
                required
                minLength={6}
                maxLength={12}
              />
            </div>
            {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? t("login_submitting") : t("login_mfa_enroll_submit")}
            </Button>
            <Button type="button" variant="ghost" className="w-full" onClick={onBackToCredentials}>
              {t("login_mfa_back")}
            </Button>
          </form>
        ) : null}
      </div>
    </div>
  );
}
