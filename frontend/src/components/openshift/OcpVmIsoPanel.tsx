/**
 * VM'e ISO / CD-ROM bağlama paneli (admin):
 *  - mevcut PVC (aynı namespace: doğrudan, başka namespace: klon)
 *  - istemci bilgisayardan ISO yükleme (tarayıcı → ainew → CDI upload proxy)
 *  - takılı CD-ROM'ları çıkarma
 */
import { useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Disc3, RefreshCw, Upload, X, ArrowUpFromLine } from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import { getToken } from '../../auth/authStore'
import { useT } from '../../i18n/LocaleProvider'

type Vm = { name: string; namespace: string }
type Source = {
  namespace: string
  name: string
  size?: string
  storage_class?: string
  phase?: string
  iso_guess: boolean
  same_namespace: boolean
}
type Cdrom = { disk: string; source_kind: string; source: string; boot_order?: number | null }

type Props = {
  clusterId: number
  vm: Vm
  running: boolean
  onClose: () => void
  onChanged: () => void
}

const inputCls = 'w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white'

async function api(path: string, init?: RequestInit) {
  const r = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) {
    throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.[0]?.msg || `HTTP ${r.status}`)
  }
  return data
}

function fmtBytes(n: number): string {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(2)} GiB`
  return `${(n / 1024 ** 2).toFixed(1)} MiB`
}

function pvcNameFromFile(fn: string): string {
  const base = fn.replace(/\.[^.]+$/, '').toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '')
  return (`iso-${base}` || 'iso').slice(0, 58).replace(/-+$/g, '')
}

export default function OcpVmIsoPanel({ clusterId, vm, running, onClose, onChanged }: Props) {
  const t = useT()
  const qc = useQueryClient()
  const [tab, setTab] = useState<'existing' | 'upload'>('existing')
  const [filter, setFilter] = useState('')
  const [onlyIso, setOnlyIso] = useState(true)
  const [picked, setPicked] = useState<string>('')
  const [bootFirst, setBootFirst] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [pvcName, setPvcName] = useState('')
  const [storageClass, setStorageClass] = useState('')
  const [attachAfter, setAttachAfter] = useState(true)
  const [pct, setPct] = useState<number | null>(null)
  const xhrRef = useRef<XMLHttpRequest | null>(null)

  const vmBase = `/openshift/clusters/${clusterId}/kubevirt/vms/${encodeURIComponent(vm.namespace)}/${encodeURIComponent(vm.name)}`

  const cdroms = useQuery({
    queryKey: ['ocp-vm-cdroms', clusterId, vm.namespace, vm.name],
    queryFn: () => api(`${vmBase}/cdroms`) as Promise<{ cdroms: Cdrom[] }>,
  })
  const sources = useQuery({
    queryKey: ['ocp-iso-sources', clusterId, vm.namespace],
    queryFn: () =>
      api(`/openshift/clusters/${clusterId}/kubevirt/iso-sources?namespace=${encodeURIComponent(vm.namespace)}`) as Promise<{
        items: Source[]
        scope: string
        truncated: boolean
      }>,
    enabled: tab === 'existing',
  })
  const storage = useQuery({
    queryKey: ['openshift-storage', clusterId],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/storage`)
      if (!r.ok) return { storage_classes: [] as { name: string; default?: boolean }[] }
      return r.json()
    },
    enabled: tab === 'upload',
  })
  const classes: { name: string; default?: boolean }[] = storage.data?.storage_classes || []

  const items = useMemo(() => {
    const all = sources.data?.items || []
    const anyIso = all.some((s) => s.iso_guess)
    const q = filter.trim().toLowerCase()
    return all.filter((s) => {
      if (onlyIso && anyIso && !s.iso_guess) return false
      if (!q) return true
      return `${s.namespace}/${s.name}`.toLowerCase().includes(q)
    })
  }, [sources.data, filter, onlyIso])

  const afterChange = (note?: string) => {
    qc.invalidateQueries({ queryKey: ['ocp-vm-cdroms', clusterId, vm.namespace, vm.name] })
    qc.invalidateQueries({ queryKey: ['ocp-iso-sources', clusterId] })
    qc.invalidateQueries({ queryKey: ['openshift-vm-detail', clusterId, vm.namespace, vm.name] })
    onChanged()
    if (note) setMsg(note)
  }

  const attach = async () => {
    const [ns, name] = picked.split('/')
    if (!ns || !name) return
    setBusy(true)
    setErr('')
    setMsg('')
    try {
      const r = await api(`${vmBase}/cdrom`, {
        method: 'POST',
        body: JSON.stringify({ source_namespace: ns, source_pvc: name, boot_first: bootFirst }),
      })
      afterChange(r.note || t('ocp_iso_done_attach'))
      setPicked('')
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const eject = async (disk: string) => {
    if (!window.confirm(t('ocp_iso_eject_confirm', { disk }))) return
    setBusy(true)
    setErr('')
    setMsg('')
    try {
      const r = await api(`${vmBase}/cdrom/${encodeURIComponent(disk)}`, { method: 'DELETE' })
      afterChange(r.note)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const upload = () => {
    if (!file || !pvcName) return
    const qs = new URLSearchParams({ namespace: vm.namespace, name: pvcName })
    if (storageClass) qs.set('storage_class', storageClass)
    if (attachAfter) {
      qs.set('attach_vm', vm.name)
      if (bootFirst) qs.set('boot_first', 'true')
    }
    const xhr = new XMLHttpRequest()
    xhrRef.current = xhr
    xhr.open('POST', `${API_BASE_URL}/openshift/clusters/${clusterId}/kubevirt/iso-upload?${qs.toString()}`)
    const token = getToken()
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.setRequestHeader('Content-Type', 'application/octet-stream')
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable) setPct(Math.min(100, Math.round((ev.loaded / ev.total) * 100)))
    }
    xhr.onload = () => {
      xhrRef.current = null
      setBusy(false)
      setPct(null)
      let data: any = {}
      try {
        data = JSON.parse(xhr.responseText || '{}')
      } catch {
        /* boş */
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        const att = data.attached
        let note = t('ocp_iso_done', { name: `${data.namespace}/${data.pvc}` })
        if (att) note += ` ${t('ocp_iso_done_attach')}`
        if (att?.restart_required) note += ` ${t('ocp_iso_restart')}`
        afterChange(note)
        setFile(null)
        setPvcName('')
      } else {
        setErr(typeof data.detail === 'string' ? data.detail : `HTTP ${xhr.status}`)
      }
    }
    xhr.onerror = () => {
      xhrRef.current = null
      setBusy(false)
      setPct(null)
      setErr(t('ocp_action_fail'))
    }
    xhr.onabort = () => {
      xhrRef.current = null
      setBusy(false)
      setPct(null)
    }
    setErr('')
    setMsg('')
    setBusy(true)
    setPct(0)
    xhr.send(file)
  }

  const cancelUpload = () => xhrRef.current?.abort()
  const close = () => {
    if (xhrRef.current) {
      if (!window.confirm(t('ocp_iso_cancel') + '?')) return
      xhrRef.current.abort()
    }
    onClose()
  }

  const needGi = file ? Math.max(1, Math.ceil((file.size * 1.1 + 64 * 1024 * 1024) / 1024 ** 3)) : 0

  return (
    <div className="fixed inset-0 bg-black/55 z-[90] flex items-center justify-center p-4" onClick={() => !busy && close()} onContextMenu={(e) => e.stopPropagation()}>
      <div
        className="bg-cyber-card border border-white/[0.08] rounded-xl w-full max-w-lg p-4 space-y-3 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <div className="text-sm text-white font-medium inline-flex items-center gap-2">
            <Disc3 size={14} /> {t('ocp_iso_title')}
          </div>
          <button type="button" onClick={close} className="text-slate-400"><X size={16} /></button>
        </div>
        <p className="text-[11px] text-slate-500">{vm.namespace}/{vm.name}</p>

        <div>
          <div className="text-[11px] text-slate-400 mb-1">{t('ocp_iso_attached')}</div>
          {(cdroms.data?.cdroms || []).length === 0 ? (
            <div className="text-xs text-slate-500">{cdroms.isLoading ? '…' : t('ocp_iso_none')}</div>
          ) : (
            <ul className="space-y-1">
              {(cdroms.data?.cdroms || []).map((c) => (
                <li key={c.disk} className="flex items-center justify-between text-xs bg-cyber-deep rounded-lg px-3 py-1.5">
                  <span className="text-slate-200 truncate">
                    {c.disk} <span className="text-slate-500">← {c.source}</span>
                  </span>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => eject(c.disk)}
                    className="inline-flex items-center gap-1 text-amber-300 hover:text-amber-200 disabled:opacity-40"
                  >
                    <ArrowUpFromLine size={12} /> {t('ocp_iso_eject')}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex gap-1 border-b border-white/[0.06]">
          {(['existing', 'upload'] as const).map((k) => (
            <button
              key={k}
              type="button"
              disabled={busy}
              onClick={() => setTab(k)}
              className={`px-3 py-1.5 text-xs border-b-2 -mb-px ${
                tab === k ? 'border-sky-500 text-white' : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              {k === 'existing' ? t('ocp_iso_tab_existing') : t('ocp_iso_tab_upload')}
            </button>
          ))}
        </div>

        {tab === 'existing' && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={t('ocp_iso_filter')} className={inputCls} />
              <label className="text-[11px] text-slate-400 inline-flex items-center gap-1 whitespace-nowrap">
                <input type="checkbox" checked={onlyIso} onChange={(e) => setOnlyIso(e.target.checked)} /> {t('ocp_iso_only_iso')}
              </label>
            </div>
            {sources.data?.scope === 'namespace' && (
              <div className="text-[11px] text-amber-300/90">{t('ocp_iso_scope_ns')}</div>
            )}
            <div className="max-h-52 overflow-y-auto rounded-lg border border-white/[0.06] divide-y divide-white/[0.04]">
              {sources.isLoading && <div className="p-3 text-xs text-slate-500">…</div>}
              {!sources.isLoading && items.length === 0 && (
                <div className="p-3 text-xs text-slate-500">{t('ocp_iso_empty')}</div>
              )}
              {items.map((s) => {
                const key = `${s.namespace}/${s.name}`
                return (
                  <label
                    key={key}
                    className={`flex items-start gap-2 px-3 py-1.5 text-xs cursor-pointer hover:bg-white/[0.04] ${
                      picked === key ? 'bg-sky-500/10' : ''
                    }`}
                  >
                    <input type="radio" name="iso-src" checked={picked === key} onChange={() => setPicked(key)} className="mt-0.5" />
                    <span className="min-w-0">
                      <span className="text-slate-100 break-all">{key}</span>
                      <span className="text-slate-500"> · {s.size || '?'}{s.iso_guess ? ' · ISO' : ''}</span>
                      <span className="block text-[10px] text-slate-500">
                        {s.same_namespace ? t('ocp_iso_same_ns') : t('ocp_iso_clone_note', { ns: s.namespace })}
                      </span>
                    </span>
                  </label>
                )
              })}
            </div>
            <label className="text-[11px] text-slate-300 inline-flex items-center gap-1.5">
              <input type="checkbox" checked={bootFirst} onChange={(e) => setBootFirst(e.target.checked)} /> {t('ocp_iso_boot_first')}
            </label>
            <button
              type="button"
              disabled={busy || !picked}
              onClick={attach}
              className="w-full py-2 rounded-lg bg-rose-600 text-white text-sm font-medium disabled:opacity-50 inline-flex items-center justify-center gap-1.5"
            >
              {busy && <RefreshCw size={12} className="animate-spin" />} {t('ocp_iso_attach')}
            </button>
          </div>
        )}

        {tab === 'upload' && (
          <div className="space-y-2">
            <input
              type="file"
              accept=".iso,.img,application/x-iso9660-image"
              disabled={busy}
              onChange={(e) => {
                const f = e.target.files?.[0] || null
                setFile(f)
                setPvcName(f ? pvcNameFromFile(f.name) : '')
              }}
              className="block w-full text-xs text-slate-300 file:mr-3 file:rounded-lg file:border-0 file:bg-white/[0.08] file:px-3 file:py-1.5 file:text-slate-100"
            />
            {file && (
              <>
                <div className="text-[11px] text-slate-400">{t('ocp_iso_size_info', { size: fmtBytes(file.size), gi: needGi })}</div>
                <input value={pvcName} disabled={busy} onChange={(e) => setPvcName(e.target.value)} placeholder={t('ocp_iso_pvc_name')} className={inputCls} />
                <select value={storageClass} disabled={busy} onChange={(e) => setStorageClass(e.target.value)} className={inputCls}>
                  <option value="">{t('ocp_sc_cluster_default')}</option>
                  {classes.map((sc) => (
                    <option key={sc.name} value={sc.name}>{sc.name}{sc.default ? t('ocp_sc_default_paren') : ''}</option>
                  ))}
                </select>
                <label className="text-[11px] text-slate-300 inline-flex items-center gap-1.5">
                  <input type="checkbox" disabled={busy} checked={attachAfter} onChange={(e) => setAttachAfter(e.target.checked)} /> {t('ocp_iso_attach_after')}
                </label>
                {attachAfter && (
                  <label className="text-[11px] text-slate-300 flex items-center gap-1.5">
                    <input type="checkbox" disabled={busy} checked={bootFirst} onChange={(e) => setBootFirst(e.target.checked)} /> {t('ocp_iso_boot_first')}
                  </label>
                )}
              </>
            )}
            {pct !== null && (
              <div className="space-y-1">
                <div className="h-2 rounded bg-white/[0.08] overflow-hidden">
                  <div className="h-full bg-sky-500 transition-all" style={{ width: `${pct}%` }} />
                </div>
                <div className="text-[11px] text-slate-400">{t('ocp_iso_uploading', { pct: `${pct}%` })}</div>
              </div>
            )}
            {busy ? (
              <button type="button" onClick={cancelUpload} className="w-full py-2 rounded-lg bg-white/[0.08] text-slate-100 text-sm">
                {t('ocp_iso_cancel')}
              </button>
            ) : (
              <button
                type="button"
                disabled={!file || !pvcName}
                onClick={upload}
                className="w-full py-2 rounded-lg bg-rose-600 text-white text-sm font-medium disabled:opacity-50 inline-flex items-center justify-center gap-1.5"
              >
                <Upload size={12} /> {t('ocp_iso_upload')}
              </button>
            )}
          </div>
        )}

        {running && <div className="text-[11px] text-slate-500">{t('ocp_iso_restart')}</div>}
        {msg && <div className="text-xs text-emerald-300">{msg}</div>}
        {err && <div className="text-xs text-red-400">{err}</div>}
      </div>
    </div>
  )
}
