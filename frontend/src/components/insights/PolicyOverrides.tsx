import { useEffect, useMemo, useState } from 'react'
import { useT } from '../../i18n/LocaleProvider'
import { GhostButton, NEON } from '../aiops/ui'
import { InfoDot } from './InfoDot'
import { apiGet, apiSend, useRole } from './insightsKit'

/**
 * E7 — Cluster / instance bazında kapasite eşiği override'ı. Yeni tablo/uç yok: mevcut
 * `GET /capacity/policy`, `GET|PUT|DELETE /capacity/policy/override` (admin yazar, audit'li) kullanılır.
 * Öncelik: kod varsayılanı < global < instance < cluster. Her anahtar için değerin hangi seviyeden geldiği
 * gösterilir; yalnız üst seviyeden FARKLI girilen değerler override olarak kaydedilir.
 */
type Src = 'cluster' | 'instance' | 'global' | 'default'

export default function PolicyOverrides({ clusters }: { clusters: any[] }) {
  const t = useT()
  const { isAdmin } = useRole()
  const instances = useMemo(() => {
    const m = new Map<number, string>()
    for (const c of clusters) if (!m.has(c.hypervisor_id)) m.set(c.hypervisor_id, c.hypervisor)
    return [...m.entries()].map(([id, name]) => ({ id, name }))
  }, [clusters])
  const [hv, setHv] = useState<number | ''>('')
  const [scope, setScope] = useState('')                // '' = instance varsayılanı, aksi halde cluster adı
  const [spec, setSpec] = useState<Record<string, any>>({})
  const [glob, setGlob] = useState<Record<string, number>>({})
  const [ov, setOv] = useState<Record<string, Record<string, number>>>({})
  const [vals, setVals] = useState<Record<string, string>>({})
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => { if (hv === '' && instances.length) setHv(instances[0].id) }, [instances, hv])
  const clusterNames = useMemo(() => clusters.filter(c => c.hypervisor_id === hv).map(c => c.cluster), [clusters, hv])

  const load = async (id: number) => {
    const [p, o] = await Promise.all([
      apiGet<any>('virt-insights', '/capacity/policy'),
      apiGet<any>('virt-insights', `/capacity/policy/overrides?hypervisor_id=${id}`),
    ])
    setSpec(p.spec || {}); setGlob(p.values || {}); setOv(o.overrides || {})
  }
  useEffect(() => {
    if (hv === '') return
    load(hv).catch(e => setMsg({ ok: false, text: e.message }))
  }, [hv])

  /** Üst seviyeden miras alınan değer (override yokmuş gibi) ve kaynağı. */
  const parent = (k: string): { v: number; src: Src } => {
    if (scope && ov['']?.[k] !== undefined) return { v: ov[''][k], src: 'instance' }
    const g = glob[k]
    return { v: g, src: g !== spec[k]?.default ? 'global' : 'default' }
  }
  const effective = (k: string): { v: number; src: Src } => {
    const own = ov[scope]?.[k]
    return own !== undefined ? { v: own, src: scope ? 'cluster' : 'instance' } : parent(k)
  }
  useEffect(() => {
    setVals(Object.fromEntries(Object.keys(spec).map(k => [k, String(effective(k).v ?? '')])))
    setMsg(null)
  }, [spec, glob, ov, scope])                           // eslint-disable-line react-hooks/exhaustive-deps

  const srcLabel = (s: Src) => t(`vi_ov_src_${s}` as any)
  const save = async () => {
    if (hv === '') return
    setMsg(null)
    const changed: Record<string, number> = {}
    for (const k of Object.keys(spec)) {
      const n = Number(vals[k])
      if (!Number.isFinite(n)) continue
      if (n !== effective(k).v) changed[k] = n
    }
    if (!Object.keys(changed).length) { setMsg({ ok: true, text: t('vi_ov_nochange') }); return }
    try {
      await apiSend('virt-insights', '/capacity/policy/override', 'PUT', { hypervisor_id: hv, cluster: scope || null, values: changed })
      await load(hv)
      setMsg({ ok: true, text: t('vi_ov_saved') })
    } catch (e: any) { setMsg({ ok: false, text: e.message }) }
  }
  const remove = async (k: string) => {
    if (hv === '') return
    setMsg(null)
    try {
      await apiSend('virt-insights', `/capacity/policy/override?hypervisor_id=${hv}&key=${encodeURIComponent(k)}${scope ? `&cluster=${encodeURIComponent(scope)}` : ''}`, 'DELETE')
      await load(hv)
      setMsg({ ok: true, text: t('vi_ov_removed') })
    } catch (e: any) { setMsg({ ok: false, text: e.message }) }
  }

  if (!instances.length) return null
  return (
    <div className="p-4 border-t border-white/[0.06] space-y-3" data-testid="policy-overrides">
      <div className="text-sm text-slate-200 font-medium flex items-center">
        {t('vi_ov_title')}
        <InfoDot label={t('vi_ov_title')} text={t('vi_ov_help')} />
      </div>
      <div className="text-xs text-slate-400">{t('vi_ov_intro')}</div>
      <div className="flex flex-wrap gap-3 text-xs text-slate-400">
        <label className="flex flex-col gap-1">{t('vi_ov_instance')}
          <select data-testid="ov-instance" value={hv} onChange={e => { setHv(Number(e.target.value)); setScope('') }}
            className="rounded bg-black/30 border border-white/[0.08] px-2 py-1.5 text-sm text-white">
            {instances.map(i => <option key={i.id} value={i.id}>{i.name}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1">{t('vi_ov_scope')}
          <select data-testid="ov-scope" value={scope} onChange={e => setScope(e.target.value)}
            className="rounded bg-black/30 border border-white/[0.08] px-2 py-1.5 text-sm text-white">
            <option value="">{t('vi_ov_scope_instance')}</option>
            {clusterNames.map((n: string) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {Object.entries(spec).map(([k, s]: any) => {
          const e = effective(k)
          const own = ov[scope]?.[k] !== undefined
          return (
            <div key={k} className="flex flex-col gap-1 text-xs text-slate-400" data-testid={`ov-${k}`}>
              <span className="text-slate-200 flex items-center">{s.label}<InfoDot label={s.label} text={t(('vi_policy_help_' + k) as any)} /></span>
              <div className="flex items-center gap-2">
                <input type="number" min={s.min} max={s.max} step="1" value={vals[k] ?? ''} disabled={!isAdmin}
                  onChange={ev => setVals(v => ({ ...v, [k]: ev.target.value }))}
                  className="w-28 rounded bg-black/30 border border-white/[0.08] px-2 py-1.5 text-sm text-white font-mono disabled:opacity-60" />
                <span data-testid={`ov-src-${k}`} className={own ? 'text-amber-300' : 'text-slate-500'}>{srcLabel(e.src)}</span>
                {own && isAdmin && (
                  <button type="button" data-testid={`ov-del-${k}`} onClick={() => remove(k)} className="text-blue-400 hover:underline">{t('vi_ov_remove')}</button>
                )}
              </div>
              <span className="text-slate-500">{t('vi_policy_range', { a: s.min, b: s.max, d: s.default })}</span>
            </div>
          )
        })}
      </div>
      {isAdmin
        ? <div className="flex gap-2"><GhostButton accent={NEON.blue} onClick={save}>{t('vi_ov_save')}</GhostButton></div>
        : <div className="text-[11px] text-slate-500">{t('vi_ov_admin_only')}</div>}
      {msg && <div className={`text-xs ${msg.ok ? 'text-emerald-300' : 'text-red-300'}`} data-testid="ov-msg">{msg.text}</div>}
    </div>
  )
}
