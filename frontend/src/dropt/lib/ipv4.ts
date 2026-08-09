/** Katı IPv4: 4 octet, yalnız rakam, octet başında 0 yok (0 tek başına OK). */
export function parseStrictIpv4(value: string): number[] | null {
  const s = value.trim();
  if (!s) return null;
  const parts = s.split(".");
  if (parts.length !== 4) return null;
  const octets: number[] = [];
  for (const part of parts) {
    if (!/^\d+$/.test(part)) return null;
    if (part.length > 1 && part.startsWith("0")) return null;
    const n = Number(part);
    if (n > 255) return null;
    octets.push(n);
  }
  return octets;
}

export function validateHostIpv4(value: string): string | null {
  const octets = parseStrictIpv4(value);
  if (!octets) {
    return "Geçerli IPv4 girin (örn. 192.168.1.10 · 4 octet · octet başında 0 yok)";
  }
  if (octets.every((n) => n === 0)) return "0.0.0.0 geçerli bir IP değil";
  if (octets.every((n) => n === 255)) return "255.255.255.255 geçerli bir IP değil";
  if (octets[0] === 127) return "Loopback (127.x) kullanılamaz";
  if (octets[0]! >= 224) return "Multicast adresi kullanılamaz";
  return null;
}

export function validateGatewayIpv4(value: string): string | null {
  const octets = parseStrictIpv4(value);
  if (!octets) {
    return "Geçerli gateway girin (örn. 192.168.1.1 · 4 octet · octet başında 0 yok)";
  }
  if (octets[0] === 0) return "Gateway 0.x.x.x olamaz";
  if (octets.every((n) => n === 0)) return "0.0.0.0 gateway olamaz";
  if (octets.every((n) => n === 255)) return "255.255.255.255 gateway olamaz";
  if (octets[0] === 127) return "Loopback gateway olamaz";
  if (octets[0]! >= 224) return "Multicast gateway olamaz";
  return null;
}

export function isValidHostIpv4(value: string): boolean {
  return validateHostIpv4(value) === null;
}

export function isValidGatewayIpv4(value: string): boolean {
  return validateGatewayIpv4(value) === null;
}
