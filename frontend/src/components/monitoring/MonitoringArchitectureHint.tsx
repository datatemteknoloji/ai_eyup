/**
 * Monitoring mimari — plan flowchart (Shared MonitoringShell + Linux Canlı Metrikler).
 * Info tıklanınca tam ekran; zoom ile büyütülür.
 */
import React, { useEffect, useId, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Info, Maximize2, Minus, Plus, X } from 'lucide-react'
import { useT } from '../../i18n/LocaleProvider'
import { ChatMermaid } from '../ChatMermaid'
import { mermaidToArchitectureDiagram } from '../../utils/mermaidToDiagram'

/**
 * Yukarı → aşağı omurga: Settings → Resolver → UI → SoT.
 * Chat, Resolver’dan ayrılan alt kol. wrappingWidth düşük olunca yazı kesiliyordu.
 */
const PLAN_MERMAID = `%%{init: {"flowchart": {"htmlLabels": true, "curve": "basis", "padding": 18, "nodeSpacing": 32, "rankSpacing": 56, "wrappingWidth": 260, "useMaxWidth": false}, "themeVariables": {"fontSize": "14px"}}}%%
flowchart TB
  subgraph settings ["1 · Settings"]
    direction LR
    V["Virt Prom URL"]
    L["Linux Prom URL"]
    O["OpenShift Prom URL<br/>+ token"]
  end

  subgraph resolver ["2 · MonitoringSourceResolver"]
    R["module + mode → URL / API SoT"]
  end

  subgraph ui ["3 · Monitoring UI"]
    direction TB
    subgraph pages ["Sayfalar"]
      direction LR
      Hub["/monitoring hub"]
      VirtPage["/virt/monitoring"]
      OcpPage["/openshift/monitoring"]
      LinuxPage["/metrics<br/>Canlı Metrikler"]
    end
    Shell["Shared MonitoringShell"]
    Hub --> Shell
    VirtPage --> Shell
    OcpPage --> Shell
    Hub -.-> LinuxPage
  end

  subgraph sot ["4 · Veri kaynağı SoT"]
    direction LR
    ApiOcp["metrics.k8s.io<br/>Timescale"]
    ApiVirt["vCenter<br/>Timescale"]
    PromOcp["OCP Prom<br/>DCGM + kubevirt"]
    PromVirt["VMware exporter<br/>Prom"]
    PromLinux["Linux<br/>node-exporter"]
  end

  subgraph chat ["5 · Chat"]
    direction TB
    Planner["source planner + catalog"]
    Tools["ocp_prom / virt_prom / API tools"]
    Planner --> Tools
  end

  settings --> resolver
  resolver --> ui
  ui --> sot
  resolver --> chat
  Shell -->|api| ApiOcp
  Shell -->|api| ApiVirt
  Shell -->|prometheus| PromOcp
  Shell -->|prometheus| PromVirt
  LinuxPage -->|prometheus| PromLinux
`

export const MonitoringArchitectureHint: React.FC<{ className?: string }> = ({ className = '' }) => {
  const t = useT()
  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [zoom, setZoom] = useState(1.25)
  const wrapRef = useRef<HTMLDivElement>(null)
  const descId = useId()
  const source = PLAN_MERMAID
  const fallback = useMemo(() => mermaidToArchitectureDiagram(source), [source])

  useEffect(() => {
    if (!open && !expanded) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setExpanded(false)
        setOpen(false)
      }
    }
    const onDown = (e: MouseEvent) => {
      if (expanded) return
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onDown)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onDown)
    }
  }, [open, expanded])

  const bumpZoom = (delta: number) => {
    setZoom((z) => Math.min(2.6, Math.max(0.7, Math.round((z + delta) * 20) / 20)))
  }

  const renderDiagram = () => (
    <ChatMermaid
      source={source}
      fallback={fallback}
      delayMs={0}
      className="!my-0 min-w-[980px] mon-arch-mermaid"
    />
  )

  const flowNote = (
    <div className="mt-3 space-y-1.5 text-[11px] text-[var(--text-muted)] leading-relaxed border-t border-white/[0.06] pt-3">
      <p className="font-medium text-[var(--text-secondary)]">{t('mon_arch_flow_title')}</p>
      <p>{t('mon_arch_flow')}</p>
      <p className="text-[10px] text-slate-500">{t('mon_arch_linux_note')}</p>
    </div>
  )

  return (
    <div
      ref={wrapRef}
      className={`relative inline-flex ${className}`}
      onMouseEnter={() => { if (!expanded) setOpen(true) }}
      onMouseLeave={() => { if (!expanded) setOpen(false) }}
    >
      <button
        type="button"
        className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent)] hover:bg-[var(--accent-subtle)] transition-colors"
        aria-label={t('mon_arch_aria')}
        aria-expanded={open || expanded}
        aria-describedby={open ? descId : undefined}
        onClick={() => {
          setZoom(1.35)
          setExpanded(true)
          setOpen(false)
        }}
      >
        <Info size={16} />
      </button>
      {open && !expanded && (
        <div
          id={descId}
          role="tooltip"
          className="absolute left-0 top-full z-50 mt-2 w-[min(96vw,1200px)] max-h-[min(78vh,860px)] overflow-auto rounded-xl border border-white/[0.1] bg-[var(--bg-surface)] shadow-xl p-4"
        >
          <div className="flex items-center justify-between mb-3 gap-2">
            <div className="text-sm font-semibold text-[var(--text-primary)]">{t('mon_arch_title')}</div>
            <button
              type="button"
              className="inline-flex items-center gap-1 text-xs text-blue-300 hover:text-white px-2 py-1 rounded-md hover:bg-white/[0.06]"
              onClick={(e) => {
                e.stopPropagation()
                setZoom(1.35)
                setExpanded(true)
                setOpen(false)
              }}
              title={t('mon_arch_expand')}
            >
              <Maximize2 size={14} /> {t('mon_arch_expand')}
            </button>
          </div>
          <div className="overflow-auto">{renderDiagram()}</div>
          {flowNote}
        </div>
      )}
      {expanded && createPortal(
        <div
          className="fixed inset-0 z-[80] bg-black/80 flex items-stretch justify-center p-3 md:p-6"
          onClick={() => setExpanded(false)}
          role="dialog"
          aria-modal="true"
          aria-label={t('mon_arch_title')}
        >
          <div
            className="bg-[var(--bg-surface)] border border-white/[0.12] rounded-2xl w-full max-w-[96vw] max-h-[96vh] flex flex-col shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3 p-4 md:p-5 border-b border-white/[0.08] shrink-0">
              <h2 className="text-lg font-bold text-[var(--text-primary)]">{t('mon_arch_title')}</h2>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-white/[0.06]"
                  onClick={() => bumpZoom(-0.15)}
                  aria-label={t('mon_arch_zoom_out')}
                  title={t('mon_arch_zoom_out')}
                >
                  <Minus size={16} />
                </button>
                <span className="text-xs text-slate-400 w-10 text-center tabular-nums">{Math.round(zoom * 100)}%</span>
                <button
                  type="button"
                  className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-white/[0.06]"
                  onClick={() => bumpZoom(0.15)}
                  aria-label={t('mon_arch_zoom_in')}
                  title={t('mon_arch_zoom_in')}
                >
                  <Plus size={16} />
                </button>
                <button
                  type="button"
                  className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-white/[0.06]"
                  onClick={() => setExpanded(false)}
                  aria-label={t('close')}
                >
                  <X size={18} />
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-auto p-4 md:p-6">
              <div
                style={{ transform: `scale(${zoom})`, transformOrigin: 'top left', width: `${100 / zoom}%` }}
              >
                {renderDiagram()}
              </div>
              <div className="mt-4 max-w-4xl">{flowNote}</div>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  )
}

export default MonitoringArchitectureHint
