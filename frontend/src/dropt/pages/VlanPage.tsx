import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  createJob,
  listInterfaces,
  listServers,
  NetInterface,
  previewJob,
  ServerPublic,
} from "@dropt/api";
import { ServerPicker } from "@dropt/components/ServerPicker";
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
import { useT } from "@dropt/i18n/I18nProvider";
import {
  isValidGatewayIpv4,
  isValidHostIpv4,
  validateGatewayIpv4,
  validateHostIpv4,
} from "@dropt/lib/ipv4";
import { getToken } from "@dropt/session";

/** /prefix → dotted netmask (IPv4) */
function prefixToMask(prefix: number): string {
  if (prefix < 0 || prefix > 32) return "";
  const mask = prefix === 0 ? 0 : (~0 << (32 - prefix)) >>> 0;
  return [24, 16, 8, 0].map((shift) => (mask >>> shift) & 255).join(".");
}

const SUBNET_OPTIONS = Array.from({ length: 23 }, (_, i) => 8 + i).map((p) => ({
  prefix: p,
  label: `/${p}  (${prefixToMask(p)})`,
}));

export function VlanPage({ embeddedTitle = false }: { embeddedTitle?: boolean } = {}) {
  const token = getToken()!;
  const afterPreview = useAfterPreview();
  const opsCtx = useOpsWizard();
  const embedded = Boolean(opsCtx?.embedded);
  const t = useT();
  const { serverId: qServerId } = useServerQuery();
  const [servers, setServers] = useState<ServerPublic[]>([]);
  const [ifaces, setIfaces] = useState<NetInterface[]>([]);
  const [ifacesLoading, setIfacesLoading] = useState(false);
  const [serverId, setServerId] = useState("");
  const [parent, setParent] = useState("");
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
      if (embedded && opsCtx?.serverId) {
        setServerId(opsCtx.serverId);
      } else if (qServerId) {
        setServerId(qServerId);
      } else if (d.items[0]) {
        setServerId(String(d.items[0].id));
      }
    });
  }, [token, qServerId, embedded, opsCtx?.serverId]);

  useEffect(() => {
    if (!effectiveServerId) return;
    setIfacesLoading(true);
    setError(null);
    void listInterfaces(token, Number(effectiveServerId))
      .then((rows) => {
        const visible = rows.filter((r) => !r.hidden);
        setIfaces(visible);
        setParent((prev) => {
          if (prev && visible.some((i) => i.name === prev)) return prev;
          return visible[0]?.name || "";
        });
      })
      .catch((err) => {
        setIfaces([]);
        setParent("");
        setError(err instanceof Error ? err.message : "Arayüz listesi alınamadı");
      })
      .finally(() => setIfacesLoading(false));
  }, [token, effectiveServerId]);

  const predictedName = useMemo(() => {
    if (!parent || !vlanId.trim()) return "";
    return `${parent}.${vlanId.trim()}`;
  }, [parent, vlanId]);

  const formComplete = useMemo(() => {
    if (ifacesLoading || !effectiveServerId || !parent.trim()) return false;
    if (!ifaces.some((i) => i.name === parent)) return false;
    if (!talepId.trim()) return false;
    const vid = Number(vlanId.trim());
    if (!Number.isInteger(vid) || vid < 1 || vid > 4094) return false;
    if (!subnet) return false;
    if (!isValidHostIpv4(ip)) return false;
    if (!isValidGatewayIpv4(gateway)) return false;
    if (ip.trim() === gateway.trim()) return false;
    return true;
  }, [
    ifacesLoading,
    effectiveServerId,
    parent,
    ifaces,
    talepId,
    vlanId,
    ip,
    gateway,
    subnet,
  ]);

  const ipError = ip.trim() ? validateHostIpv4(ip) : null;
  const gatewayError = gateway.trim() ? validateGatewayIpv4(gateway) : null;
  const sameIpGw =
    ip.trim() && gateway.trim() && ip.trim() === gateway.trim()
      ? "Gateway, IP ile aynı olamaz"
      : null;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (ifacesLoading) throw new Error("Interface listesi yükleniyor, bekleyin");
      if (!effectiveServerId) throw new Error("Sunucu seçin");
      if (!parent.trim()) throw new Error("Interface seçin (liste yüklenene kadar bekleyin)");
      if (!ifaces.some((i) => i.name === parent)) {
        throw new Error("Geçerli bir Interface seçin");
      }
      if (!talepId.trim()) throw new Error("Talep ID zorunlu");
      const vid = Number(vlanId.trim());
      if (!Number.isInteger(vid) || vid < 1 || vid > 4094) {
        throw new Error("VLAN ID 1–4094 arasında olmalı");
      }
      if (!ip.trim()) throw new Error("IP zorunlu");
      const ipErr = validateHostIpv4(ip);
      if (ipErr) throw new Error(ipErr);
      if (!gateway.trim()) throw new Error("Gateway zorunlu");
      const gwErr = validateGatewayIpv4(gateway);
      if (gwErr) throw new Error(gwErr);
      if (ip.trim() === gateway.trim()) throw new Error("Gateway, IP ile aynı olamaz");
      const job = await createJob(token, {
        module: "vlan",
        action: "add",
        talep_id: talepId.trim(),
        server_ids: [Number(effectiveServerId)],
        payload: {
          parent: parent.trim(),
          vlan_id: vid,
          ip: ip.trim(),
          subnet: Number(subnet),
          gateway: gateway.trim(),
        },
      });
      afterPreview(await previewJob(token, job.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Hata");
    } finally {
      setBusy(false);
    }
  }

  const canSubmit = !busy && formComplete;

  return (
    <div className={embeddedTitle ? undefined : "px-6 py-5 md:px-8"}>
      <h2 className="text-lg font-semibold tracking-tight">
        {embeddedTitle ? t("network_add_vlan") : t("wizard_vlan")}
      </h2>
      <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">
        Yönetim / docker / ilo arayüzleri gizli · con-name = ifname = Interface.VLAN
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
            placeholder="Örn. TLP-VLAN-001"
            required
          />
        </div>

        {!embedded ? (
          <ServerPicker
            servers={servers}
            value={serverId ? [Number(serverId)] : []}
            onChange={(ids) => setServerId(ids[0] ? String(ids[0]) : "")}
            multiple={false}
          />
        ) : (
          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--theme-inset,var(--bg-deep))] px-3 py-2">
            <p className="text-[11px] text-[var(--color-muted-foreground)]">{t("server")}</p>
            <p className="mt-0.5 font-mono text-sm text-[var(--color-foreground)]">
              {servers.find((s) => String(s.id) === effectiveServerId)?.hostname || effectiveServerId}
            </p>
          </div>
        )}

        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">Interface</label>
          {ifacesLoading ? (
            <p className="text-xs text-[var(--color-muted-foreground)]">Interface listesi yükleniyor…</p>
          ) : (
            <Select value={parent || undefined} onValueChange={setParent} disabled={!ifaces.length}>
              <SelectTrigger>
                <SelectValue placeholder={ifaces.length ? "Interface" : "Uygun interface yok"} />
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
          {predictedName ? (
            <p className="mt-1 font-mono text-[11px] text-[var(--color-muted-foreground)]">
              → {predictedName}
            </p>
          ) : null}
        </div>

        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">VLAN ID</label>
          <Input
            className="font-mono"
            type="number"
            min={1}
            max={4094}
            placeholder="örn. 12"
            value={vlanId}
            onChange={(e) => setVlanId(e.target.value)}
            required
          />
        </div>

        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">IP</label>
          <Input
            className="font-mono"
            placeholder="örn. 192.168.1.224"
            value={ip}
            onChange={(e) => setIp(e.target.value)}
            required
          />
          {ipError ? (
            <p className="mt-1 text-xs text-[var(--color-destructive)]">{ipError}</p>
          ) : (
            <p className="mt-1 text-[10px] text-[var(--color-muted-foreground)]">
              4 octet · yalnız rakam · octet başında 0 yok
            </p>
          )}
        </div>

        <div>
          <label className="mb-1 block text-xs text-[var(--color-muted-foreground)]">Subnet</label>
          <Select value={subnet} onValueChange={setSubnet}>
            <SelectTrigger>
              <SelectValue placeholder="Subnet" />
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
          <Input
            className="font-mono"
            placeholder="örn. 192.168.1.1"
            value={gateway}
            onChange={(e) => setGateway(e.target.value)}
            required
          />
          {sameIpGw || gatewayError ? (
            <p className="mt-1 text-xs text-[var(--color-destructive)]">{sameIpGw || gatewayError}</p>
          ) : (
            <p className="mt-1 text-[10px] text-[var(--color-muted-foreground)]">
              Unicast · 0.x / 127.x / 255.255.255.255 / multicast yok
            </p>
          )}
        </div>

        {error ? <p className="text-sm text-[var(--color-destructive)]">{error}</p> : null}
        <div className="flex justify-end border-t border-[var(--color-border)] pt-3">
          <Button type="submit" className="h-9 px-4" disabled={!canSubmit}>
            {busy ? "…" : ifacesLoading ? "Interface yükleniyor…" : t("preview")}
          </Button>
        </div>
      </form>
    </div>
  );
}
