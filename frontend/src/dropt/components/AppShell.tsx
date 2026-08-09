import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Activity,
  ChevronsLeft,
  ChevronsRight,
  Languages,
  LayoutDashboard,
  LogOut,
  Moon,
  ScrollText,
  Server,
  Settings,
  Shield,
  Sun,
  Users,
} from "lucide-react";
import { useEffect, useState } from "react";
import { getMe, getPublicSettings, logoutApi, updatePreferences, UserPublic } from "@dropt/api";
import { AssistantFab } from "@dropt/components/AssistantFab";
import { Button } from "@dropt/components/ui/button";
import { Separator } from "@dropt/components/ui/separator";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@dropt/components/ui/tooltip";
import { useI18n } from "@dropt/i18n/I18nProvider";
import { useTheme } from "@dropt/theme/ThemeProvider";
import { clearSession, getToken } from "@dropt/session";
import { cn } from "@dropt/lib/utils";

const SIDEBAR_KEY = "dropt_sidebar_collapsed";

export function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const { t, locale, setLocale } = useI18n();
  const { theme, setTheme } = useTheme();
  const [user, setUser] = useState<UserPublic | null>(null);
  const [appName, setAppName] = useState("Dr OPT");
  const [assistantEnabled, setAssistantEnabled] = useState(false);
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(SIDEBAR_KEY) === "1");
  const settingsActive = location.pathname.startsWith("/app/settings");

  const nav = [
    { to: "/app", labelKey: "nav_dashboard" as const, icon: LayoutDashboard, end: true },
    { to: "/app/servers", labelKey: "nav_servers" as const, icon: Server },
    { to: "/app/jobs", labelKey: "nav_jobs" as const, icon: Activity },
    { to: "/app/audit", labelKey: "nav_audit" as const, icon: Shield },
  ];

  useEffect(() => {
    const token = getToken();
    if (!token) {
      navigate("/", { replace: true });
      return;
    }
    void (async () => {
      try {
        const [me, settings] = await Promise.all([getMe(token), getPublicSettings()]);
        setUser(me);
        if (me.theme === "light" || me.theme === "dark") setTheme(me.theme);
        if (me.locale === "tr" || me.locale === "en") setLocale(me.locale);
        setAppName(settings.app_name);
        setAssistantEnabled(Boolean(settings.assistant_enabled));
        document.title = settings.app_name;
      } catch {
        clearSession();
        navigate("/", { replace: true });
      }
    })();
  }, [navigate]);

  useEffect(() => {
    function onAssistantFlag(e: Event) {
      const detail = (e as CustomEvent<{ enabled?: boolean }>).detail;
      if (typeof detail?.enabled === "boolean") setAssistantEnabled(detail.enabled);
    }
    window.addEventListener("dropt-assistant-enabled", onAssistantFlag as EventListener);
    return () => window.removeEventListener("dropt-assistant-enabled", onAssistantFlag as EventListener);
  }, []);

  function toggleSidebar() {
    setCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem(SIDEBAR_KEY, next ? "1" : "0");
      return next;
    });
  }

  function logout() {
    const token = getToken();
    void (token ? logoutApi(token).catch(() => undefined) : Promise.resolve()).finally(() => {
      clearSession();
      navigate("/", { replace: true });
    });
  }

  if (!user) {
    return (
      <div className="flex h-full items-center justify-center text-[var(--color-muted-foreground)]">
        {t("loading")}
      </div>
    );
  }

  return (
    <TooltipProvider>
      <div className="flex h-full min-h-0">
        <aside
          className={cn(
            "flex shrink-0 flex-col border-r border-[var(--color-border)] bg-[var(--color-card)]/90 backdrop-blur transition-[width] duration-200",
            collapsed ? "w-14" : "w-44",
          )}
        >
          <div className={cn("flex items-start gap-2 px-3 py-4", collapsed && "flex-col items-center px-2")}>
            <div className={cn("min-w-0 flex-1", collapsed && "hidden")}>
              <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-[var(--color-primary)]">
                {t("portal")}
              </p>
              <h1 className="mt-1 truncate text-lg font-semibold tracking-tight">{appName}</h1>
            </div>
            {collapsed ? (
              <p className="font-mono text-[10px] font-semibold text-[var(--color-primary)]">DO</p>
            ) : null}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8 shrink-0"
                  onClick={toggleSidebar}
                  aria-label={collapsed ? t("sidebar_expand") : t("sidebar_collapse")}
                >
                  {collapsed ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">
                {collapsed ? t("sidebar_expand") : t("sidebar_collapse")}
              </TooltipContent>
            </Tooltip>
          </div>
          <Separator />
          <nav className="flex flex-1 flex-col gap-1 overflow-y-auto p-2">
            {nav.map((item) => {
              const Icon = item.icon;
              const link = (
                <NavLink
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
                      collapsed && "justify-center px-2",
                      isActive
                        ? "bg-[var(--color-primary)]/15 text-[var(--theme-success-fg)]"
                        : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)] hover:text-[var(--color-foreground)]",
                    )
                  }
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  {!collapsed ? t(item.labelKey) : null}
                </NavLink>
              );
              if (!collapsed) {
                return <div key={item.to}>{link}</div>;
              }
              return (
                <Tooltip key={item.to}>
                  <TooltipTrigger asChild>{link}</TooltipTrigger>
                  <TooltipContent side="right">{t(item.labelKey)}</TooltipContent>
                </Tooltip>
              );
            })}
            {user.role === "admin" ? (
              <>
                {collapsed ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <NavLink
                        to="/app/users"
                        className={({ isActive }) =>
                          cn(
                            "flex items-center justify-center rounded-md px-2 py-2 text-sm transition-colors",
                            isActive
                              ? "bg-[var(--color-primary)]/15 text-[var(--theme-success-fg)]"
                              : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)] hover:text-[var(--color-foreground)]",
                          )
                        }
                      >
                        <Users className="h-4 w-4" />
                      </NavLink>
                    </TooltipTrigger>
                    <TooltipContent side="right">{t("nav_portal_users")}</TooltipContent>
                  </Tooltip>
                ) : (
                  <NavLink
                    to="/app/users"
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
                        isActive
                          ? "bg-[var(--color-primary)]/15 text-[var(--theme-success-fg)]"
                          : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)] hover:text-[var(--color-foreground)]",
                      )
                    }
                  >
                    <Users className="h-4 w-4" />
                    {t("nav_portal_users")}
                  </NavLink>
                )}
                {collapsed ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <NavLink
                        to="/app/system"
                        className={({ isActive }) =>
                          cn(
                            "flex items-center justify-center rounded-md px-2 py-2 text-sm transition-colors",
                            isActive
                              ? "bg-[var(--color-primary)]/15 text-[var(--theme-success-fg)]"
                              : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)] hover:text-[var(--color-foreground)]",
                          )
                        }
                      >
                        <ScrollText className="h-4 w-4" />
                      </NavLink>
                    </TooltipTrigger>
                    <TooltipContent side="right">{t("nav_system")}</TooltipContent>
                  </Tooltip>
                ) : (
                  <NavLink
                    to="/app/system"
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
                        isActive
                          ? "bg-[var(--color-primary)]/15 text-[var(--theme-success-fg)]"
                          : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)] hover:text-[var(--color-foreground)]",
                      )
                    }
                  >
                    <ScrollText className="h-4 w-4" />
                    {t("nav_system")}
                  </NavLink>
                )}
              </>
            ) : null}
          </nav>

          <div className="mt-auto flex h-12 shrink-0 items-center justify-between border-t border-[var(--color-border)] px-2">
            {user.role === "admin" || user.auth_source === "local" ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    className={cn(
                      "h-8 w-8 shrink-0",
                      settingsActive
                        ? "bg-[var(--color-primary)]/15 text-[var(--theme-success-fg)] hover:bg-[var(--color-primary)]/20"
                        : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)] hover:text-[var(--color-foreground)]",
                    )}
                    onClick={() => navigate("/app/settings")}
                    aria-label={t("nav_settings")}
                    aria-current={settingsActive ? "page" : undefined}
                  >
                    <Settings className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="right">{t("nav_settings")}</TooltipContent>
              </Tooltip>
            ) : (
              <span className="inline-block h-8 w-8 shrink-0" aria-hidden />
            )}

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8 shrink-0 text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)] hover:text-[var(--color-foreground)]"
                  onClick={logout}
                  aria-label={t("logout")}
                >
                  <LogOut className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">{t("logout")}</TooltipContent>
            </Tooltip>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 shrink-0 items-center justify-end gap-2 border-b border-[var(--color-border)] bg-[var(--color-card)]/70 px-4 backdrop-blur">
            <span className="mr-auto truncate text-sm text-[var(--color-muted-foreground)]">
              <span className="font-medium text-[var(--color-foreground)]">{user.username}</span>
              <span className="mx-1.5">·</span>
              <span className="font-mono text-xs">{user.role}</span>
            </span>

            {/* Açık temada ay (→ koyu); koyu temada güneş (→ açık) */}
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="h-9 w-9 text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)] hover:text-[var(--color-foreground)]"
              onClick={() => {
                const next = theme === "light" ? "dark" : "light";
                setTheme(next);
                const token = getToken();
                if (token) void updatePreferences(token, { theme: next }).catch(() => undefined);
              }}
              title={theme === "light" ? t("theme_dark") : t("theme_light")}
              aria-label={theme === "light" ? t("theme_dark") : t("theme_light")}
            >
              {theme === "light" ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
            </Button>

            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-9 gap-1.5 px-2 font-medium text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)] hover:text-[var(--color-foreground)]"
              onClick={() => {
                const next = locale === "tr" ? "en" : "tr";
                setLocale(next);
                const token = getToken();
                if (token) void updatePreferences(token, { locale: next }).catch(() => undefined);
              }}
              title={locale === "tr" ? "English" : "Türkçe"}
              aria-label={locale === "tr" ? "Switch to English" : "Türkçe'ye geç"}
            >
              <Languages className="h-4 w-4" />
              <span className="text-xs tracking-wide">{locale === "tr" ? "TR" : "EN"}</span>
            </Button>
          </header>

          <main className="min-h-0 flex-1 overflow-auto">
            <Outlet context={{ user, appName, setAppName }} />
          </main>
        </div>
        {assistantEnabled ? <AssistantFab /> : null}
      </div>
    </TooltipProvider>
  );
}
