import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { listServers, ServerPublic, terminalWsUrl } from "@dropt/api";
import { SingleServerField } from "@dropt/components/OpsLockedServer";
import { Button } from "@dropt/components/ui/button";
import { Input } from "@dropt/components/ui/input";
import { useServerQuery } from "@dropt/hooks/useServerQuery";
import { useI18n } from "@dropt/i18n/I18nProvider";
import { getStoredUser, getToken } from "@dropt/session";

export function TerminalPage() {
  const token = getToken()!;
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useI18n();
  const serversHome = location.pathname.startsWith("/level1") ? "/level1" : "/app/servers";
  const { serverId: qServerId } = useServerQuery();
  const user = useMemo(() => {
    try {
      return JSON.parse(getStoredUser() || "{}") as { role?: string };
    } catch {
      return {};
    }
  }, []);
  const isAdmin = user.role === "admin";

  const [servers, setServers] = useState<ServerPublic[]>([]);
  const [serverId, setServerId] = useState("");
  const [osUser, setOsUser] = useState(isAdmin ? "root" : "");
  const [osPass, setOsPass] = useState("");
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hostRef = useRef<HTMLDivElement | null>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    void listServers(token, { page: 1, page_size: 200, status: "ready" }).then((d) => {
      setServers(d.items);
      if (qServerId) setServerId(qServerId);
      else if (d.items[0]) setServerId(String(d.items[0].id));
    });
  }, [token, qServerId]);

  useEffect(() => {
    return () => {
      wsRef.current?.close();
      termRef.current?.dispose();
    };
  }, []);

  function disconnect() {
    wsRef.current?.close();
    wsRef.current = null;
    setConnected(false);
    setOsPass("");
  }

  function connect(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!serverId || !osUser.trim() || !osPass) {
      setError("Sunucu, kullanıcı ve şifre gerekli");
      return;
    }
    if (!hostRef.current) return;

    termRef.current?.dispose();
    const term = new Terminal({
      cursorBlink: true,
      fontFamily: "IBM Plex Mono, ui-monospace, monospace",
      fontSize: 13,
      theme: { background: "#0b1220", foreground: "#d7e0ea" },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(hostRef.current);
    fit.fit();
    termRef.current = term;
    fitRef.current = fit;

    const cols = term.cols;
    const rows = term.rows;
    const url = terminalWsUrl(Number(serverId), {
      token,
      username: osUser.trim(),
      password: osPass,
      cols: String(cols),
      rows: String(rows),
    });
    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      term.focus();
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") term.write(ev.data);
      else term.write(new Uint8Array(ev.data as ArrayBuffer));
    };
    ws.onerror = () => setError("WebSocket hatası");
    ws.onclose = () => {
      setConnected(false);
      term.writeln("\r\n[portal] Bağlantı kapandı");
      setOsPass("");
    };
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(data);
    });

    const onResize = () => {
      fit.fit();
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      }
    };
    window.addEventListener("resize", onResize);
    termRef.current = term;
    // cleanup resize on next connect via dispose
  }

  return (
    <div className="flex h-full min-h-0 flex-col px-6 py-6">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">{t("wizard_terminal")}</h2>
          <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">{t("terminal_subtitle")}</p>
        </div>
        <Button variant="outline" onClick={() => navigate(serversHome)}>
          {t("nav_servers")}
        </Button>
      </div>

      {!connected ? (
        <form
          onSubmit={connect}
          className="mb-4 max-w-xl space-y-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-4"
        >
          <p className="text-sm text-amber-200/90">{t("terminal_warning")}</p>
          <SingleServerField
            locked={Boolean(qServerId)}
            servers={servers}
            serverId={serverId}
            onChange={setServerId}
          />
          <Input
            className="font-mono"
            placeholder={t("username")}
            value={osUser}
            onChange={(e) => setOsUser(e.target.value)}
            required
          />
          <Input
            type="password"
            placeholder={t("password")}
            value={osPass}
            onChange={(e) => setOsPass(e.target.value)}
            required
            autoComplete="off"
          />
          {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
          <Button type="submit">{t("terminal_connect")}</Button>
        </form>
      ) : (
        <div className="mb-3 flex gap-2">
          <Button variant="destructive" size="sm" onClick={disconnect}>
            {t("terminal_disconnect")}
          </Button>
        </div>
      )}

      <div
        ref={hostRef}
        className="min-h-[420px] flex-1 overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--theme-terminal-bg)] p-2"
      />
    </div>
  );
}
