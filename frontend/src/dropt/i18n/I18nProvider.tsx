import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  dictionaries,
  formatMessage,
  type Locale,
  type TranslationKey,
} from "@dropt/i18n/messages";

const STORAGE_KEY = "dropt_locale";
const AINEW_KEY = "ainew_locale";
const AINEW_EVENT = "ainew-locale";

type I18nCtx = {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: TranslationKey, vars?: Record<string, string | number>) => string;
};

const Ctx = createContext<I18nCtx | null>(null);

function parseLocale(raw: string | null | undefined): Locale | null {
  return raw === "en" || raw === "tr" ? raw : null;
}

function readInitial(): Locale {
  return parseLocale(localStorage.getItem(AINEW_KEY))
    ?? parseLocale(localStorage.getItem(STORAGE_KEY))
    ?? "tr";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(readInitial);

  useEffect(() => {
    const sync = () => {
      const next = readInitial();
      setLocaleState(next);
      document.documentElement.lang = next;
    };
    window.addEventListener(AINEW_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(AINEW_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const setLocale = useCallback((l: Locale) => {
    // Embedded in ainew: parent LocaleProvider owns the preference.
    if (parseLocale(localStorage.getItem(AINEW_KEY))) return;
    localStorage.setItem(STORAGE_KEY, l);
    setLocaleState(l);
    document.documentElement.lang = l;
  }, []);

  const t = useCallback(
    (key: TranslationKey, vars?: Record<string, string | number>) => {
      const dict = dictionaries[locale] ?? dictionaries.tr;
      const msg = dict[key] ?? dictionaries.tr[key] ?? key;
      return vars ? formatMessage(msg, vars) : msg;
    },
    [locale],
  );

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);
  return createElement(Ctx.Provider, { value }, children);
}

export function useI18n(): I18nCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useI18n outside provider");
  return ctx;
}

export function useT() {
  return useI18n().t;
}
