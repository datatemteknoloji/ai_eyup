import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { I18nProvider } from "@/i18n/I18nProvider";
import { applyTheme, readStoredTheme, ThemeProvider } from "@/theme/ThemeProvider";
import "./index.css";

document.documentElement.lang = localStorage.getItem("dropt_locale") === "en" ? "en" : "tr";
applyTheme(readStoredTheme());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <I18nProvider>
        <App />
      </I18nProvider>
    </ThemeProvider>
  </StrictMode>,
);
