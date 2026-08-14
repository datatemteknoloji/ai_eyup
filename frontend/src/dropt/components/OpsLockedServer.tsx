import type { ServerPublic } from "@dropt/api";
import { ServerPicker } from "@dropt/components/ServerPicker";
import { useT } from "@dropt/i18n/I18nProvider";

/** Operasyon merkezinden / gömülü konsoldan gelen tek host — liste yok. */
export function OpsLockedServer({
  servers,
  serverId,
}: {
  servers: ServerPublic[];
  serverId: string;
}) {
  const t = useT();
  const s = servers.find((x) => String(x.id) === serverId);
  const line = s
    ? `${s.hostname}${s.ip ? ` · ${s.ip}` : ""}`
    : serverId || "—";
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--theme-inset,var(--bg-deep))] px-3 py-2">
      <p className="text-[11px] text-[var(--color-muted-foreground)]">{t("server")}</p>
      <p className="mt-0.5 font-mono text-sm text-[var(--color-foreground)]">{line}</p>
    </div>
  );
}

/** Tek-host sihirbaz: URL/konsol bağlamı varsa kilitli özet, yoksa seçici. */
export function SingleServerField({
  locked,
  servers,
  serverId,
  onChange,
  label,
  listClassName,
}: {
  locked: boolean;
  servers: ServerPublic[];
  serverId: string;
  onChange: (id: string) => void;
  label?: string;
  listClassName?: string;
}) {
  if (locked && serverId) {
    return <OpsLockedServer servers={servers} serverId={serverId} />;
  }
  return (
    <ServerPicker
      servers={servers}
      value={serverId ? [Number(serverId)] : []}
      onChange={(ids) => onChange(ids[0] ? String(ids[0]) : "")}
      multiple={false}
      label={label}
      listClassName={listClassName}
    />
  );
}
