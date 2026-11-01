import React, { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import { useT } from '../../i18n/LocaleProvider'
import { EmptyState } from '../aiops/ui'
import { Panel } from '../insights/insightsKit'
import { VendorLogo } from './hwUi'

async function call(path: string, method: 'GET' | 'POST' | 'DELETE', body?: unknown) {
  const r = await fetch(`${API_BASE_URL}/hw${path}`, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : `HTTP ${r.status}`)
  return j
}

export type FwComp = {
  key: string; name: string; location?: string | null; version: string; reference_version: string
  state: string; accepted?: boolean; accepted_by?: string | null; note?: string | null
}
export type FwStatus = {
  server_id: number; status: string; compared: number; outdated: number; accepted: number; unknown: number; newer?: number
  reference?: { id: number; server_id: number; name: string; scope: string; enclosure_name?: string | null } | null
  components: FwComp[]
}

const FW_QUERY_KEYS = ['hw-fw-compare', 'hw-server', 'hw-findings']

const TONE: Record<string, string> = {
  ok: 'text-emerald-300 border-emerald-500/30', outdated: 'text-red-300 border-red-500/40', accepted: 'text-sky-300 border-sky-500/30',
  unknown: 'text-slate-400 border-white/10', reference: 'text-violet-300 border-violet-500/30', newer: 'text-slate-300 border-white/10',
  no_reference: 'text-slate-500 border-white/10', no_data: 'text-slate-500 border-white/10', reference_no_data: 'text-amber-300 border-amber-500/30',
}

export const FwStateBadge: React.FC<{ state: string }> = ({ state }) => {
  const t = useT()
  return <span data-testid="hw-fw-state" className={`text-[10px] px-1.5 py-0.5 rounded-sm border ${TONE[state] || TONE.unknown}`}>{t(`hw_fwc_state_${state}` as any)}</span>
}

function useFwActions() {
  const qc = useQueryClient()
  const [err, setErr] = useState<string | null>(null)
  const done = () => { setErr(null); FW_QUERY_KEYS.forEach(k => qc.invalidateQueries({ queryKey: [k] })) }
  const opts = { onSuccess: done, onError: (e: any) => setErr(e.message) }
  return {
    err,
    setRef: useMutation({ mutationFn: (v: { server_id: number; scope: 'model' | 'chassis' }) => call('/firmware/references', 'POST', v), ...opts }),
    delRef: useMutation({ mutationFn: (id: number) => call(`/firmware/references/${id}`, 'DELETE'), ...opts }),
    accept: useMutation({ mutationFn: (v: { server_id: number; component_keys?: string[]; note?: string }) => call('/firmware/accept', 'POST', v), ...opts }),
    unaccept: useMutation({ mutationFn: (v: { server_id: number; component_key?: string }) => call(`/firmware/accept/${v.server_id}${v.component_key ? `?component_key=${encodeURIComponent(v.component_key)}` : ''}`, 'DELETE'), ...opts }),
  }
}

const btn = 'text-[11px] px-2 py-0.5 rounded-sm border border-white/[0.1] text-slate-300 hover:text-white disabled:opacity-50'

/** Bir sunucunun bileşen karşılaştırması + «Kabul et» + «Referans yap». Hem Firmware sekmesinde hem satır ayrıntısında kullanılır. */
export const FwComponents: React.FC<{ serverId: number; status: FwStatus; showAll?: boolean }> = ({ serverId, status, showAll }) => {
  const t = useT()
  const a = useFwActions()
  const [note, setNote] = useState('')
  const comps = (showAll ? status.components : status.components.filter(c => c.state !== 'ok'))
  if (!comps.length) return null
  const acceptable = status.components.some(c => c.state === 'outdated')
  return (
    <div className="space-y-1" data-testid="hw-fwc-comps">
      <table className="w-full text-xs text-slate-300">
        <thead><tr className="text-left text-[10px] uppercase tracking-wide text-slate-500">
          <th className="py-1 pr-3 font-medium">{t('hw_fw_col_name')}</th><th className="py-1 pr-3 font-medium">{t('hw_fw_col_version')}</th>
          <th className="py-1 pr-3 font-medium">{t('hw_fwc_col_ref_version')}</th><th className="py-1 pr-3 font-medium">{t('hw_fwc_col_state')}</th><th />
        </tr></thead>
        <tbody>
          {comps.map(c => (
            <tr key={c.key} className="border-t border-white/[0.04]" data-testid="hw-fwc-comp">
              <td className="py-1 pr-3 break-all">{c.name}{c.location ? <span className="text-slate-500"> · {c.location}</span> : null}</td>
              <td className="py-1 pr-3 font-mono">{c.version}</td>
              <td className="py-1 pr-3 font-mono text-slate-400">{c.reference_version}</td>
              <td className="py-1 pr-3"><FwStateBadge state={c.state} />{c.accepted && c.accepted_by ? <span className="ml-1 text-[10px] text-slate-500">{t('hw_fwc_accepted_by', { u: c.accepted_by })}{c.note ? ` — ${c.note}` : ''}</span> : null}</td>
              <td className="py-1 text-right">
                {c.state === 'outdated' && <button type="button" className={btn} disabled={a.accept.isPending} data-testid="hw-fwc-accept"
                  onClick={() => a.accept.mutate({ server_id: serverId, component_keys: [c.key], note: note || undefined })}>{t('hw_fwc_accept')}</button>}
                {c.state === 'accepted' && <button type="button" className={btn} disabled={a.unaccept.isPending}
                  onClick={() => a.unaccept.mutate({ server_id: serverId, component_key: c.key })}>{t('hw_fwc_unaccept')}</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {acceptable && (
        <div className="flex items-center gap-2 pt-1">
          <input value={note} onChange={e => setNote(e.target.value)} maxLength={500} placeholder={t('hw_fwc_accept_note')}
            className="text-xs bg-slate-950/60 border border-white/[0.1] rounded-sm px-2 py-0.5 text-slate-200 w-64" />
          <button type="button" className={btn} disabled={a.accept.isPending} data-testid="hw-fwc-accept-all"
            onClick={() => a.accept.mutate({ server_id: serverId, note: note || undefined })}>{t('hw_fwc_accept_all')}</button>
        </div>
      )}
      {a.err && <div className="text-xs text-red-300" role="alert">{a.err}</div>}
    </div>
  )
}

/** Sunucu satırı ayrıntısında: referans durumu + «Referans yap». */
export const FwStatusPanel: React.FC<{ serverId: number; status?: FwStatus | null; hasData: boolean }> = ({ serverId, status, hasData }) => {
  const t = useT()
  const a = useFwActions()
  if (!status) return null
  const ref = status.reference
  return (
    <div className="rounded-sm border border-white/[0.08] px-3 py-2 space-y-2" data-testid="hw-fwc-panel">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-300">
        <span className="font-medium text-slate-200">{t('hw_fwc_title')}</span>
        <FwStateBadge state={status.status} />
        {ref ? <span className="text-slate-400">{t('hw_fwc_ref_line', { name: ref.name, scope: ref.scope === 'chassis' ? t('hw_fwc_ref_chassis') : t('hw_fwc_ref_model') })}</span>
          : <span className="text-slate-500">{t('hw_fwc_no_ref')}</span>}
        {status.compared > 0 && <span className="text-slate-500">{t('hw_fwc_compared', { n: status.compared, o: status.outdated })}</span>}
        {hasData && (
          <span className="ml-auto flex gap-1">
            <button type="button" className={btn} disabled={a.setRef.isPending} data-testid="hw-fwc-set-model" onClick={() => a.setRef.mutate({ server_id: serverId, scope: 'model' })}>{t('hw_fwc_set_model')}</button>
            <button type="button" className={btn} disabled={a.setRef.isPending} data-testid="hw-fwc-set-chassis" onClick={() => a.setRef.mutate({ server_id: serverId, scope: 'chassis' })}>{t('hw_fwc_set_chassis')}</button>
          </span>
        )}
      </div>
      <FwComponents serverId={serverId} status={status} showAll />
      {a.err && <div className="text-xs text-red-300" role="alert">{a.err}</div>}
    </div>
  )
}

const GroupCard: React.FC<{ g: any; onlyOutdated: boolean }> = ({ g, onlyOutdated }) => {
  const t = useT()
  const a = useFwActions()
  const [open, setOpen] = useState(g.outdated > 0)
  const servers = (g.servers as any[]).filter(s => !onlyOutdated || s.status === 'outdated')
  if (onlyOutdated && !servers.length) return null
  return (
    <Panel>
      <div className="px-4 py-3 space-y-2" data-testid="hw-fwc-group">
        <button type="button" className="flex items-center gap-2 text-left w-full" onClick={() => setOpen(!open)}>
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <VendorLogo vendor={g.vendor} />
          <span className="text-sm text-white">{g.model || t('hw_not_measured')}</span>
          <span className="text-xs text-slate-400">{t('hw_fwc_summary', { n: g.total, o: g.outdated, a: g.accepted, u: g.unknown })}</span>
          <span className="text-xs text-slate-500">{t('hw_fwc_coverage', { w: g.with_firmware, n: g.total })}</span>
        </button>
        <div className="text-xs text-slate-300 space-y-0.5">
          {g.reference
            ? <div className="flex items-center gap-2">{t('hw_fwc_ref_model')}: <span className="text-white">{g.reference.server_name}</span>
                <button type="button" className={btn} onClick={() => a.delRef.mutate(g.reference.id)}>{t('hw_fwc_remove_ref')}</button></div>
            : <div className="text-slate-500">{t('hw_fwc_no_model_ref')}</div>}
          {(g.chassis_refs as any[]).map(r => (
            <div key={r.id} className="flex items-center gap-2">{t('hw_fwc_ref_chassis')} ({r.enclosure_name || '—'}): <span className="text-white">{r.server_name}</span>
              <button type="button" className={btn} onClick={() => a.delRef.mutate(r.id)}>{t('hw_fwc_remove_ref')}</button></div>
          ))}
        </div>
        {a.err && <div className="text-xs text-red-300" role="alert">{a.err}</div>}
        {open && (
          <div className="divide-y divide-white/[0.05]">
            {servers.map(s => (
              <div key={s.id} className="py-2 space-y-1" data-testid="hw-fwc-server">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="text-sm text-slate-100">{s.name}</span>
                  {s.enclosure_name && <span className="text-slate-500">{s.enclosure_name}{s.bay ? ` / ${s.bay}` : ''}</span>}
                  <FwStateBadge state={s.status} />
                  {s.firmware_collected_at && <span className="text-[10px] text-slate-500">{t('hw_fw_read_at', { t: new Date(s.firmware_collected_at).toLocaleString() })}</span>}
                  {(s.firmware_rows > 0 || s.bmc_version || s.bios_version) && (
                    <span className="ml-auto flex gap-1">
                      <button type="button" className={btn} data-testid="hw-fwc-set-model" onClick={() => a.setRef.mutate({ server_id: s.id, scope: 'model' })}>{t('hw_fwc_set_model')}</button>
                      <button type="button" className={btn} data-testid="hw-fwc-set-chassis" onClick={() => a.setRef.mutate({ server_id: s.id, scope: 'chassis' })}>{t('hw_fwc_set_chassis')}</button>
                    </span>
                  )}
                </div>
                {s.components?.length > 0 && <FwComponents serverId={s.id} status={s as FwStatus} />}
              </div>
            ))}
          </div>
        )}
      </div>
    </Panel>
  )
}

export const HwFirmwareTab: React.FC = () => {
  const t = useT()
  const q = useQuery<any>({ queryKey: ['hw-fw-compare'], queryFn: () => call('/firmware/compare', 'GET') })
  const [only, setOnly] = useState(false)
  const groups: any[] = q.data?.groups || []
  return (
    <div className="space-y-3" data-testid="hw-fwc-tab">
      <div className="text-xs text-slate-400">{t('hw_fwc_hint')}</div>
      <label className="text-xs text-slate-300 flex items-center gap-2"><input type="checkbox" checked={only} onChange={e => setOnly(e.target.checked)} /> {t('hw_fwc_only_outdated')}</label>
      {groups.map((g, i) => <GroupCard key={`${g.vendor}-${g.model}-${i}`} g={g} onlyOutdated={only} />)}
      {!q.isLoading && !groups.length && <Panel><EmptyState text={t('hw_fwc_none')} /></Panel>}
    </div>
  )
}
