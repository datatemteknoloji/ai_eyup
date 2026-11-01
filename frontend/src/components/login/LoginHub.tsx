import React from 'react'
import { useT } from '../../i18n/LocaleProvider'

/**
 * Giriş ekranı sol panel diyagramı: ürün adından yönetilen platformlara akış şeması.
 *   ainew ─┬─ Linux ──┐                    ┌─ Sanallaştırma ─ [ vSphere · OpenShift · OLVM ]
 *          ├─ Windows ┴─ [ HP   Dell ]     │                         ▲ tek bağlantı çubuğu
 *          ├─ Exadata        └┬──┘         │
 *          └─ ...        [Fiziksel  Sanal] ┘
 * Linux ve Windows aynı ortak yapıyı paylaşır: HP ve Dell bir üst düzeydedir, «Fiziksel» ikisine de bağlanır;
 * «Sanal» tek bir bağlantı çubuğuyla sanallaştırma kümesinin TÜMÜNE bağlanır.
 * Tamamen dekoratiftir — sayı/ölçüm göstermez (giriş öncesi envanter bilgisi sızdırılmaz).
 * Renkler `.lg-*` CSS değişkenlerinden gelir (koyu/açık tema). Animasyonlar CSS'tedir ve
 * `prefers-reduced-motion` ile kapanır.
 */
const CX = 300
const CORE_Y = 26
const BUS_Y = 70
const TOP_Y = 96            // ikinci düzey (platform) hapları
const GROUP_Y = 124         // çerçeveler

type Pill = { id: string; label: string; x: number; y: number; w: number; h: number; small?: boolean; accent?: boolean }

const shorten = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)

const LoginHub: React.FC<{ appName: string; logoUrl: string | null; ariaLabel: string }> = ({
  appName,
  logoUrl,
  ariaLabel,
}) => {
  const t = useT()
  const coreText = shorten(appName, logoUrl ? 9 : 13)

  const top: Pill[] = [
    { id: 'linux', label: 'Linux', x: 80, y: TOP_Y, w: 104, h: 32 },
    { id: 'windows', label: 'Windows', x: 200, y: TOP_Y, w: 104, h: 32 },
    { id: 'exadata', label: 'Exadata', x: 335, y: TOP_Y, w: 104, h: 32 },
    { id: 'virt', label: t('login_hub_virt'), x: 490, y: TOP_Y, w: 132, h: 32 },
  ]
  // Linux ve Windows'un ORTAK yapısı
  const shared: Pill[] = [
    { id: 'hp', label: 'HP', x: 80, y: 150, w: 104, h: 28, small: true },
    { id: 'dell', label: 'Dell', x: 200, y: 150, w: 104, h: 28, small: true },
    { id: 'physical', label: t('login_hub_physical'), x: 80, y: 202, w: 104, h: 28, small: true },
    { id: 'virtual', label: t('login_hub_virtual'), x: 200, y: 202, w: 104, h: 28, small: true, accent: true },
  ]
  // Sanallaştırmanın alt dalları (hepsi aynı çubuğa bağlı)
  const virt: Pill[] = [
    { id: 'vsphere', label: 'vSphere', x: 492, y: 166, w: 116, h: 28, small: true },
    { id: 'openshift', label: 'OpenShift', x: 492, y: 202, w: 116, h: 28, small: true },
    { id: 'olvm', label: 'OLVM', x: 492, y: 238, w: 116, h: 28, small: true },
  ]
  const BAR_X = 418
  const barTop = virt[0].y
  const barBottom = virt[virt.length - 1].y
  const byId = (id: string) => shared.find(p => p.id === id)!
  const hp = byId('hp')
  const dell = byId('dell')
  const phys = byId('physical')
  const sanal = byId('virtual')
  const flowStart = sanal.x + sanal.w / 2
  const forkY = (hp.y + hp.h / 2 + phys.y - phys.h / 2) / 2          // HP/Dell ile Fiziksel arası dal noktası

  const lines: { id: string; d: string }[] = [
    { id: 'core-bus', d: `M${CX},${CORE_Y + 22} V${BUS_Y}` },
    { id: 'bus', d: `M${top[0].x},${BUS_Y} H${top[3].x}` },
    ...top.map(p => ({ id: `drop-${p.id}`, d: `M${p.x},${BUS_Y} V${p.y - p.h / 2}` })),
    // Linux ve Windows aynı ortak çerçeveye iner
    { id: 'linux-group', d: `M${top[0].x},${top[0].y + 16} V${GROUP_Y}` },
    { id: 'windows-group', d: `M${top[1].x},${top[1].y + 16} V${GROUP_Y}` },
    { id: 'virt-group', d: `M${top[3].x},${top[3].y + 16} V${GROUP_Y}` },
    // «Fiziksel» → HP ve Dell (bir üst düzey)
    { id: 'physical-hp', d: `M${phys.x},${phys.y - phys.h / 2} V${hp.y + hp.h / 2}` },
    { id: 'physical-dell', d: `M${phys.x},${forkY} H${dell.x} V${dell.y + dell.h / 2}` },
    // alt dallar: tek çubuk + her haba kısa dal
    ...virt.map(p => ({ id: `tick-${p.id}`, d: `M${BAR_X},${p.y} H${p.x - p.w / 2}` })),
  ]

  const renderPill = (p: Pill, i: number) => (
    <g key={p.id} data-node={p.id}>
      <rect className={`lg-hub-pill${p.accent ? ' lg-hub-pill-accent' : ''}`} x={p.x - p.w / 2} y={p.y - p.h / 2} width={p.w} height={p.h} rx={p.h / 2} />
      <circle className="lg-hub-halo" cx={p.x - p.w / 2 + (p.small ? 15 : 18)} cy={p.y} r="3.2" style={{ animationDelay: `${-i * 0.5}s` }} />
      <circle className="lg-hub-dot" cx={p.x - p.w / 2 + (p.small ? 15 : 18)} cy={p.y} r="3.2" />
      <text className={p.small ? 'lg-hub-label lg-hub-label-sm' : 'lg-hub-label'} x={p.x - p.w / 2 + (p.small ? 25 : 30)} y={p.y + (p.small ? 4 : 4.4)}>
        {p.label}
      </text>
    </g>
  )

  return (
    <svg
      className="lg-hub"
      viewBox="0 0 600 272"
      role="img"
      aria-label={ariaLabel}
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id="lg-core-grad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#4a86ff" />
          <stop offset="1" stopColor="#2459e0" />
        </linearGradient>
      </defs>

      {/* ortak yapı + sanallaştırma çerçeveleri */}
      <rect className="lg-hub-frame" data-node="shared-frame" x="20" y={GROUP_Y} width="260" height="106" rx="14" />
      <rect className="lg-hub-frame" data-node="virt-frame" x="392" y={GROUP_Y} width="196" height="142" rx="14" />

      {lines.map((l, i) => (
        <path key={l.id} data-line={l.id} className="lg-hub-line" d={l.d} fill="none" style={{ animationDelay: `${-i * 0.3}s` }} />
      ))}

      {/* «Sanal» → sanallaştırma kümesinin tamamı: tek bağlantı çubuğu */}
      <path data-line="vm-flow" className="lg-hub-line lg-hub-flow" fill="none"
        d={`M${flowStart},${sanal.y} H${BAR_X}`} />
      <line data-line="vm-bar" className="lg-hub-bar" x1={BAR_X} y1={barTop} x2={BAR_X} y2={barBottom} />

      <rect className="lg-hub-core-glow" x={CX - 60} y={CORE_Y - 18} width="120" height="36" rx="18" />
      <rect className="lg-hub-core" x={CX - 70} y={CORE_Y - 22} width="140" height="44" rx="13" />
      {logoUrl && (
        <image href={logoUrl} x={CX - 58} y={CORE_Y - 12} width="24" height="24" preserveAspectRatio="xMidYMid meet" />
      )}
      <text
        className="lg-hub-core-label"
        x={logoUrl ? CX - 28 : CX}
        y={CORE_Y + 5}
        textAnchor={logoUrl ? 'start' : 'middle'}
      >
        {coreText}
      </text>

      {[...top, ...shared, ...virt].map(renderPill)}
    </svg>
  )
}

export default LoginHub
