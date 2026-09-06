import { FormEvent, useEffect, useMemo, useState } from "react";
import { Navigate, useLocation, useSearchParams } from "react-router-dom";
import {
  createJob,
  getIpChangeInventory,
  getNetworkInterfaces,
  IpChangeIface,
  IpChangeInventory,
  listServers,
  NetInterface,
  previewJob,
  ServerPublic,
} from "@dropt/api";
import { SingleServerField } from "@dropt/components/OpsLockedServer";
import { Button } from "@dropt/components/ui/button";
import { Input } from "@dropt/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@dropt/components/ui/select";
import { useServerQuery } from "@dropt/hooks/useServerQuery";
import { useAfterPreview, useOpsWizard } from "@dropt/hooks/useOpsWizard";
import { useI18n, useT } from "@dropt/i18n/I18nProvider";
import { buildIpChangeSuccessChecklist } from "@dropt/lib/opsPostchecks";
import {
  isValidGatewayIpv4,
  isValidHostIpv4,
  validateGatewayIpv4,
  validateHostIpv4,
} from "@dropt/lib/ipv4";
import { getToken } from "@dropt/session";
import { VlanPage } from "@dropt/pages/VlanPage";
import { Cable, Layers, ArrowLeftRight } from "lucide-react";
import { BackNavButton } from "@dropt/components/BackNavButton";

function prefixToMask(prefix: number): string {
  if (prefix < 0 || prefix > 32) return "";
  const mask = prefix === 0 ? 0 : (~0 << (32 - prefix)) >>> 0;
  return [24, 16, 8, 0].map((shift) => (mask >>> shift) & 255).join(".");
}

const SUBNET_OPTIONS = Array.from({ length: 23 }, (_, i) => 8 + i).map((p) => ({
  prefix: p,
  label: `/${p}  (${prefixToMask(p)})`,
}));

type Tab = "choice" | "network" | "vlan" | "ipchange";

function normalizeTab(raw: string): Tab {
  const v = raw.toLowerCase();
  if (v === "network" || v === "vlan" || v === "ipchange") return v;
  if (v === "ip") return "ipchange";
  return "choice";
}

function NetworkBackBar({ onBack }: { onBack: () => void }) {
  const t = useT();
  return (
    <div className="mb-3 flex items-center gap-2">
      <BackNavButton label={t("network_back_to_choice")} onClick={onBack} />
    </div>
  );
}

export function NetworkPage() {
  const t = useT();
  const opsCtx = useOpsWizard();
  const embedded = Boolean(opsCtx?.embedded);
  const [params, setParams] = useSearchParams();
  /** Console / embedded: her açılışta choice; URL tab yok sayılır. */
  const [embeddedTab, setEmbeddedTab] = useState<Tab>("choice");
  const [embeddedSession, setEmbeddedSession] = useState(0);

  useEffect(() => {
    if (!embedded) return;
    setEmbeddedTab("choice");
    setEmbeddedSession((n) => n + 1);
  }, [embedded, opsCtx?.serverId]);

  const urlTab = normalizeTab(params.get("tab") || params.get("mode") || "");
  const tab: Tab = embedded ? embeddedTab : urlTab;

  function go(next: Tab) {
    if (embedded) {
      setEmbeddedTab(next);
      return;
    }
    const nextParams = new URLSearchParams(params);
    if (next === "choice") {
      nextParams.delete("tab");
      nextParams.delete("mode");
    } else {
      nextParams.set("tab", next);
      nextParams.delete("mode");
    }
    setParams(nextParams, { replace: true });
  }

  const shell = embedded ? "px-4 py-3 md:px-5 md:py-4" : "px-6 py-5 md:px-8 md:py-6";

  if (tab === "vlan") {
    return (
      <div className={shell}>
        <NetworkBackBar onBack={() => go("choice")} />
        <VlanPage key={`vlan-${embeddedSession}`} embeddedTitle />
      </div>
    );
  }

  if (tab === "network") {
    return (
      <div className={shell}>
        <NetworkBackBar onBack={() => go("choice")} />
        <AddNetworkForm key={`net-${embeddedSession}`} />
      </div>
    );
  }

  if (tab === "ipchange") {
    return (
      <div className={shell}>
        <NetworkBackBar onBack={() => go("choice")} />
        <IpChangeForm key={`ip-${embeddedSession}`} />
      </div>
    );
  }

  const netChoices = [
    {
      tab: "network" as Tab,
      title: t("network_add_network"),
      hint: t("network_add_network_hint"),
      icon: Cable,
      tone: "bg-[var(--accent-subtle)] text-[var(--accent)]",
    },
    {
      tab: "vlan" as Tab,
      title: t("network_add_vlan"),
      hint: t("network_add_vlan_hint"),
      icon: Layers,
      tone: "bg-[var(--info-bg)] text-[var(--info)]",
    },
    {
      tab: "ipchange" as Tab,
      title: t("network_ip_change"),
      hint: t("network_ip_change_hint"),
      icon: ArrowLeftRight,
      tone: "bg-[var(--warning-bg)] text-[var(--warning)]",
    },
  ];

  return (
    <div className={shell}>
      {!embedded ? (
        <>
          <h2 className="text-lg font-semibold tracking-tight">{t("wizard_network")}</h2>
          <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">{t("network_mgmt_sub")}</p>
        </>
      ) : (
        <p className="mb-1 text-sm text-[var(--color-muted-foreground)]">{t("network_mgmt_sub")}</p>
      )}
      <div className={`${embedded ? "mt-3" : "mt-4"} grid gap-3 sm:grid-cols-3`}>
        {netChoices.map((c) => {
          const Icon = c.icon;
          return (
            <button
              key={c.tab}
              type="button"
              onClick={() => go(c.tab)}
              className="group flex flex-col rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-4 text-left transition hover:border-[var(--color-primary)]/50 hover:bg-[var(--accent-subtle,var(--color-accent))]"
            >
              <span
                className={`mb-3 grid h-10 w-10 place-items-center rounded-lg transition group-hover:scale-105 ${c.tone}`}
              >
                <Icon className="h-5 w-5" />
              </span>
              <p className="text-sm font-semibold text-[var(--color-foreground)]">{c.title}</p>
              <p className="mt-1.5 flex-1 text-xs leading-relaxed text-[var(--color-muted-foreground)]">
                {c.hint}
              </p>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function AddNetworkForm() {
  const token = getToken()!;
  const afterPreview = useAfterPreview();
  const opsCtx = useOpsWizard();
  const embedded = Boolean(opsCtx?.embedded);
  const t = useT();
  const { serverId: qServerId } = useServerQuery();
  const [servers, setServers] = useState<ServerPublic[]>([]);
  const [ifaces, setIfaces] = useState<NetInterface[]>([]);
  const [nextBond, setNextBond] = useState("bond1");
  const [ifacesLoading, setIfacesLoading] = useState(false);
  const [serverId, setServerId] = useState("");
  const [connType, setConnType] = useState<"ethernet" | "bond">("ethernet");
  const [iface, setIface] = useState("");
  const [slaves, setSlaves] = useState<string[]>([]);
  const [bondMode, setBondMode] = useState("1");
  const [vlanId, setVlanId] = useState("");
  const [ip, setIp] = useState("");
  const [subnet, setSubnet] = useState("24");
  const [gateway, setGateway] = useState("");
  const [talepId, setTalepId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const effectiveServerId = embedded && opsCtx?.serverId ? opsCtx.serverId : serverId;

  useEffect(() => {
    void listServers(token, { page: 1, page_size: 200, status: "ready" }).then((d) => {
      setServers(d.items);
      if (embedded && opsCtx?.serverId) setServerId(opsCtx.serverId);
      else if (qServerId) setServerId(qServerId);
      else if (d.items[0]) setServerId(String(d.items[0].id));
    });
  }, [token, qServerId, embedded, opsCtx?.serverId]);

  useEffect(() => {
    if (!effectiveServerId) return;
    setIfacesLoading(true);
    setError(null);
    void getNetworkInterfaces(token, Number(effectiveServerId))
      .then((d) => {
        setIfaces(d.interfaces || []);
        setNextBond(d.next_bond_name || "bond1");
        setIface((prev) => {
          if (prev && d.interfaces.some((i) => i.name === prev)) return prev;
          return d.interfaces[0]?.name || "";
        });
        setSlaves((prev) => prev.filter((s) => d.interfaces.some((i) => i.name === s)));
      })
      .catch((err) => {
        setIfaces([]);
        setError(err instanceof Error ? err.message : "Interface listesi alınamadı");
      })
      .finally(() => setIfacesLoading(false));
  }, [token, effectiveServerId]);

  const accessHint = vlanId.trim() ? t("network_trunk_hint") : t("network_access_hint");

  const formComplete = useMemo(() => {
    if (ifacesLoading || !effectiveServerId || !talepId.trim()) return false;
    if (connType === "ethernet") {
      if (!iface || !ifaces.some((i) => i.name === iface)) return false;
    } else {
      if (slaves.length < 1) return false;
      if (!bondMode) return false;
    }
    if (!subnet) return false;
    if (!isValidHostIpv4(ip) || !isValidGatewayIpv4(gateway)) return false;
    if (ip.trim() === gateway.trim()) return false;
    if (vlanId.trim()) {
      const vid = Number(vlanId.trim());
      if (!Number.isInteger(vid) || vid < 1 || vid > 4094) return false;
    }
    return true;
  }, [
    ifacesLoading,
    effectiveServerId,
    talepId,
    connType,
    iface,
    ifaces,
    slaves,
    bondMode,
    subnet,
    ip,
    gateway,
    vlanId,
  ]);

  const ipError = ip.trim() ? validateHostIpv4(ip) : null;
  const gatewayError = gateway.trim() ? validateGatewayIpv4(gateway) : null;

  function toggleSlave(name: string) {
    setSlaves((prev) => (prev.includes(name) ? prev.filter((x) => x !== name) : [...prev, name]));
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (!formComplete) throw new Error("Formu tamamlayın");
      const payload: Record<string, unknown> = {
        connection_type: connType,
        ip: ip.trim(),
        subnet: Number(subnet),
        gateway: gateway.trim(),
      };
      if (vlanId.trim()) payload.vlan_id = Number(vlanId.trim());
      if (connType === "ethernet") {
        payload.interface = iface;
      } else {
        payload.mode = bondMode;
        payload.slaves = slaves;
        payload.bond_name = nextBond;
      }
      const job = await createJob(token, {
        module: "network",
        action: "add_network",
        talep_id: talepId.trim(),
        server_ids: [Number(effectiveServerId)],
        payload,
      });
      afterPreview(await previewJob(token, job.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h2 className="text-lg font-semibold tracking-tight text-[var(--color-foreground)]">
        {t("network_add_network")}
      </h2>
      <p className="mt-1 rounded-lg border border-[var(--info)]/20 bg-[var(--info-bg,rgba(56,189,248,0.1))] px-3 py-2 text-xs leading-relaxed text-[var(--text-secondary,var(--color-muted-foreground))]">
        {accessHint}
      </p>
      <form
        onSubmit={onSubmit}
        className="mt-3 max-w-xl space-y-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-4"
      >
        <div>
          <label className="mb-1.5 block text-xs text-[var(--color-muted-foreground)]">{t("talep_id")}</label>
          <Input
            className="h-9"
            value={talepId}
            onChange={(e) => setTalepId(e.target.value)}
            placeholder="Örn. TLP-NET-001"
            required
          />
        </div>

        <SingleServerField
          locked={Boolean(qServerId) || embedded}
          servers={servers}
          serverId={String(effectiveServerId || "")}
          onChange={setServerId}
        />

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1.5 block text-xs text-[var(--color-muted-foreground)]">Bağlantı tipi</label>
            <Select value={connType} onValueChange={(v) => setConnType(v as "ethernet" | "bond")}>
              <SelectTrigger className="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ethernet">ethernet</SelectItem>
                <SelectItem value="bond">bond</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {connType === "ethernet" ? (
            <div>
              <label className="mb-1.5 block text-xs text-[var(--color-muted-foreground)]">Interface</label>
              {ifacesLoading ? (
                <p className="flex h-9 items-center text-xs text-[var(--color-muted-foreground)]">Yükleniyor…</p>
              ) : (
                <Select value={iface || undefined} onValueChange={setIface} disabled={!ifaces.length}>
                  <SelectTrigger className="h-9">
                    <SelectValue placeholder={ifaces.length ? "Interface seçin" : "Uygun interface yok"} />
                  </SelectTrigger>
                  <SelectContent>
                    {ifaces.map((i) => (
                      <SelectItem key={i.name} value={i.name}>
                        {i.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          ) : (
            <div>
              <label className="mb-1.5 block text-xs text-[var(--color-muted-foreground)]">Bond mode</label>
              <Select value={bondMode} onValueChange={setBondMode}>
                <SelectTrigger className="h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="1">mode=1 active-backup</SelectItem>
                  <SelectItem value="4">mode=4 802.3ad (LACP)</SelectItem>
                  <SelectItem value="6">mode=6 balance-alb</SelectItem>
                </SelectContent>
              </Select>
              <p className="mt-1 font-mono text-[11px] text-[var(--color-muted-foreground)]">→ {nextBond}</p>
            </div>
          )}
        </div>

        {connType === "bond" ? (
          <div>
            <label className="mb-1.5 block text-xs text-[var(--color-muted-foreground)]">Bond slaves</label>
            {ifacesLoading ? (
              <p className="text-xs text-[var(--color-muted-foreground)]">Yükleniyor…</p>
            ) : (
              <div className="max-h-36 space-y-1 overflow-y-auto rounded-lg border border-[var(--color-border)] p-2">
                {ifaces.map((i) => (
                  <label key={i.name} className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-sm hover:bg-white/[0.04]">
                    <input
                      type="checkbox"
                      checked={slaves.includes(i.name)}
                      onChange={() => toggleSlave(i.name)}
                    />
                    <span className="font-mono">{i.name}</span>
                  </label>
                ))}
                {!ifaces.length ? (
                  <p className="text-xs text-[var(--color-muted-foreground)]">Uygun interface yok</p>
                ) : null}
              </div>
            )}
          </div>
        ) : null}

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1.5 block text-xs text-[var(--color-muted-foreground)]">
              VLAN ID <span className="font-normal opacity-70">(opsiyonel)</span>
            </label>
            <Input
              className="h-9 font-mono"
              type="number"
              min={1}
              max={4094}
              placeholder="boş = access"
              value={vlanId}
              onChange={(e) => setVlanId(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs text-[var(--color-muted-foreground)]">IP</label>
            <Input className="h-9 font-mono" value={ip} onChange={(e) => setIp(e.target.value)} required />
            {ipError ? <p className="mt-1 text-xs text-[var(--color-destructive)]">{ipError}</p> : null}
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1.5 block text-xs text-[var(--color-muted-foreground)]">Subnet</label>
            <Select value={subnet} onValueChange={setSubnet}>
              <SelectTrigger className="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SUBNET_OPTIONS.map((o) => (
                  <SelectItem key={o.prefix} value={String(o.prefix)}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="mb-1.5 block text-xs text-[var(--color-muted-foreground)]">Gateway</label>
            <Input
              className="h-9 font-mono"
              value={gateway}
              onChange={(e) => setGateway(e.target.value)}
              required
            />
            {gatewayError ? (
              <p className="mt-1 text-xs text-[var(--color-destructive)]">{gatewayError}</p>
            ) : null}
          </div>
        </div>

        {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
        <div className="flex justify-end border-t border-[var(--color-border)] pt-3">
          <Button type="submit" className="h-9 px-4" disabled={busy || !formComplete}>
            {busy ? "…" : t("preview")}
          </Button>
        </div>
      </form>
    </>
  );
}

function buildDnsTicket(fqdn: string, oldIp: string, newIp: string): string {
  const f = fqdn.replace(/\.$/, "");
  return `${f} - ${oldIp} dns kaydının "${f} - ${newIp}" olarak değiştirilmesini rica ederiz.`;
}

function IpChangeForm() {
  const token = getToken()!;
  const afterPreview = useAfterPreview();
  const opsCtx = useOpsWizard();
  const embedded = Boolean(opsCtx?.embedded);
  const { t, locale } = useI18n();
  const { serverId: qServerId } = useServerQuery();
  const [servers, setServers] = useState<ServerPublic[]>([]);
  const [inv, setInv] = useState<IpChangeInventory | null>(null);
  const [loading, setLoading] = useState(false);
  const [serverId, setServerId] = useState("");
  const [iface, setIface] = useState("");
  const [ip, setIp] = useState("");
  const [subnet, setSubnet] = useState("24");
  const [gateway, setGateway] = useState("");
  const [vlanId, setVlanId] = useState("");
  const [dns, setDns] = useState("");
  const [dnsSearch, setDnsSearch] = useState("");
  const [talepId, setTalepId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const effectiveServerId = embedded && opsCtx?.serverId ? opsCtx.serverId : serverId;

  useEffect(() => {
    void listServers(token, { page: 1, page_size: 200, status: "ready" }).then((d) => {
      setServers(d.items);
      if (embedded && opsCtx?.serverId) setServerId(opsCtx.serverId);
      else if (qServerId) setServerId(qServerId);
      else if (d.items[0]) setServerId(String(d.items[0].id));
    });
  }, [token, qServerId, embedded, opsCtx?.serverId]);

  useEffect(() => {
    if (!effectiveServerId) return;
    setLoading(true);
    setError(null);
    void getIpChangeInventory(token, Number(effectiveServerId))
      .then((d) => {
        setInv(d);
        const first = d.interfaces.find((i) => i.is_primary) || d.interfaces[0];
        setIface(first?.name || "");
      })
      .catch((err) => {
        setInv(null);
        setError(err instanceof Error ? err.message : "Envanter alınamadı");
      })
      .finally(() => setLoading(false));
  }, [token, effectiveServerId]);

  const selected: IpChangeIface | null = useMemo(() => {
    if (!inv || !iface) return null;
    return inv.interfaces.find((i) => i.name === iface) || null;
  }, [inv, iface]);

  useEffect(() => {
    if (!selected || !inv) return;
    setIp(selected.ip || "");
    setSubnet(String(selected.subnet || 24));
    setGateway(selected.gateway || "");
    setVlanId(selected.vlan_id != null ? String(selected.vlan_id) : "");
    if (selected.is_primary) {
      setDns((inv.dns || []).join(", "));
      setDnsSearch((inv.dns_search || []).join(" "));
    } else {
      setDns("");
      setDnsSearch("");
    }
  }, [selected?.name, inv]);

  const displayFqdn = useMemo(() => {
    if (!inv) return "—";
    const fq = (inv.fqdn || "").trim().replace(/\.$/, "");
    if (fq) return fq;
    const s = (inv.short_name || "").trim();
    const d = (inv.domain || "").trim();
    if (s && d) return `${s}.${d}`;
    return s || "—";
  }, [inv]);

  const ticketText = useMemo(() => {
    if (!selected || !inv) return "";
    if (!ip.trim() || ip.trim() === selected.ip) return "";
    if (!displayFqdn || displayFqdn === "—") return "";
    return buildDnsTicket(displayFqdn, selected.ip, ip.trim());
  }, [selected, inv, ip, displayFqdn]);

  const dnsQueryHost = useMemo(() => {
    const ns = inv?.nslookup;
    const fromNs = String(ns?.resolved_fqdn || ns?.forward_fqdn || "").trim().replace(/\.$/, "");
    return fromNs || displayFqdn;
  }, [inv?.nslookup, displayFqdn]);

  const dnsQueryIp = useMemo(() => {
    const ns = inv?.nslookup;
    const fromNs = String(ns?.resolved_ip || "").trim();
    if (fromNs) return fromNs;
    const primary = inv?.interfaces?.find((i) => i.is_primary);
    return primary?.ip || selected?.ip || "—";
  }, [inv?.nslookup, inv?.interfaces, selected?.ip]);

  const successChecklist = useMemo(
    () =>
      buildIpChangeSuccessChecklist(
        locale,
        displayFqdn,
        selected?.ip || "—",
        ip.trim() || selected?.ip || "—",
        Boolean(selected?.is_primary),
      ),
    [locale, displayFqdn, selected?.ip, selected?.is_primary, ip],
  );

  const formComplete = useMemo(() => {
    if (loading || !effectiveServerId || !talepId.trim() || !selected) return false;
    if (!subnet || !isValidHostIpv4(ip) || !isValidGatewayIpv4(gateway)) return false;
    if (ip.trim() === gateway.trim()) return false;
    if (selected.has_vlan) {
      const vid = Number(vlanId.trim());
      if (!Number.isInteger(vid) || vid < 1 || vid > 4094) return false;
    }
    if (selected.is_primary) {
      if (!dns.trim() || !dnsSearch.trim()) return false;
    }
    return true;
  }, [loading, effectiveServerId, talepId, selected, subnet, ip, gateway, vlanId, dns, dnsSearch]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (!formComplete || !selected) throw new Error("Formu tamamlayın");
      const payload: Record<string, unknown> = {
        interface: selected.name,
        ip: ip.trim(),
        subnet: Number(subnet),
        gateway: gateway.trim(),
      };
      if (selected.has_vlan) payload.vlan_id = Number(vlanId.trim());
      if (selected.is_primary) {
        payload.dns = dns
          .split(/[\s,;]+/)
          .map((x) => x.trim())
          .filter(Boolean);
        payload.dns_search = dnsSearch
          .split(/[\s,;]+/)
          .map((x) => x.trim())
          .filter(Boolean);
      }
      const job = await createJob(token, {
        module: "network",
        action: "change_ip",
        talep_id: talepId.trim(),
        server_ids: [Number(effectiveServerId)],
        payload,
      });
      afterPreview(await previewJob(token, job.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h2 className="text-lg font-semibold tracking-tight">{t("network_ip_change")}</h2>
      <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">{t("network_ip_change_sub")}</p>

      <div className="mt-2 w-full rounded-lg border border-amber-500/35 bg-amber-500/10 px-3 py-2 text-xs text-[var(--color-foreground)]">
        {t("network_ip_change_dns_warn")}
      </div>

      <form
        onSubmit={onSubmit}
        className="mt-3 w-full space-y-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-4"
      >
        <div>
          <label className="mb-1.5 block text-xs text-[var(--color-muted-foreground)]">{t("talep_id")}</label>
          <Input
            className="h-9"
            value={talepId}
            onChange={(e) => setTalepId(e.target.value)}
            placeholder="Örn. TLP-IP-001"
            required
          />
        </div>

        <SingleServerField
          locked={Boolean(qServerId) || embedded}
          servers={servers}
          serverId={String(effectiveServerId || "")}
          onChange={setServerId}
        />

        {inv ? (
          <p className="text-xs text-[var(--color-muted-foreground)]">
            FQDN: <span className="font-mono">{inv.fqdn || "—"}</span>
            {" · "}
            default: <span className="font-mono">{inv.default_route?.dev || "—"}</span>
            {inv.default_route?.src ? (
              <>
                {" / src "}
                <span className="font-mono">{inv.default_route.src}</span>
              </>
            ) : null}
          </p>
        ) : null}

        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">Interface</label>
          {loading ? (
            <p className="text-xs text-[var(--color-muted-foreground)]">Yükleniyor…</p>
          ) : (
            <Select value={iface || undefined} onValueChange={setIface} disabled={!inv?.interfaces.length}>
              <SelectTrigger>
                <SelectValue placeholder={inv?.interfaces.length ? "Interface" : "Uygun interface yok"} />
              </SelectTrigger>
              <SelectContent>
                {(inv?.interfaces || []).map((i) => (
                  <SelectItem key={i.name} value={i.name}>
                    {i.name} · {i.ip_cidr}
                    {i.is_primary ? " · ana IP" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>

        {selected?.is_primary ? (
          <p className="text-xs text-[var(--color-muted-foreground)]">{t("network_ip_change_primary_hint")}</p>
        ) : null}

        {selected?.has_vlan ? (
          <div>
            <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">VLAN ID</label>
            <Input
              className="font-mono"
              type="number"
              min={1}
              max={4094}
              value={vlanId}
              onChange={(e) => setVlanId(e.target.value)}
              required
            />
          </div>
        ) : null}

        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">IP</label>
          <Input className="font-mono" value={ip} onChange={(e) => setIp(e.target.value)} required />
        </div>

        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">Subnet</label>
          <Select value={subnet} onValueChange={setSubnet}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SUBNET_OPTIONS.map((o) => (
                <SelectItem key={o.prefix} value={String(o.prefix)}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">Gateway</label>
          <Input className="font-mono" value={gateway} onChange={(e) => setGateway(e.target.value)} required />
        </div>

        {selected?.is_primary ? (
          <>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                DNS <span className="opacity-70">(nameserver, virgül/boşluk)</span>
              </label>
              <Input className="font-mono" value={dns} onChange={(e) => setDns(e.target.value)} required />
            </div>
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">
                DNS-search <span className="opacity-70">(search)</span>
              </label>
              <Input className="font-mono" value={dnsSearch} onChange={(e) => setDnsSearch(e.target.value)} required />
            </div>
          </>
        ) : null}

        {ticketText ? (
          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-muted)]/30 p-3">
            <p className="text-xs font-medium text-[var(--color-muted-foreground)]">
              {t("network_ip_change_ticket_label")}
            </p>
            <p className="mt-1 font-mono text-xs leading-relaxed">{ticketText}</p>
          </div>
        ) : null}

        {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
        <div className="flex justify-end border-t border-[var(--color-border)] pt-3">
          <Button type="submit" className="h-9 px-4" disabled={busy || !formComplete}>
            {busy ? "…" : t("preview")}
          </Button>
        </div>
      </form>

      <div className="mt-4 w-full space-y-3">
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--theme-inset)] px-4 py-3 text-xs">
          <p className="text-[10px] font-medium uppercase tracking-wide text-[var(--color-muted-foreground)]">
            {t("ops_dns_query_result")}
          </p>
          <p className="mt-1 font-mono text-sm text-[var(--color-foreground)]">
            {t("ops_dns_query_hostname")}:{" "}
            <span className="font-semibold">{dnsQueryHost || "—"}</span>
            {" · "}
            {t("ops_dns_query_ip")}: <span className="font-semibold">{dnsQueryIp || "—"}</span>
          </p>
          {selected ? (
            <p className="mt-1 text-[10px] text-[var(--color-muted-foreground)]">
              {t("ops_selected_iface")}:{" "}
              <span className="font-mono">{selected.name}</span>
              {selected.is_primary
                ? ` · ${t("ops_primary_ip_dns")}`
                : ` · ${t("ops_secondary_ip_dns")}`}
            </p>
          ) : null}
        </div>
        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-card)]/60 p-4 text-sm text-[var(--color-muted-foreground)]">
          <p className="font-medium text-[var(--color-foreground)]">{t("ops_success_checklist")}</p>
          <p className="mt-2 text-xs text-[var(--color-muted-foreground)]">
            {t("ops_success_checklist_hint_ip")}
          </p>
          <ol className="mt-3 list-decimal space-y-3 pl-5">
            {successChecklist.map((item, idx) => (
              <li key={idx} className="whitespace-pre-wrap text-[var(--color-foreground)]/90">
                {item}
              </li>
            ))}
          </ol>
        </div>
      </div>
    </>
  );
}

/** Eski /app/vlan bookmark → Network Management */
export function VlanRedirect() {
  const [params] = useSearchParams();
  const loc = useLocation();
  const next = new URLSearchParams(params);
  next.set("tab", "vlan");
  next.delete("mode");
  const base = loc.pathname.startsWith("/level1") ? "/level1/ops/network" : "/app/network";
  return <Navigate to={`${base}?${next.toString()}`} replace />;
}
