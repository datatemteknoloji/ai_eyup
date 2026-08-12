import { useEffect, useRef, useState } from 'react'
import {
  AlertTriangle, ArrowRightLeft, Check, CheckCircle2, ChevronDown, ChevronRight, Copy,
  FileText, HardDrive, KeyRound, Loader2, Network, Play, Plus, RefreshCw, Trash2, X,
  XCircle, Zap,
} from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import { useAuth } from '../../auth/AuthContext'

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) } })
  const body = await r.json().catch(() => ({}))
  if (!r.ok) {
    const detail = body?.detail
    const msg = typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ')
        : (r.statusText || 'Hata')
    throw new Error(msg)
  }
  return body as T
}

const input = 'w-full rounded-lg border border-white/[0.08] bg-cyber-deep px-3 py-2 text-sm text-slate-200 outline-none focus:border-cyan-500/50'
const button = 'rounded-lg border border-white/[0.08] px-2.5 py-1.5 text-xs text-slate-300 hover:bg-white/[0.05] disabled:cursor-not-allowed disabled:opacity-40 inline-flex items-center gap-1.5'

export default function OcpMtvPanel({ clusterId, overview }: { clusterId: number; overview: any }) {
  const { user } = useAuth()
  const canWrite = Boolean(user?.is_admin || user?.role === 'admin')
  const base = `${API_BASE_URL}/openshift/clusters/${clusterId}/mtv`
  const [providers, setProviders] = useState<any[]>([])
  const [plans, setPlans] = useState<any[]>([])
  const [hypervisors, setHypervisors] = useState<any[]>([])
  const [rbacYaml, setRbacYaml] = useState('')
  const [showRbac, setShowRbac] = useState(false)
  const [watch, setWatch] = useState<string | null>(null)
  const [status, setStatus] = useState<any>(null)
  const [wizard, setWizard] = useState(false)
  const [vddkFor, setVddkFor] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const load = async () => {
    setBusy(true)
    try {
      const [p, pl, hvRaw, rbac] = await Promise.all([
        api<any[]>(`${base}/providers`), api<any[]>(`${base}/plans`), api<any>(`${API_BASE_URL}/hypervisors/`),
        api<{ yaml: string }>(`${base}/rbac`),
      ])
      setProviders(Array.isArray(p) ? p : [])
      setPlans(Array.isArray(pl) ? pl : [])
      const hvList = Array.isArray(hvRaw) ? hvRaw : (hvRaw?.hypervisors || hvRaw?.items || [])
      setHypervisors(hvList.filter((h: any) => (h.type || h.hypervisor_type || '').toLowerCase() === 'vmware'))
      setRbacYaml(rbac.yaml || '')
    } catch (e: any) { setMsg(e.message || 'MTV bilgileri alınamadı') } finally { setBusy(false) }
  }
  useEffect(() => { load() }, [clusterId])
  useEffect(() => {
    if (!watch) { setStatus(null); return }
    let active = true
    const poll = async () => {
      try { if (active) setStatus(await api<any>(`${base}/plans/${encodeURIComponent(watch)}/status`)) } catch {}
    }
    poll()
    const timer = window.setInterval(() => { poll(); load() }, 5000)
    return () => { active = false; window.clearInterval(timer) }
  }, [watch, clusterId])

  const act = async (action: () => Promise<unknown>, success: string) => {
    try { await action(); setMsg(success); await load() } catch (e: any) { setMsg(e.message || 'İşlem başarısız') }
  }
  const addProvider = (id: string) => {
    if (!id || !canWrite) return
    const h = hypervisors.find((x) => String(x.id) === id)
    if (!window.confirm(`${h?.name || 'vCenter'} kaynak sağlayıcı olarak eklensin mi? Kimlik bilgileri kümede Secret olarak saklanır.`)) return
    act(() => api(`${base}/providers`, { method: 'POST', body: JSON.stringify({ hypervisor_id: Number(id) }) }), 'Kaynak sağlayıcı oluşturuldu; hazır olması yaklaşık bir dakika sürebilir.')
  }
  const copyRbac = async () => {
    try { await navigator.clipboard.writeText(`oc apply -f - <<'EOF'\n${rbacYaml}EOF`); setMsg('RBAC komutu kopyalandı.') } catch { setMsg('Panoya kopyalanamadı.') }
  }
  const readyProvider = providers.some((p) => p.type === 'vsphere' && p.ready)
  const missing = overview?.migration_missing || []

  return <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-5 space-y-5">
    <div className="flex items-center gap-2 flex-wrap">
      <ArrowRightLeft size={18} className="text-cyan-400" />
      <h2 className="text-sm font-medium text-white">VM Taşıma (MTV)</h2>
      <button type="button" onClick={() => setShowRbac(!showRbac)} className="ml-1 text-xs text-slate-500 hover:text-cyan-300 inline-flex items-center gap-1"><KeyRound size={13} /> Yetki ver</button>
      <button type="button" onClick={load} className={`${button} ml-auto`}><RefreshCw size={13} className={busy ? 'animate-spin' : ''} /> Yenile</button>
    </div>
    {msg && <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/[0.07] px-3 py-2 text-xs text-cyan-100 flex justify-between gap-3"><span>{msg}</span><button onClick={() => setMsg('')}><X size={14} /></button></div>}
    <div className="rounded-xl border border-sky-500/20 bg-sky-500/[0.07] px-4 py-3 text-xs text-sky-100 leading-relaxed">
      VMware sanal makinelerini Migration Toolkit for Virtualization (Forklift) ile OpenShift Virtualization'a taşıyın: vCenter kaynağını ekleyin, VM ve hedef eşlemelerini seçin, planı doğrulayın ve başlatın.
    </div>
    {!overview?.migration_ready && <div className="rounded-xl border border-amber-500/25 bg-amber-500/[0.08] px-4 py-3 text-xs text-amber-100 flex gap-2"><AlertTriangle size={15} className="mt-0.5 flex-none text-amber-400" /><span>MTV için gerekli operatörler eksik: <b>{missing.join(', ') || 'KubeVirt, CDI veya Forklift'}</b>. Plan oluşturmadan önce küme hazırlığını tamamlayın.</span></div>}
    {showRbac && <div className="rounded-xl border border-white/[0.06] bg-cyber-deep p-4 space-y-2"><div className="flex justify-between"><p className="text-xs text-slate-300">Yazma RBAC'ı kümede bir kez uygulayın.</p><button className="text-slate-400 hover:text-cyan-300" onClick={copyRbac}><Copy size={14} /></button></div><pre className="max-h-40 overflow-auto rounded-lg bg-black/30 p-3 text-[10px] text-cyan-100/80 whitespace-pre-wrap">{`oc apply -f - <<'EOF'\n${rbacYaml}EOF`}</pre></div>}
    <section className="space-y-2">
      <h3 className="text-xs uppercase tracking-wide text-slate-500">Kaynaklar (provider)</h3>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {providers.map((p) => <ProviderCard key={p.name} provider={p} canWrite={!!canWrite} onVddk={() => setVddkFor(p)} />)}
        {!providers.length && <p className="text-xs text-slate-500 col-span-full">Henüz kaynak sağlayıcı yok.</p>}
      </div>
      {canWrite && <select className={`${input} max-w-sm text-xs py-1.5`} value="" onChange={(e) => addProvider(e.target.value)}><option value="">+ vCenter'ı kaynak olarak ekle…</option>{hypervisors.map((h) => <option key={h.id} value={h.id}>{h.name} ({h.hostname || h.ip || h.host || '—'})</option>)}</select>}
    </section>
    <section className="space-y-2">
      <div className="flex items-center"><h3 className="text-xs uppercase tracking-wide text-slate-500">Taşıma planları</h3>{canWrite && readyProvider && <button onClick={() => setWizard(true)} className="ml-auto rounded-lg bg-cyan-600 px-2.5 py-1.5 text-xs text-white hover:bg-cyan-500 inline-flex items-center gap-1"><Plus size={13} /> Yeni Plan</button>}</div>
      {!plans.length ? <p className="py-3 text-xs text-slate-500">{readyProvider ? 'Henüz plan yok. Yeni plan oluşturarak başlayın.' : 'Önce hazır bir vSphere provider ekleyin.'}</p> : <div className="space-y-2">{plans.map((p) => <PlanRow key={p.name} plan={p} canWrite={!!canWrite} watching={watch === p.name} onWatch={() => setWatch(watch === p.name ? null : p.name)} onStart={() => { if (window.confirm(`"${p.name}" planı başlatılsın mı? Açık kaynak VM'ler soğuk taşımada kapatılabilir.`)) act(() => api(`${base}/plans/${encodeURIComponent(p.name)}/start`, { method: 'POST' }), 'Taşıma başlatıldı.'); setWatch(p.name) }} onCancel={() => { if (window.confirm(`"${p.name}" taşıması iptal edilsin mi? Plan korunur.`)) act(() => api(`${base}/plans/${encodeURIComponent(p.name)}/cancel`, { method: 'POST' }), 'Taşıma iptal edildi.') }} onDelete={() => { if (window.confirm(`"${p.name}" planı silinsin mi?`)) act(() => api(`${base}/plans/${encodeURIComponent(p.name)}`, { method: 'DELETE' }), 'Plan silindi.') }} />)}</div>}
    </section>
    {watch && <ProgressWatch clusterId={clusterId} base={base} plan={watch} status={status} />}
    {wizard && (
      <PlanWizard
        clusterId={clusterId}
        base={base}
        providers={providers.filter((p) => p.type === 'vsphere')}
        hypervisors={hypervisors}
        onClose={() => setWizard(false)}
        onCreated={() => {
          setWizard(false)
          load()
          setMsg('Plan oluşturuldu; MTV doğrulamasından sonra başlatabilirsiniz.')
        }}
      />
    )}
    {vddkFor && <VddkModal base={base} provider={vddkFor} onClose={() => setVddkFor(null)} onSaved={() => { setVddkFor(null); load(); setMsg('VDDK ayarı kaydedildi.') }} />}
  </div>
}

function ProviderCard({ provider: p, canWrite, onVddk }: any) {
  return <div className={`rounded-xl border p-3 ${p.error ? 'border-rose-500/30 bg-rose-500/[0.06]' : 'border-white/[0.06] bg-cyber-deep/40'} space-y-2`}>
    <div className="flex items-center gap-2">{p.ready ? <CheckCircle2 size={16} className="text-emerald-400" /> : p.error ? <XCircle size={16} className="text-rose-400" /> : <Loader2 size={16} className="text-slate-500 animate-spin" />}<span className="truncate text-sm text-slate-100">{p.name}</span><span className="ml-auto text-[10px] text-slate-500">{p.type}</span></div>
    {p.url && <p className="truncate font-mono text-[10px] text-slate-500">{p.url}</p>}{p.error && <p className="text-[11px] text-rose-200">{p.error}</p>}
    {p.type === 'vsphere' && <div className="border-t border-white/[0.06] pt-2 flex gap-2 items-start">{p.vddk ? <Zap size={14} className="text-emerald-400" /> : <AlertTriangle size={14} className="text-amber-400 mt-0.5" />}<div className="min-w-0 flex-1"><p className={p.vddk ? 'text-[11px] text-emerald-300' : 'text-[11px] text-amber-200'}>{p.vddk ? 'VDDK etkin' : 'VDDK yok — diskler daha yavaş kopyalanır'}</p>{p.vddk && <p className="truncate text-[10px] font-mono text-slate-500">{p.vddk}</p>}</div>{canWrite && <button onClick={onVddk} className="text-[11px] text-cyan-300 hover:text-cyan-200">{p.vddk ? 'Değiştir' : 'Ayarla'}</button>}</div>}
  </div>
}

function PlanRow({ plan: p, canWrite, watching, onWatch, onStart, onCancel, onDelete }: any) {
  const state = String(p.state || '').toLowerCase()
  const running = state.includes('çalış') || state.includes('running') || p.started
  const ready = state.includes('hazır') || state.includes('ready')
  return <div className={`rounded-xl border px-3 py-2.5 flex items-center gap-3 flex-wrap ${p.error ? 'border-rose-500/25 bg-rose-500/[0.05]' : 'border-white/[0.06] bg-cyber-deep/35'}`}><div className="min-w-0"><div className="flex gap-2 items-center"><span className="text-sm text-slate-100">{p.name}</span><span className={`rounded-full px-2 py-0.5 text-[10px] ${p.error ? 'bg-rose-500/15 text-rose-300' : running ? 'bg-amber-500/15 text-amber-300' : 'bg-emerald-500/15 text-emerald-300'}`}>{p.state || '—'}</span>{p.warm && <span className="text-[10px] text-amber-300">ılık</span>}</div><p className="mt-0.5 text-[11px] text-slate-500">{p.vm_count || 0} VM → <span className="font-mono">{p.target_namespace || '—'}</span></p>{p.error && <p className="mt-1 text-[11px] text-rose-200">{p.error}</p>}</div><div className="ml-auto flex gap-1.5">{running && <button onClick={onWatch} className={button}>{watching ? 'İzleniyor' : 'İzle'}</button>}{canWrite && ready && !p.started && <button onClick={onStart} className="rounded-lg bg-emerald-600 px-2 py-1 text-xs text-white inline-flex items-center gap-1"><Play size={12} /> Başlat</button>}{canWrite && running && <button onClick={onCancel} className="rounded-lg bg-amber-600 px-2 py-1 text-xs text-white">İptal</button>}{canWrite && <button title="Planı sil" onClick={onDelete} className="p-1.5 text-slate-500 hover:text-rose-300"><Trash2 size={15} /></button>}</div></div>
}

function ProgressWatch({ clusterId, base, plan, status }: any) {
  return <div className="rounded-xl border border-white/[0.06] bg-cyber-deep/50 p-4 space-y-3"><h3 className="text-xs text-slate-200">“{plan}” ilerlemesi</h3>{(status?.vms || []).map((vm: any) => <div key={vm.name} className="text-xs"><p className="text-slate-200">{vm.name} <span className="text-slate-500">— {vm.phase}</span>{vm.error && <span className="text-rose-300"> · {String(vm.error)}</span>}</p>{(vm.pipeline || []).map((s: any) => { const pct = s.total ? Math.round(Math.min(1, (s.completed || 0) / s.total) * 100) : null; return <div key={s.name} className="mt-1 flex gap-2 items-center text-[11px]"><span className={`h-1.5 w-1.5 rounded-full ${s.phase === 'Completed' ? 'bg-emerald-400' : s.phase === 'Running' ? 'bg-amber-400 animate-pulse' : 'bg-slate-600'}`} /><span className="w-44 truncate text-slate-500">{s.name}</span>{pct !== null && <><div className="h-1 flex-1 max-w-[200px] bg-white/[0.08]"><div className="h-full bg-cyan-400" style={{ width: `${pct}%` }} /></div><span className="text-slate-500">%{pct}</span></>}</div> })}</div>)}{!status?.vms?.length && <p className="text-xs text-slate-500">VM durumu bekleniyor…</p>}<MigrationLogs clusterId={clusterId} base={base} plan={plan} /></div>
}

function MigrationLogs({ clusterId, base, plan }: any) {
  const [data, setData] = useState<any>({ pods: [] }); const [selected, setSelected] = useState(''); const [container, setContainer] = useState(''); const [logs, setLogs] = useState(''); const [open, setOpen] = useState(true); const box = useRef<HTMLPreElement>(null)
  useEffect(() => { let alive = true; const load = async () => { try { const d = await api<any>(`${base}/plans/${encodeURIComponent(plan)}/pods`); if (alive) { setData(d); setSelected((x) => d.pods?.some((p: any) => p.name === x) ? x : d.pods?.[0]?.name || '') } } catch {} }; load(); const t = window.setInterval(load, 8000); return () => { alive = false; clearInterval(t) } }, [base, plan])
  const pod = data.pods?.find((p: any) => p.name === selected)
  useEffect(() => { if (pod && !pod.containers?.includes(container)) setContainer(pod.containers?.[0] || '') }, [pod, selected])
  useEffect(() => { if (!open || !selected || !data.namespace || !container) return; let alive = true; const pull = async () => { try { const d = await api<any>(`${API_BASE_URL}/openshift/clusters/${clusterId}/pods/${encodeURIComponent(data.namespace)}/${encodeURIComponent(selected)}/logs?container=${encodeURIComponent(container)}&tail=400`); if (alive) setLogs(d.logs || '') } catch (e: any) { if (alive) setLogs(`Log alınamadı: ${e.message}`) } }; pull(); const t = window.setInterval(pull, 4000); return () => { alive = false; clearInterval(t) } }, [clusterId, data.namespace, selected, container, open])
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight }, [logs])
  return <div className="border-t border-white/[0.06] pt-3"><button onClick={() => setOpen(!open)} className="flex items-center gap-1.5 text-xs text-slate-300"><FileText size={14} className="text-cyan-400" /> Canlı Log {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</button>{open && <div className="mt-2 space-y-2">{!data.pods?.length ? <p className="text-[11px] text-slate-500">Taşıma pod'u henüz oluşmadı veya tamamlandı.</p> : <><div className="flex gap-1 flex-wrap">{data.pods.map((p: any) => <button key={p.name} onClick={() => setSelected(p.name)} className={`rounded border px-2 py-1 text-[10px] font-mono ${p.name === selected ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-200' : 'border-white/[0.06] text-slate-500'}`}>{p.healthy ? '●' : '●'} {p.name}</button>)}</div>{pod?.containers?.length > 1 && <div className="flex gap-1">{pod.containers.map((c: string) => <button key={c} onClick={() => setContainer(c)} className={`text-[10px] ${c === container ? 'text-cyan-300' : 'text-slate-500'}`}>{c}</button>)}</div>}<pre ref={box} className="h-64 overflow-auto rounded-lg border border-white/[0.06] bg-black/30 p-3 text-[10px] text-cyan-100/80 whitespace-pre-wrap">{logs || 'Log bekleniyor…'}</pre></>}</div>}</div>
}

function VddkModal({ base, provider, onClose, onSaved }: any) {
  const [image, setImage] = useState(provider.vddk || ''); const [saving, setSaving] = useState(false); const [error, setError] = useState('')
  const save = async (value: string) => { setSaving(true); try { await api(`${base}/providers/${encodeURIComponent(provider.name)}/vddk`, { method: 'PUT', body: JSON.stringify({ vddk_init_image: value }) }); onSaved() } catch (e: any) { setError(e.message) } finally { setSaving(false) } }
  return <Modal title={`VDDK Ayarı — ${provider.name}`} onClose={onClose}><p className="text-xs leading-relaxed text-slate-400">VDDK, VMware disklerini kendi kütüphanesiyle okur. Tanımlanmadığında HTTPS aktarımı tipik olarak 5–10 kat daha yavaştır.</p><label className="block text-xs text-slate-500">VDDK init imajı<input className={`${input} mt-1 font-mono`} placeholder="quay.io/kurum/vddk:8.0.3" value={image} onChange={(e) => setImage(e.target.value)} /></label>{error && <p className="text-xs text-rose-300">{error}</p>}<details className="rounded-lg border border-white/[0.06] p-3 text-xs text-slate-400"><summary className="cursor-pointer text-slate-300">İmajı nasıl hazırlarım?</summary><p className="mt-2">VMware/Broadcom'dan VDDK paketini indirin, kurum registry'nize init imajı olarak derleyip gönderin. İmaj tüm küme node'larından erişilebilir olmalıdır.</p></details><div className="flex gap-2">{provider.vddk && <button disabled={saving} onClick={() => save('')} className={button}>Kaldır</button>}<button disabled={saving || !image.trim()} onClick={() => save(image)} className="flex-1 rounded-lg bg-cyan-600 py-2 text-sm text-white disabled:opacity-40">{saving ? 'Kaydediliyor…' : 'Kaydet'}</button></div></Modal>
}

function PlanWizard({ clusterId, base, providers, hypervisors, onClose, onCreated }: any) {
  const sourceProviders = (providers || []).filter((p: any) => p.type !== 'openshift')
  // Atlas ile aynı: VDDK'lı provider varsayılan (yoksa ilk)
  const [providerName, setProviderName] = useState(
    () => (sourceProviders.find((p: any) => p.vddk) || sourceProviders[0])?.name || '',
  )
  const selectedProvider = sourceProviders.find((p: any) => p.name === providerName)
  const [step, setStep] = useState(1)
  const [name, setName] = useState('')
  const [hypervisorId, setHypervisorId] = useState(String(hypervisors[0]?.id || ''))
  const [vms, setVms] = useState<any[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState('')
  const [targets, setTargets] = useState<any>(null)
  const [refs, setRefs] = useState<any>(null)
  const [sMap, setSMap] = useState<Record<string, string>>({})
  const [nMap, setNMap] = useState<Record<string, string>>({})
  const [targetNs, setTargetNs] = useState('vm-migrasyon')
  const [warm, setWarm] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!hypervisorId) return
    api<any[]>(`${base}/source-vms?hypervisor_id=${encodeURIComponent(hypervisorId)}`)
      .then(setVms)
      .catch((e) => setError(e.message))
    setSelected(new Set())
  }, [base, hypervisorId])
  useEffect(() => {
    api<any>(`${base}/targets`).then(setTargets).catch((e) => setError(e.message))
  }, [base])
  // Provider listesi yenilenince VDDK'lıyı tercih et (ilk açılış / boş seçim)
  useEffect(() => {
    if (!sourceProviders.length) return
    if (providerName && sourceProviders.some((p: any) => p.name === providerName)) return
    setProviderName((sourceProviders.find((p: any) => p.vddk) || sourceProviders[0]).name)
  }, [providers])

  const defaultSc = targets?.storage_classes?.find((s: any) => s.default)?.name || targets?.storage_classes?.[0]?.name || ''
  const next = async () => {
    setLoading(true)
    setError('')
    try {
      const r = await api<any>(`${base}/source-refs`, {
        method: 'POST',
        body: JSON.stringify({ hypervisor_id: Number(hypervisorId), vm_morefs: [...selected] }),
      })
      setRefs(r)
      setSMap(Object.fromEntries((r.datastores || []).map((d: any) => [d.moref, defaultSc])))
      setNMap(Object.fromEntries((r.networks || []).map((n: any) => [n.moref, 'pod'])))
      setStep(2)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }
  const create = async () => {
    setLoading(true)
    setError('')
    try {
      const networkOptions = targets?.networks || [{ type: 'pod', name: 'pod' }]
      await api(`${base}/plans`, {
        method: 'POST',
        body: JSON.stringify({
          plan_name: name,
          provider_name: providerName,
          hypervisor_id: Number(hypervisorId),
          vms: vms.filter((v) => selected.has(v.moref)).map((v) => ({ id: v.moref, name: v.name })),
          target_namespace: targetNs,
          warm,
          storage_class: defaultSc,
          network: { type: 'pod' },
          storage_map: (refs?.datastores || []).map((d: any) => ({
            source_id: d.moref,
            source_name: d.name,
            storage_class: sMap[d.moref],
          })),
          network_map: (refs?.networks || []).map((n: any) => {
            const key = nMap[n.moref] || 'pod'
            const o =
              networkOptions.find((x: any) => (x.type === 'pod' ? 'pod' : `multus:${x.name}`) === key) ||
              { type: 'pod' }
            return {
              source_id: n.moref,
              source_name: n.name,
              type: o.type,
              name: o.name,
              namespace: o.namespace,
              namespaces: o.namespaces,
            }
          }),
        }),
      })
      onCreated()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }
  const toggle = (id: string) =>
    setSelected((old) => {
      const next = new Set(old)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  const nets = targets?.networks || [{ type: 'pod', name: 'pod', label: 'Pod ağı' }]
  const filteredVms = vms.filter(
    (v) => !search || v.name.toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <Modal title="Yeni Taşıma Planı" onClose={onClose} wide>
      <div className="flex items-center gap-2 mb-4">
        {['VM Seçimi', 'Eşleme', 'Hedef & Onay'].map((label, i) => (
          <div key={label} className="flex items-center gap-1.5 flex-1">
            <span
              className={`h-5 w-5 rounded-full text-[10px] flex items-center justify-center ${
                step > i + 1 ? 'bg-emerald-500' : step === i + 1 ? 'bg-cyan-600' : 'bg-white/[0.08] text-slate-500'
              }`}
            >
              {step > i + 1 ? <Check size={12} /> : i + 1}
            </span>
            <span className={`text-[11px] ${step >= i + 1 ? 'text-slate-200' : 'text-slate-500'}`}>{label}</span>
          </div>
        ))}
      </div>
      {error && <p className="rounded-lg bg-rose-500/10 p-2 text-xs text-rose-200">{error}</p>}

      {step === 1 && (
        <div className="space-y-3">
          <div className="grid sm:grid-cols-2 gap-3">
            <label className="text-xs text-slate-500">
              Plan adı
              <input
                className={`${input} mt-1`}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="örn. uretim-tasima"
              />
            </label>
            <div>
              <label className="text-xs text-slate-500 block mb-1">Kaynak sağlayıcı (MTV)</label>
              <select
                className={input}
                value={providerName}
                onChange={(e) => setProviderName(e.target.value)}
              >
                {sourceProviders.map((p: any) => (
                  <option key={p.name} value={p.name}>
                    {p.name} — {p.vddk ? 'VDDK etkin (hızlı)' : 'VDDK yok (yavaş)'}
                  </option>
                ))}
              </select>
              {selectedProvider && !selectedProvider.vddk && (
                <p className="mt-1 flex items-start gap-1.5 text-[11px] text-amber-300/90">
                  <AlertTriangle className="mt-px h-3.5 w-3.5 flex-shrink-0" />
                  <span>
                    Bu sağlayıcıda VDDK tanımlı değil — diskler vCenter&apos;dan HTTPS ile çekilir
                    (tipik 5–10 kat yavaş). Sağlayıcı kartındaki <b>Ayarla</b> ile VDDK imajını
                    tanımlayın.
                  </span>
                </p>
              )}
            </div>
          </div>
          <label className="block text-xs text-slate-500">
            Kaynak vCenter
            <select
              className={`${input} mt-1`}
              value={hypervisorId}
              onChange={(e) => setHypervisorId(e.target.value)}
            >
              {hypervisors.map((h: any) => (
                <option key={h.id} value={h.id}>
                  {h.name} ({h.hostname || h.ip || '—'})
                </option>
              ))}
            </select>
          </label>
          <div>
            <div className="mb-1 flex items-center gap-2">
              <p className="text-xs text-slate-500">Taşınacak VM&apos;ler ({selected.size} seçili)</p>
              <input
                className="ml-auto rounded border border-white/[0.08] bg-cyber-deep px-2 py-1 text-xs"
                placeholder="ara…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className="max-h-52 overflow-auto rounded-lg border border-white/[0.06]">
              {filteredVms.length ? (
                filteredVms.map((v) => (
                  <label
                    key={v.moref}
                    className="flex gap-2 border-b border-white/[0.04] px-3 py-2 text-xs hover:bg-white/[0.03]"
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(v.moref)}
                      onChange={() => toggle(v.moref)}
                    />
                    <span className={v.power_state === 'poweredOn' ? 'text-emerald-400' : 'text-slate-500'}>
                      ●
                    </span>
                    <span className="text-slate-200">{v.name}</span>
                    {!warm && v.power_state === 'poweredOn' && (
                      <span className="text-[10px] text-amber-400/80">soğuk taşımada kapatılacak</span>
                    )}
                    <span className="ml-auto font-mono text-slate-500">{v.moref}</span>
                  </label>
                ))
              ) : (
                <p className="p-3 text-xs text-slate-500">VM yok</p>
              )}
            </div>
          </div>
          <button
            disabled={!name.trim() || !selected.size || !providerName || loading}
            onClick={next}
            className="w-full rounded-lg bg-cyan-600 py-2 text-sm text-white disabled:opacity-40"
          >
            {loading ? 'Kaynaklar okunuyor…' : 'Devam — Eşlemeye Geç'}
          </button>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-4">
          <p className="text-xs text-slate-400">
            VM&apos;lerin kullandığı datastore ve ağları OpenShift hedeflerine eşleyin.
          </p>
          {refs?.warnings?.length > 0 && (
            <div className="rounded-lg border border-amber-500/25 bg-amber-500/10 p-3 text-xs text-amber-100">
              {refs.warnings.map((w: string) => (
                <p key={w}>• {w}</p>
              ))}
            </div>
          )}
          <Mapping
            title="Depolama eşlemesi"
            icon={<HardDrive size={14} />}
            refs={refs?.datastores}
            value={sMap}
            setValue={setSMap}
            options={targets?.storage_classes || []}
            optionKey={(x: any) => x.name}
            optionLabel={(x: any) => `${x.name}${x.default ? ' (varsayılan)' : ''}`}
          />
          <Mapping
            title="Ağ eşlemesi"
            icon={<Network size={14} />}
            refs={refs?.networks}
            value={nMap}
            setValue={setNMap}
            options={nets}
            optionKey={(x: any) => (x.type === 'pod' ? 'pod' : `multus:${x.name}`)}
            optionLabel={(x: any) => x.label || x.name}
          />
          <div className="flex gap-2">
            <button className={button} onClick={() => setStep(1)}>
              Geri
            </button>
            <button className="flex-1 rounded-lg bg-cyan-600 py-2 text-sm text-white" onClick={() => setStep(3)}>
              Devam
            </button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="space-y-3">
          <label className="text-xs text-slate-500">
            Hedef namespace
            <input className={`${input} mt-1`} value={targetNs} onChange={(e) => setTargetNs(e.target.value)} />
          </label>
          <label className="flex gap-2 text-xs text-slate-300">
            <input type="checkbox" checked={warm} onChange={(e) => setWarm(e.target.checked)} />
            <span>
              Ilık taşıma (warm)
              <span className="mt-1 block text-slate-500">
                VM açıkken kopyalar; son geçişte kısa kesinti olur. CBT açık olmalıdır.
              </span>
            </span>
          </label>
          <div className="rounded-lg bg-cyber-deep p-3 text-xs text-slate-400 space-y-1">
            <p>
              <b className="text-slate-200">{selected.size} VM</b> →{' '}
              <span className="font-mono">{targetNs}</span>
            </p>
            <p>
              Sağlayıcı: <span className="font-mono text-slate-200">{providerName}</span>{' '}
              {selectedProvider?.vddk ? (
                <span className="text-emerald-400">— VDDK etkin, hızlı kopyalama</span>
              ) : (
                <span className="text-amber-300">— VDDK yok (HTTPS, yavaş)</span>
              )}
            </p>
            <p>
              Taşıma tipi:{' '}
              <b className="text-slate-200">{warm ? 'ılık (warm)' : 'soğuk (cold)'}</b>
              {!warm && <span className="text-amber-300"> — açık VM&apos;ler kapatılacak</span>}
            </p>
          </div>
          <div className="flex gap-2">
            <button className={button} onClick={() => setStep(2)}>
              Geri
            </button>
            <button
              disabled={loading}
              onClick={create}
              className="flex-1 rounded-lg bg-cyan-600 py-2 text-sm text-white disabled:opacity-40"
            >
              {loading ? 'Oluşturuluyor…' : `Planı Oluştur (${selected.size} VM)`}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}

function Mapping({ title, icon, refs, value, setValue, options, optionKey, optionLabel }: any) { return <div><p className="mb-2 flex gap-1.5 text-xs text-slate-300">{icon} {title}</p>{!refs?.length ? <p className="text-xs text-slate-500">Kaynak bulunamadı.</p> : <div className="space-y-1.5">{refs.map((r: any) => <div key={r.moref} className="grid grid-cols-[1fr_1fr] gap-2 text-xs items-center"><span className="truncate text-slate-300">{r.name}</span><select className={input} value={value[r.moref] || ''} onChange={(e) => setValue({ ...value, [r.moref]: e.target.value })}>{options.map((o: any) => <option key={optionKey(o)} value={optionKey(o)}>{optionLabel(o)}</option>)}</select></div>)}</div>}</div> }
function Modal({ title, onClose, children, wide = false }: any) { return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onMouseDown={onClose}><div className={`max-h-[92vh] w-full ${wide ? 'max-w-3xl' : 'max-w-xl'} overflow-y-auto rounded-xl border border-white/[0.1] bg-cyber-card p-5 shadow-2xl space-y-4`} onMouseDown={(e) => e.stopPropagation()}><div className="flex justify-between items-center"><h2 className="text-base text-white">{title}</h2><button className="text-slate-400 hover:text-white" onClick={onClose}><X size={18} /></button></div>{children}</div></div> }
