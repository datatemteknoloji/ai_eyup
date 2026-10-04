/**
 * OpenShift Access / RBAC — Users, Groups, Roles, Bindings (READ-ONLY).
 */
import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Shield, Users, UsersRound, KeyRound, Link2, Search, RefreshCw,
  ChevronRight, AlertTriangle, Fingerprint, UserCircle2,
} from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { useT } from '../i18n/LocaleProvider'

type Cluster = { id: number; name: string; api_url?: string; status?: string }

type TabId =
  | 'overview'
  | 'users'
  | 'groups'
  | 'identities'
  | 'roles'
  | 'clusterroles'
  | 'rolebindings'
  | 'clusterrolebindings'
  | 'serviceaccounts'
  | 'subject'
  | 'can_i'
  | 'idp'

const TABS: { id: TabId; labelKey: string; kind?: string }[] = [
  { id: 'overview', labelKey: 'ocp_acc_tab_overview' },
  { id: 'users', labelKey: 'ocp_acc_tab_users', kind: 'users' },
  { id: 'groups', labelKey: 'ocp_acc_tab_groups', kind: 'groups' },
  { id: 'identities', labelKey: 'ocp_acc_tab_identities', kind: 'identities' },
  { id: 'roles', labelKey: 'ocp_acc_tab_roles', kind: 'roles' },
  { id: 'clusterroles', labelKey: 'ocp_acc_tab_clusterroles', kind: 'clusterroles' },
  { id: 'rolebindings', labelKey: 'ocp_acc_tab_rolebindings', kind: 'rolebindings' },
  { id: 'clusterrolebindings', labelKey: 'ocp_acc_tab_crb', kind: 'clusterrolebindings' },
  { id: 'serviceaccounts', labelKey: 'ocp_acc_tab_sa', kind: 'serviceaccounts' },
  { id: 'subject', labelKey: 'ocp_acc_tab_subject' },
  { id: 'can_i', labelKey: 'ocp_acc_tab_can_i' },
  { id: 'idp', labelKey: 'ocp_acc_tab_idp' },
]

export default function OpenShiftAccessPage() {
  const t = useT()
  const [clusterId, setClusterId] = useState<number | null>(null)
  const [tab, setTab] = useState<TabId>('overview')
  const [q, setQ] = useState('')
  const [namespace, setNamespace] = useState('')
  const [selected, setSelected] = useState<any | null>(null)
  const [subjKind, setSubjKind] = useState('User')
  const [subjName, setSubjName] = useState('')
  const [subjNs, setSubjNs] = useState('')
  const [canVerb, setCanVerb] = useState('list')
  const [canResource, setCanResource] = useState('users')
  const [canGroup, setCanGroup] = useState('user.openshift.io')

  const { data: clusters = [] } = useQuery<Cluster[]>({
    queryKey: ['openshift-clusters'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters`)
      if (!r.ok) return []
      const body = await r.json()
      return Array.isArray(body?.clusters) ? body.clusters : []
    },
  })

  const { data: nsOptions = [] } = useQuery<string[]>({
    queryKey: ['ocp-access-namespaces', clusterId],
    enabled: !!clusterId,
    staleTime: 60_000,
    queryFn: async () => {
      const p = new URLSearchParams({
        cluster_id: String(clusterId),
        include_system: 'true',
        page_size: '1000',
        page: '1',
      })
      const r = await fetch(`${API_BASE_URL}/openshift/projects?${p}`)
      if (!r.ok) return []
      const body = await r.json()
      const names = (body?.projects || [])
        .map((x: any) => x.name)
        .filter(Boolean)
      return Array.from(new Set(names as string[])).sort((a, b) => a.localeCompare(b))
    },
  })

  useEffect(() => {
    if (!clusters.length) {
      setClusterId(null)
      return
    }
    if (!clusterId || !clusters.find((c) => c.id === clusterId)) {
      setClusterId(clusters[0].id)
    }
  }, [clusters, clusterId])

  const overviewQ = useQuery({
    queryKey: ['ocp-access-overview', clusterId],
    enabled: !!clusterId && tab === 'overview',
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/access/overview`)
      if (!r.ok) throw new Error(await r.text())
      return r.json()
    },
  })

  const listKind = TABS.find((x) => x.id === tab)?.kind
  const listQ = useQuery({
    queryKey: ['ocp-access-list', clusterId, listKind, namespace, q],
    enabled: !!clusterId && !!listKind,
    queryFn: async () => {
      const p = new URLSearchParams({ kind: listKind!, limit: '800' })
      if (namespace.trim()) p.set('namespace', namespace.trim())
      if (q.trim()) p.set('q', q.trim())
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/access/list?${p}`)
      if (!r.ok) throw new Error(await r.text())
      return r.json()
    },
  })

  const subjectQ = useQuery({
    queryKey: ['ocp-access-subject', clusterId, subjKind, subjName, subjNs, namespace],
    enabled: !!clusterId && tab === 'subject' && !!subjName.trim(),
    queryFn: async () => {
      const p = new URLSearchParams({
        subject_kind: subjKind,
        subject_name: subjName.trim(),
        limit: '500',
      })
      if (subjNs.trim()) p.set('subject_namespace', subjNs.trim())
      if (namespace.trim()) p.set('namespace', namespace.trim())
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/access/subject?${p}`)
      if (!r.ok) throw new Error(await r.text())
      return r.json()
    },
  })

  const canIQ = useQuery({
    queryKey: ['ocp-access-can-i', clusterId, canVerb, canResource, canGroup, namespace],
    enabled: !!clusterId && tab === 'can_i',
    queryFn: async () => {
      const p = new URLSearchParams({
        verb: canVerb,
        resource: canResource,
        api_group: canGroup,
      })
      if (namespace.trim()) p.set('namespace', namespace.trim())
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/access/can-i?${p}`)
      if (!r.ok) throw new Error(await r.text())
      return r.json()
    },
  })

  const idpQ = useQuery({
    queryKey: ['ocp-access-idp', clusterId],
    enabled: !!clusterId && tab === 'idp',
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/access/identity-providers`)
      if (!r.ok) throw new Error(await r.text())
      return r.json()
    },
  })

  const detailQ = useQuery({
    queryKey: ['ocp-access-get', clusterId, selected?.kind, selected?.name, selected?.namespace],
    enabled: !!clusterId && !!selected?.name && !!listKind,
    queryFn: async () => {
      const kind = listKind!
      const p = new URLSearchParams({ kind, name: selected.name })
      if (selected.namespace) p.set('namespace', selected.namespace)
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/access/get?${p}`)
      if (!r.ok) throw new Error(await r.text())
      return r.json()
    },
  })

  const needsNs = ['roles', 'rolebindings', 'serviceaccounts'].includes(listKind || '')

  const items = useMemo(() => listQ.data?.items || [], [listQ.data])

  return (
    <div className="px-4 pt-3 pb-6 max-w-[1800px] mx-auto space-y-4 w-full">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-white flex items-center gap-2">
            <Shield size={20} className="text-blue-400" />
            {t('ocp_acc_title')}
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">{t('ocp_acc_subtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={clusterId ?? ''}
            onChange={(e) => {
              setClusterId(Number(e.target.value) || null)
              setSelected(null)
              setNamespace('')
              setSubjNs('')
            }}
            className="bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1.5 text-xs text-slate-200"
          >
            {!clusters.length && <option value="">{t('ocp_acc_no_cluster')}</option>}
            {clusters.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5 border-b border-white/[0.06] pb-2">
        {TABS.map((tb) => (
          <button
            key={tb.id}
            type="button"
            onClick={() => { setTab(tb.id); setSelected(null) }}
            className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${
              tab === tb.id
                ? 'bg-blue-600/30 text-blue-200 border border-blue-500/40'
                : 'text-slate-400 hover:text-slate-200 hover:bg-white/[0.04]'
            }`}
          >
            {t(tb.labelKey as any)}
          </button>
        ))}
      </div>

      {!clusterId && (
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4 text-sm text-amber-200">
          {t('ocp_acc_no_cluster')}
        </div>
      )}

      {clusterId && tab === 'overview' && (
        <OverviewPanel data={overviewQ.data} loading={overviewQ.isFetching} error={overviewQ.error as Error | null} t={t} />
      )}

      {clusterId && listKind && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2 items-end">
            <div className="flex-1 min-w-[160px]">
              <label className="text-[10px] uppercase text-slate-500">{t('ocp_acc_search')}</label>
              <div className="relative">
                <Search size={14} className="absolute left-2 top-2.5 text-slate-500" />
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  className="w-full bg-cyber-deep border border-white/[0.08] rounded-md pl-7 pr-2 py-1.5 text-xs text-slate-200"
                  placeholder={t('ocp_acc_search_ph')}
                />
              </div>
            </div>
            {needsNs && (
              <div className="w-56">
                <label className="text-[10px] uppercase text-slate-500">{t('ocp_acc_namespace')}</label>
                <select
                  value={namespace}
                  onChange={(e) => { setNamespace(e.target.value); setSelected(null) }}
                  className="w-full bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1.5 text-xs text-slate-200 font-mono"
                >
                  <option value="">{t('ocp_acc_ns_all')}</option>
                  {nsOptions.map((ns) => (
                    <option key={ns} value={ns}>{ns}</option>
                  ))}
                </select>
              </div>
            )}
            <button
              type="button"
              onClick={() => listQ.refetch()}
              className="p-2 rounded-md text-slate-400 hover:text-white hover:bg-white/[0.06]"
              title={t('refresh_action')}
            >
              <RefreshCw size={14} className={listQ.isFetching ? 'animate-spin' : ''} />
            </button>
          </div>

          {listQ.data && listQ.data.ok === false && (
            <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <span>{listQ.data.error}</span>
            </div>
          )}

          <div className="grid lg:grid-cols-[minmax(0,38%)_minmax(0,1fr)] gap-3 items-start">
            <div className="rounded-xl border border-white/[0.06] bg-cyber-card overflow-hidden min-w-0">
              <div className="px-3 py-2 text-[10px] uppercase text-slate-500 border-b border-white/[0.04] flex justify-between gap-2">
                <span className="truncate">{listKind}</span>
                <span className="shrink-0 tabular-nums">{listQ.data?.count ?? '…'} {t('ocp_acc_items')}</span>
              </div>
              <div className="max-h-[min(70vh,640px)] overflow-y-auto">
                {listQ.isLoading && <p className="p-4 text-xs text-slate-500">{t('mon_loading')}</p>}
                {items.map((it: any) => (
                  <button
                    key={`${it.namespace}:${it.name}:${it.uid || it.name}`}
                    type="button"
                    onClick={() => setSelected(it)}
                    className={`w-full text-left px-3 py-2 border-b border-white/[0.03] hover:bg-white/[0.03] min-w-0 ${
                      selected?.name === it.name && selected?.namespace === it.namespace
                        ? 'bg-blue-600/15'
                        : ''
                    }`}
                  >
                    <div className="flex items-center gap-2 text-xs text-slate-200 min-w-0">
                      <RowIcon kind={listKind} />
                      <span className="font-mono truncate flex-1 min-w-0">{it.name}</span>
                      {it.namespace ? (
                        <span className="text-[10px] text-slate-500 font-mono shrink-0 max-w-[40%] truncate">{it.namespace}</span>
                      ) : null}
                      <ChevronRight size={12} className="text-slate-600 shrink-0" />
                    </div>
                    <RowHint item={it} kind={listKind} />
                  </button>
                ))}
                {!listQ.isLoading && items.length === 0 && listQ.data?.ok !== false && (
                  <p className="p-4 text-xs text-slate-500">{t('ocp_acc_empty')}</p>
                )}
              </div>
            </div>

            <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-3 min-h-[200px] min-w-0 overflow-hidden">
              {!selected && (
                <p className="text-xs text-slate-500 py-8 text-center">{t('ocp_acc_pick')}</p>
              )}
              {selected && (
                <DetailPanel
                  item={selected}
                  detail={detailQ.data}
                  loading={detailQ.isFetching}
                  listKind={listKind!}
                  t={t}
                  onLookupSubject={(kind, name, ns) => {
                    setTab('subject')
                    setSubjKind(kind)
                    setSubjName(name)
                    setSubjNs(ns || '')
                  }}
                />
              )}
            </div>
          </div>
        </div>
      )}

      {clusterId && tab === 'subject' && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2 items-end">
            <div>
              <label className="text-[10px] uppercase text-slate-500">{t('ocp_acc_subj_kind')}</label>
              <select
                value={subjKind}
                onChange={(e) => setSubjKind(e.target.value)}
                className="block bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1.5 text-xs text-slate-200"
              >
                <option value="User">User</option>
                <option value="Group">Group</option>
                <option value="ServiceAccount">ServiceAccount</option>
              </select>
            </div>
            <div className="min-w-[180px] flex-1">
              <label className="text-[10px] uppercase text-slate-500">{t('ocp_acc_subj_name')}</label>
              <input
                value={subjName}
                onChange={(e) => setSubjName(e.target.value)}
                className="w-full bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1.5 text-xs text-slate-200 font-mono"
              />
            </div>
            {subjKind === 'ServiceAccount' && (
              <div className="w-56">
                <label className="text-[10px] uppercase text-slate-500">SA namespace</label>
                <select
                  value={subjNs}
                  onChange={(e) => setSubjNs(e.target.value)}
                  className="w-full bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1.5 text-xs text-slate-200 font-mono"
                >
                  <option value="">{t('ocp_acc_ns_pick')}</option>
                  {nsOptions.map((ns) => (
                    <option key={ns} value={ns}>{ns}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
          {subjectQ.isFetching && <p className="text-xs text-slate-500">{t('mon_loading')}</p>}
          {subjectQ.data && (
            <BindingsTable bindings={subjectQ.data.bindings || []} total={subjectQ.data.total} t={t} />
          )}
          {!subjName.trim() && (
            <p className="text-xs text-slate-500">{t('ocp_acc_subj_hint')}</p>
          )}
        </div>
      )}

      {clusterId && tab === 'can_i' && (
        <div className="space-y-3 max-w-xl">
          <p className="text-xs text-slate-500">{t('ocp_acc_can_i_hint')}</p>
          <div className="grid grid-cols-2 gap-2">
            <Field label="verb" value={canVerb} onChange={setCanVerb} />
            <Field label="resource" value={canResource} onChange={setCanResource} />
            <Field label="apiGroup" value={canGroup} onChange={setCanGroup} />
            <div>
              <label className="text-[10px] uppercase text-slate-500">namespace</label>
              <select
                value={namespace}
                onChange={(e) => setNamespace(e.target.value)}
                className="w-full bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1.5 text-xs text-slate-200 font-mono"
              >
                <option value="">{t('ocp_acc_ns_all')}</option>
                {nsOptions.map((ns) => (
                  <option key={ns} value={ns}>{ns}</option>
                ))}
              </select>
            </div>
          </div>
          {canIQ.data && (
            <div className={`rounded-lg border px-3 py-3 text-sm ${
              canIQ.data.allowed
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
                : 'border-rose-500/30 bg-rose-500/10 text-rose-200'
            }`}>
              {canIQ.data.allowed ? t('ocp_acc_allowed') : t('ocp_acc_denied')}
              {canIQ.data.reason ? <p className="text-xs mt-1 opacity-80">{canIQ.data.reason}</p> : null}
            </div>
          )}
        </div>
      )}

      {clusterId && tab === 'idp' && (
        <div className="rounded-xl border border-white/[0.06] bg-cyber-card overflow-hidden">
          {idpQ.data?.ok === false && (
            <p className="p-3 text-xs text-amber-300">{idpQ.data.error}</p>
          )}
          <table className="w-full text-left text-xs">
            <thead className="text-slate-500 border-b border-white/[0.06]">
              <tr>
                <th className="px-3 py-2">{t('ocp_acc_col_name')}</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2">Mapping</th>
              </tr>
            </thead>
            <tbody>
              {(idpQ.data?.providers || []).map((p: any) => (
                <tr key={p.name} className="border-b border-white/[0.03] text-slate-300">
                  <td className="px-3 py-2 font-mono">{p.name}</td>
                  <td className="px-3 py-2">{p.type}</td>
                  <td className="px-3 py-2">{p.mapping_method || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {idpQ.data?.ok && !(idpQ.data.providers || []).length && (
            <p className="p-4 text-xs text-slate-500">{t('ocp_acc_empty')}</p>
          )}
        </div>
      )}
    </div>
  )
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="text-[10px] uppercase text-slate-500">{label}</label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1.5 text-xs text-slate-200 font-mono"
      />
    </div>
  )
}

function RowIcon({ kind }: { kind: string }) {
  const cls = 'text-slate-500 shrink-0'
  if (kind === 'users') return <UserCircle2 size={14} className={cls} />
  if (kind === 'groups') return <UsersRound size={14} className={cls} />
  if (kind === 'identities') return <Fingerprint size={14} className={cls} />
  if (kind.includes('role') && !kind.includes('binding')) return <KeyRound size={14} className={cls} />
  if (kind.includes('binding')) return <Link2 size={14} className={cls} />
  return <Users size={14} className={cls} />
}

function RowHint({ item, kind }: { item: any; kind: string }) {
  if (kind === 'groups') {
    return <div className="text-[10px] text-slate-500 mt-0.5">{item.user_count ?? 0} users</div>
  }
  if (kind === 'users') {
    return (
      <div className="text-[10px] text-slate-500 mt-0.5 truncate pl-5 min-w-0">
        {(item.identities || []).slice(0, 1).join(', ') || item.full_name || '—'}
      </div>
    )
  }
  if (kind.includes('binding')) {
    const rr = item.role_ref || {}
    return (
      <div className="text-[10px] text-slate-500 mt-0.5 truncate">
        → {rr.kind}/{rr.name} · {item.subject_count ?? 0} subjects
      </div>
    )
  }
  if (kind.includes('role')) {
    return <div className="text-[10px] text-slate-500 mt-0.5">{item.rule_count ?? 0} rules</div>
  }
  return null
}

function OverviewPanel({ data, loading, error, t }: any) {
  if (loading) return <p className="text-xs text-slate-500">{t('mon_loading')}</p>
  if (error) return <p className="text-xs text-amber-300">{String(error.message || error)}</p>
  if (!data) return null
  const counts = data.counts || {}
  const cards = [
    ['users', counts.users],
    ['groups', counts.groups],
    ['identities', counts.identities],
    ['clusterroles', counts.clusterroles],
    ['clusterrolebindings', counts.clusterrolebindings],
    ['roles', counts.roles],
    ['rolebindings', counts.rolebindings],
    ['serviceaccounts', counts.serviceaccounts],
  ]
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {cards.map(([k, v]) => (
          <div key={k} className="rounded-lg border border-white/[0.06] bg-cyber-card px-3 py-2">
            <div className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">{k}</div>
            <div className="text-lg font-semibold text-slate-100 mt-0.5 tabular-nums">
              {v == null ? '—' : v}
            </div>
          </div>
        ))}
      </div>
      {Object.keys(data.errors || {}).length > 0 && (
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-[11px] text-amber-200 space-y-1">
          <div className="font-medium flex items-center gap-1"><AlertTriangle size={12} /> {t('ocp_acc_partial')}</div>
          {Object.entries(data.errors).map(([k, v]) => (
            <div key={k} className="font-mono opacity-90">{k}: {String(v)}</div>
          ))}
        </div>
      )}
      <div className="rounded-lg border border-white/[0.06] bg-cyber-card p-3 text-xs text-slate-400">
        <div className="text-[10px] uppercase text-slate-500 mb-1">{t('ocp_acc_token_can')}</div>
        <div>list users: {String(data.token_can?.list_users)}</div>
        <div>list clusterrolebindings: {String(data.token_can?.list_clusterrolebindings)}</div>
        {data.footnote && <p className="mt-2 text-slate-500">{data.footnote}</p>}
      </div>
      {(data.identity_providers || []).length > 0 && (
        <div className="text-xs text-slate-400">
          IdP: {(data.identity_providers as any[]).map((p) => `${p.name} (${p.type})`).join(', ')}
        </div>
      )}
    </div>
  )
}

function DetailPanel({ item, detail, loading, listKind, t, onLookupSubject }: any) {
  const full = detail?.item || item
  return (
    <div className="space-y-2 text-xs min-w-0 max-w-full overflow-x-hidden">
      <div className="font-mono text-sm text-white break-all">{full.name}</div>
      {full.namespace ? <div className="text-slate-500 break-all">ns: {full.namespace}</div> : null}
      {loading && <p className="text-slate-500">{t('mon_loading')}</p>}
      {full.full_name ? <div className="break-words">fullName: {full.full_name}</div> : null}
      {full.identities?.length ? (
        <div className="min-w-0">
          <div className="text-slate-500 mb-1">identities</div>
          <ul className="space-y-1.5 font-mono text-[11px] text-slate-300">
            {full.identities.map((id: string) => (
              <li key={id} className="break-all leading-snug rounded bg-black/20 px-2 py-1.5 border border-white/[0.04]">
                {id}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {full.users?.length ? (
        <div className="min-w-0">
          <div className="text-slate-500 mb-1">members ({full.user_count})</div>
          <ul className="max-h-40 overflow-y-auto space-y-0.5 font-mono text-[11px] text-slate-300">
            {full.users.map((u: string) => (
              <li key={u} className="min-w-0">
                <button
                  type="button"
                  className="hover:text-blue-300 break-all text-left"
                  onClick={() => onLookupSubject('User', u)}
                >
                  {u}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {full.role_ref && (
        <div className="text-slate-300 break-all">
          roleRef: <span className="font-mono">{full.role_ref.kind}/{full.role_ref.name}</span>
        </div>
      )}
      {full.subjects?.length ? (
        <div className="min-w-0">
          <div className="text-slate-500 mb-1">subjects</div>
          <ul className="max-h-40 overflow-y-auto space-y-1 text-[11px]">
            {full.subjects.map((s: any, i: number) => (
              <li key={i} className="min-w-0">
                <button
                  type="button"
                  className="font-mono text-slate-300 hover:text-blue-300 text-left break-all"
                  onClick={() => onLookupSubject(s.kind || 'User', s.name, s.namespace)}
                >
                  {s.kind}/{s.namespace ? `${s.namespace}/` : ''}{s.name}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {full.rules?.length ? (
        <div className="min-w-0">
          <div className="text-slate-500 mb-1">rules ({full.rule_count})</div>
          <ul className="max-h-48 overflow-y-auto space-y-1.5 text-[10px] font-mono text-slate-400">
            {full.rules.slice(0, 40).map((r: any, i: number) => (
              <li key={i} className="border-b border-white/[0.04] pb-1 break-all">
                <div>verbs: {(r.verbs || []).join(', ')}</div>
                <div>resources: {(r.resources || []).join(', ') || '—'}</div>
                <div>apiGroups: {(r.api_groups || []).join(', ') || '""'}</div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {(listKind === 'users' || listKind === 'groups' || listKind === 'serviceaccounts') && (
        <button
          type="button"
          onClick={() => onLookupSubject(
            listKind === 'users' ? 'User' : listKind === 'groups' ? 'Group' : 'ServiceAccount',
            full.name,
            full.namespace,
          )}
          className="mt-2 text-[11px] text-blue-300 hover:underline"
        >
          {t('ocp_acc_show_bindings')}
        </button>
      )}
    </div>
  )
}

function BindingsTable({ bindings, total, t }: { bindings: any[]; total?: number; t: any }) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-cyber-card overflow-hidden">
      <div className="px-3 py-2 text-[10px] uppercase text-slate-500 border-b border-white/[0.04]">
        {t('ocp_acc_bindings')} · {total ?? bindings.length}
      </div>
      <div className="max-h-[480px] overflow-auto">
        <table className="w-full text-left text-[11px]">
          <thead className="sticky top-0 bg-[#0d1422] text-slate-500">
            <tr>
              <th className="px-3 py-1.5">Kind</th>
              <th className="px-3 py-1.5">Name</th>
              <th className="px-3 py-1.5">Namespace</th>
              <th className="px-3 py-1.5">Role</th>
              <th className="px-3 py-1.5">Subjects</th>
            </tr>
          </thead>
          <tbody>
            {bindings.map((b) => (
              <tr key={`${b.kind}:${b.namespace}:${b.name}`} className="border-b border-white/[0.03] text-slate-300">
                <td className="px-3 py-1.5">{b.kind}</td>
                <td className="px-3 py-1.5 font-mono">{b.name}</td>
                <td className="px-3 py-1.5 font-mono">{b.namespace || '—'}</td>
                <td className="px-3 py-1.5 font-mono">{b.role_ref?.kind}/{b.role_ref?.name}</td>
                <td className="px-3 py-1.5">{b.subject_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!bindings.length && <p className="p-4 text-xs text-slate-500">{t('ocp_acc_empty')}</p>}
      </div>
    </div>
  )
}
