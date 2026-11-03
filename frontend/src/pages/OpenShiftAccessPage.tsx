/**
 * OpenShift Access / RBAC.
 *
 * Okuma: openshift modülü yetkilileri (listeler, izin matrisi, etkin yetki, risk paneli).
 * Yazma: YALNIZ Admin ve YALNIZ oluşturma (RoleBinding / ClusterRoleBinding / Role / ClusterRole).
 *        Düzenleme, silme ve kullanıcı/grup yönetimi bu ekranda yoktur.
 */
import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Users, UsersRound, KeyRound, Link2, RefreshCw, AlertTriangle, Fingerprint, UserCircle2,
  Plus, FileCode2, ShieldAlert, Network, Gauge,
} from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { useT } from '../i18n/LocaleProvider'
import { ColumnTable, type TableColumn } from '../components/ColumnTable'
import { useRole } from '../components/insights/insightsKit'
import CreateDialog from '../components/openshift/access/CreateDialog'
import EffectivePanel, { type SubjectSel } from '../components/openshift/access/EffectivePanel'
import PermissionMatrix from '../components/openshift/access/PermissionMatrix'
import RiskPanel from '../components/openshift/access/RiskPanel'
import {
  accessRequest, isManagedByAinew, type AccessKind, type Capabilities, type Matrix,
} from '../components/openshift/access/accessApi'

type Cluster = { id: number; name: string; api_url?: string; status?: string }

type TabId =
  | 'overview' | 'risk'
  | 'users' | 'groups' | 'serviceaccounts' | 'identities' | 'idp'
  | 'clusterroles' | 'roles'
  | 'clusterrolebindings' | 'rolebindings'
  | 'effective' | 'can_i'

type TabDef = { id: TabId; labelKey: Parameters<ReturnType<typeof useT>>[0]; kind?: string; createKind?: AccessKind }
type GroupDef = { id: string; labelKey: TabDef['labelKey']; icon: React.ReactNode; tabs: TabDef[] }

const GROUPS: GroupDef[] = [
  { id: 'general', labelKey: 'ocp_rb_grp_general', icon: <Gauge size={13} />, tabs: [
    { id: 'overview', labelKey: 'ocp_acc_tab_overview' },
    { id: 'risk', labelKey: 'ocp_rb_tab_risk' },
  ] },
  { id: 'identities', labelKey: 'ocp_rb_grp_identities', icon: <Users size={13} />, tabs: [
    { id: 'users', labelKey: 'ocp_acc_tab_users', kind: 'users' },
    { id: 'groups', labelKey: 'ocp_acc_tab_groups', kind: 'groups' },
    { id: 'serviceaccounts', labelKey: 'ocp_acc_tab_sa', kind: 'serviceaccounts' },
    { id: 'identities', labelKey: 'ocp_acc_tab_identities', kind: 'identities' },
    { id: 'idp', labelKey: 'ocp_acc_tab_idp' },
  ] },
  { id: 'roles', labelKey: 'ocp_rb_grp_roles', icon: <KeyRound size={13} />, tabs: [
    { id: 'clusterroles', labelKey: 'ocp_acc_tab_clusterroles', kind: 'clusterroles', createKind: 'ClusterRole' },
    { id: 'roles', labelKey: 'ocp_acc_tab_roles', kind: 'roles', createKind: 'Role' },
  ] },
  { id: 'bindings', labelKey: 'ocp_rb_grp_bindings', icon: <Link2 size={13} />, tabs: [
    { id: 'clusterrolebindings', labelKey: 'ocp_acc_tab_crb', kind: 'clusterrolebindings', createKind: 'ClusterRoleBinding' },
    { id: 'rolebindings', labelKey: 'ocp_acc_tab_rolebindings', kind: 'rolebindings', createKind: 'RoleBinding' },
  ] },
  { id: 'tools', labelKey: 'ocp_rb_grp_tools', icon: <Network size={13} />, tabs: [
    { id: 'effective', labelKey: 'ocp_rb_tab_effective' },
    { id: 'can_i', labelKey: 'ocp_acc_tab_can_i' },
  ] },
]
const ALL_TABS = GROUPS.flatMap(g => g.tabs)

const fmtDate = (s?: string) => (s ? new Date(s).toLocaleDateString() : '—')
const subjLabel = (s: any) => `${s.kind}/${s.namespace ? `${s.namespace}/` : ''}${s.name}`

export default function OpenShiftAccessPage() {
  const t = useT()
  const { isAdmin } = useRole()
  const qc = useQueryClient()
  const [clusterId, setClusterId] = useState<number | null>(null)
  const [tab, setTab] = useState<TabId>('overview')
  const [namespace, setNamespace] = useState('')
  const [selected, setSelected] = useState<any | null>(null)
  const [managedOnly, setManagedOnly] = useState(false)
  const [subject, setSubject] = useState<SubjectSel>({ kind: 'User', name: '', ns: '' })
  const [canVerb, setCanVerb] = useState('list')
  const [canResource, setCanResource] = useState('users')
  const [canGroup, setCanGroup] = useState('user.openshift.io')
  const [createKind, setCreateKind] = useState<AccessKind | null>(null)

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
      const p = new URLSearchParams({ cluster_id: String(clusterId), include_system: 'true', page_size: '1000', page: '1' })
      const r = await fetch(`${API_BASE_URL}/openshift/projects?${p}`)
      if (!r.ok) return []
      const body = await r.json()
      const names = (body?.projects || []).map((x: any) => x.name).filter(Boolean)
      return Array.from(new Set(names as string[])).sort((a, b) => a.localeCompare(b))
    },
  })

  useEffect(() => {
    if (!clusters.length) { setClusterId(null); return }
    if (!clusterId || !clusters.find(c => c.id === clusterId)) setClusterId(clusters[0].id)
  }, [clusters, clusterId])

  const capsQ = useQuery<Capabilities>({
    queryKey: ['ocp-access-caps', clusterId],
    enabled: !!clusterId,
    staleTime: 60_000,
    queryFn: () => accessRequest<Capabilities>(clusterId!, 'capabilities'),
  })
  const caps = capsQ.data
  const canWrite = isAdmin && !!caps?.can_write

  const overviewQ = useQuery({
    queryKey: ['ocp-access-overview', clusterId],
    enabled: !!clusterId && tab === 'overview',
    queryFn: () => accessRequest<any>(clusterId!, 'overview'),
  })

  const tabDef = ALL_TABS.find(x => x.id === tab)!
  const listKind = tabDef.kind
  const namespaced = ['roles', 'rolebindings', 'serviceaccounts'].includes(listKind || '')

  const useList = (kind: string | undefined, ns: string, enabled: boolean) => useQuery<any>({
    queryKey: ['ocp-access-list', clusterId, kind, ns],
    enabled: !!clusterId && !!kind && enabled,
    staleTime: 30_000,
    queryFn: () => accessRequest<any>(clusterId!, 'list', { params: { kind: kind!, namespace: ns || undefined, limit: '20000' } }),
  })
  const listQ = useList(listKind, namespaced ? namespace : '', true)
  const effTab = tab === 'effective'
  const usersQ = useList('users', '', effTab)
  const groupsQ = useList('groups', '', effTab)

  const dialogOpen = createKind !== null
  const crQ = useList('clusterroles', '', dialogOpen)
  const rQ = useList('roles', '', dialogOpen)

  const canIQ = useQuery({
    queryKey: ['ocp-access-can-i', clusterId, canVerb, canResource, canGroup, namespace],
    enabled: !!clusterId && tab === 'can_i',
    queryFn: () => accessRequest<any>(clusterId!, 'can-i', {
      params: { verb: canVerb, resource: canResource, api_group: canGroup, namespace: namespace || undefined },
    }),
  })

  const idpQ = useQuery({
    queryKey: ['ocp-access-idp', clusterId],
    enabled: !!clusterId && tab === 'idp' && isAdmin,
    queryFn: () => accessRequest<any>(clusterId!, 'identity-providers'),
  })
  const ovForIdp = useQuery({
    queryKey: ['ocp-access-overview', clusterId],
    enabled: !!clusterId && tab === 'idp' && !isAdmin,
    queryFn: () => accessRequest<any>(clusterId!, 'overview'),
  })

  const gotoSubject = (kind: string, name: string, ns?: string) => {
    setSubject({ kind, name, ns: ns || '' })
    setTab('effective')
    setSelected(null)
  }

  const refreshAll = async () => {
    if (!clusterId) return
    await accessRequest(clusterId, 'overview', { params: { refresh: 'true' } }).catch(() => undefined)
    qc.invalidateQueries({ queryKey: ['ocp-access-list'] })
    qc.invalidateQueries({ queryKey: ['ocp-access-overview'] })
    qc.invalidateQueries({ queryKey: ['ocp-access-risks'] })
    qc.invalidateQueries({ queryKey: ['ocp-access-effective'] })
  }

  const columns = useMemo<TableColumn<any>[]>(() => columnsFor(listKind || '', t), [listKind, t])
  const rawItems: any[] = listQ.data?.items || []
  const items = useMemo(() => (managedOnly ? rawItems.filter(i => isManagedByAinew(i.labels)) : rawItems), [rawItems, managedOnly])
  const hasManaged = useMemo(() => rawItems.some(i => isManagedByAinew(i.labels)), [rawItems])
  const switchTab = (id: TabId) => { setTab(id); setSelected(null) }

  return (
    <div className="px-4 pt-3 pb-6 max-w-[1800px] mx-auto space-y-4 w-full">
      <div className="flex flex-wrap items-center justify-end gap-3">
        <div className="flex items-center gap-2">
          <button type="button" onClick={refreshAll} title={t('ocp_rb_refresh')}
            className="p-2 rounded-md text-slate-400 hover:text-white hover:bg-white/[0.06]">
            <RefreshCw size={14} className={listQ.isFetching || overviewQ.isFetching ? 'animate-spin' : ''} />
          </button>
          <select
            value={clusterId ?? ''}
            onChange={e => { setClusterId(Number(e.target.value) || null); setSelected(null); setNamespace('') }}
            className="bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1.5 text-xs text-slate-200"
          >
            {!clusters.length && <option value="">{t('ocp_acc_no_cluster')}</option>}
            {clusters.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
      </div>

      <nav className="flex flex-wrap items-center gap-x-1 gap-y-2 border-b border-white/[0.06] pb-2" aria-label="RBAC">
        {GROUPS.map((g, gi) => (
          <div key={g.id} className={`flex items-center gap-1 ${gi > 0 ? 'pl-3 ml-2 border-l border-white/[0.08]' : ''}`}>
            <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider text-slate-500 font-bold mr-1">
              {g.icon}{t(g.labelKey)}
            </span>
            {g.tabs.map(tb => (
              <button
                key={tb.id}
                type="button"
                data-testid={`tab-${tb.id}`}
                onClick={() => switchTab(tb.id)}
                className={`px-2.5 py-1 rounded-md text-[11px] font-medium whitespace-nowrap transition-colors ${
                  tab === tb.id
                    ? 'bg-blue-600/30 text-blue-200 border border-blue-500/40'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-white/[0.04]'
                }`}
              >
                {t(tb.labelKey)}
              </button>
            ))}
          </div>
        ))}
      </nav>

      {!clusterId && (
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4 text-sm text-amber-200">{t('ocp_acc_no_cluster')}</div>
      )}

      {clusterId && tab === 'overview' && (
        <OverviewPanel data={overviewQ.data} loading={overviewQ.isFetching} error={overviewQ.error as Error | null} t={t}
          onRisk={() => switchTab('risk')} />
      )}

      {clusterId && tab === 'risk' && <RiskPanel clusterId={clusterId} onSubject={gotoSubject} />}

      {clusterId && listKind && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2 items-end">
            {namespaced && (
              <div className="w-56">
                <label className="text-[10px] uppercase text-slate-500">{t('ocp_acc_namespace')}</label>
                <select
                  value={namespace}
                  onChange={e => { setNamespace(e.target.value); setSelected(null) }}
                  className="w-full bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1.5 text-xs text-slate-200 font-mono"
                >
                  <option value="">{t('ocp_acc_ns_all')}</option>
                  {nsOptions.map(ns => <option key={ns} value={ns}>{ns}</option>)}
                </select>
              </div>
            )}
            {hasManaged && (
              <label className="inline-flex items-center gap-1.5 text-[11px] text-slate-400 pb-1.5">
                <input type="checkbox" checked={managedOnly} onChange={e => setManagedOnly(e.target.checked)} data-testid="managed-only" />
                {t('ocp_rb_managed_filter')}
              </label>
            )}
            <div className="ml-auto">
              {isAdmin && tabDef.createKind && (
                <button
                  type="button"
                  data-testid="btn-create"
                  disabled={!caps?.kinds[tabDef.createKind]?.allowed}
                  title={caps?.kinds[tabDef.createKind]?.allowed ? '' : (caps?.kinds[tabDef.createKind]?.reason || t('ocp_rb_cap_denied'))}
                  onClick={() => setCreateKind(tabDef.createKind!)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <Plus size={13} /> {t('ocp_rb_new_kind', { kind: tabDef.createKind })}
                </button>
              )}
            </div>
          </div>

          {listQ.data && listQ.data.ok === false && (
            <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <span>{listQ.data.error}</span>
            </div>
          )}
          {listQ.data?.truncated && <p className="text-[11px] text-amber-300">{t('ocp_rb_truncated')}</p>}

          <div className={`grid gap-3 items-start ${selected ? 'xl:grid-cols-[minmax(0,1fr)_minmax(0,480px)]' : ''}`}>
            <ColumnTable<any>
              testId="access-list"
              rowTestId="access-row"
              rows={items}
              columns={columns}
              rowKey={r => `${r.namespace}:${r.name}:${r.uid || ''}`}
              searchPlaceholder={t('ocp_acc_search_ph')}
              empty={t('ocp_acc_empty')}
              loading={listQ.isLoading}
              error={listQ.error ? (listQ.error as Error).message : null}
              defaultSort={{ id: 'name', dir: 'asc' }}
              maxHeightClass="max-h-[min(65vh,640px)]"
              pageSize={100}
              onRowClick={r => setSelected(r)}
              rowClass={r => (selected && selected.name === r.name && selected.namespace === r.namespace ? 'bg-blue-600/15' : '')}
              countLabel={(shown, total) => t('ocp_rb_count', { shown, total })}
            />
            {selected && (
              <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-3 min-w-0 overflow-hidden" data-testid="detail-pane">
                <DetailPanel
                  clusterId={clusterId}
                  item={selected}
                  listKind={listKind}
                  isAdmin={isAdmin}
                  t={t}
                  onClose={() => setSelected(null)}
                  onLookupSubject={gotoSubject}
                />
              </div>
            )}
          </div>
        </div>
      )}

      {clusterId && tab === 'effective' && (
        <EffectivePanel
          clusterId={clusterId}
          subject={subject}
          onChange={setSubject}
          nsOptions={nsOptions}
          suggestions={{
            users: (usersQ.data?.items || []).map((u: any) => u.name),
            groups: (groupsQ.data?.items || []).map((g: any) => g.name),
          }}
        />
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
                onChange={e => setNamespace(e.target.value)}
                className="w-full bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1.5 text-xs text-slate-200 font-mono"
              >
                <option value="">{t('ocp_acc_ns_all')}</option>
                {nsOptions.map(ns => <option key={ns} value={ns}>{ns}</option>)}
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
        <IdpTable
          providers={isAdmin ? idpQ.data?.providers : ovForIdp.data?.identity_providers}
          error={isAdmin ? (idpQ.data?.ok === false ? idpQ.data.error : null) : ovForIdp.data?.identity_providers_error}
          full={isAdmin}
          t={t}
        />
      )}

      {createKind && clusterId && caps && (
        <CreateDialog
          clusterId={clusterId}
          caps={caps}
          initialKind={createKind}
          nsOptions={nsOptions}
          clusterRoles={(crQ.data?.items || []).map((r: any) => r.name)}
          roles={(rQ.data?.items || []).map((r: any) => ({ namespace: r.namespace, name: r.name }))}
          onClose={() => setCreateKind(null)}
          onCreated={refreshAll}
        />
      )}
    </div>
  )
}

function columnsFor(kind: string, t: ReturnType<typeof useT>): TableColumn<any>[] {
  const name: TableColumn<any> = {
    id: 'name', label: t('ocp_acc_col_name'), text: r => r.name,
    render: r => (
      <span className="inline-flex items-center gap-1.5 min-w-0">
        <RowIcon kind={kind} />
        <span className="font-mono break-all">{r.name}</span>
        {isManagedByAinew(r.labels) && (
          <span className="shrink-0 px-1 rounded-sm bg-blue-500/15 text-blue-300 text-[9px] uppercase" title={r.annotations?.['ainew.io/created-by'] || ''}>ainew</span>
        )}
      </span>
    ),
  }
  const ns: TableColumn<any> = { id: 'namespace', label: t('ocp_rb_col_ns'), text: r => r.namespace, render: r => <span className="font-mono text-slate-400">{r.namespace || '—'}</span> }
  const created: TableColumn<any> = { id: 'created', label: t('ocp_rb_col_created'), text: r => r.created || '', render: r => <span className="text-slate-500">{fmtDate(r.created)}</span> }
  const role: TableColumn<any> = {
    id: 'role', label: t('ocp_rb_col_role'), text: r => `${r.role_ref?.kind}/${r.role_ref?.name}`,
    render: r => <span className="font-mono">{r.role_ref?.kind}/{r.role_ref?.name}</span>,
  }
  const subjects: TableColumn<any> = {
    id: 'subjects', label: t('ocp_rb_col_subjects'),
    text: r => (r.subjects || []).map(subjLabel).join(' '), num: r => r.subject_count ?? 0,
    render: r => (
      <span className="font-mono text-slate-400" title={(r.subjects || []).map(subjLabel).join('\n')}>
        {(r.subjects || []).slice(0, 2).map(subjLabel).join(', ')}
        {(r.subject_count ?? 0) > 2 ? ` +${r.subject_count - 2}` : ''}
      </span>
    ),
  }
  switch (kind) {
    case 'users':
      return [name,
        { id: 'full', label: t('ocp_rb_col_fullname'), text: r => r.full_name || '' },
        { id: 'identity', label: t('ocp_rb_col_identity'), text: r => (r.identities || []).join(' '), render: r => <span className="font-mono text-slate-400">{(r.identities || [])[0] || '—'}</span> },
        created]
    case 'groups':
      return [name, { id: 'members', label: t('ocp_rb_col_members'), text: r => String(r.user_count ?? 0), num: r => r.user_count ?? 0 }, created]
    case 'identities':
      return [name,
        { id: 'provider', label: t('ocp_rb_col_provider'), text: r => r.provider_name || '' },
        { id: 'user', label: t('ocp_rb_col_user'), text: r => r.user_name || '', render: r => <span className="font-mono">{r.user_name || '—'}</span> },
        created]
    case 'serviceaccounts':
      return [name, ns, created]
    case 'clusterroles':
      return [name, { id: 'rules', label: t('ocp_rb_col_rules'), text: r => String(r.rule_count ?? 0), num: r => r.rule_count ?? 0 }, created]
    case 'roles':
      return [name, ns, { id: 'rules', label: t('ocp_rb_col_rules'), text: r => String(r.rule_count ?? 0), num: r => r.rule_count ?? 0 }, created]
    case 'clusterrolebindings':
      return [name, role, subjects, created]
    case 'rolebindings':
      return [name, ns, role, subjects, created]
    default:
      return [name]
  }
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="text-[10px] uppercase text-slate-500">{label}</label>
      <input
        value={value}
        onChange={e => onChange(e.target.value)}
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
  if (kind.includes('binding')) return <Link2 size={14} className={cls} />
  if (kind.includes('role')) return <KeyRound size={14} className={cls} />
  return <Users size={14} className={cls} />
}

function IdpTable({ providers, error, full, t }: { providers?: any[]; error?: string | null; full: boolean; t: any }) {
  const cols: TableColumn<any>[] = [
    { id: 'name', label: t('ocp_acc_col_name'), text: p => p.name || '', render: p => <span className="font-mono">{p.name}</span> },
    { id: 'type', label: t('ocp_rb_col_type'), text: p => p.type || '' },
    ...(full ? [{ id: 'mapping', label: t('ocp_rb_col_mapping'), text: (p: any) => p.mapping_method || '' } as TableColumn<any>] : []),
  ]
  return (
    <div className="space-y-2">
      {!full && <p className="text-[11px] text-slate-500" data-testid="idp-limited">{t('ocp_rb_idp_limited')}</p>}
      {error && <p className="text-xs text-amber-300">{error}</p>}
      <ColumnTable<any> testId="idp-table" rows={providers || []} columns={cols} rowKey={p => p.name}
        searchPlaceholder={t('ocp_acc_search_ph')} empty={t('ocp_acc_empty')} hideSearch />
    </div>
  )
}

function OverviewPanel({ data, loading, error, t, onRisk }: any) {
  if (loading && !data) return <p className="text-xs text-slate-500">{t('mon_loading')}</p>
  if (error) return <p className="text-xs text-amber-300">{String(error.message || error)}</p>
  if (!data) return null
  const counts = data.counts || {}
  const cards = ['users', 'groups', 'identities', 'clusterroles', 'clusterrolebindings', 'roles', 'rolebindings', 'serviceaccounts']
  const rs = data.risk_summary
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {cards.map(k => (
          <div key={k} className="rounded-lg border border-white/[0.06] bg-cyber-card px-3 py-2">
            <div className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">{k}</div>
            <div className="text-lg font-semibold text-slate-100 mt-0.5 tabular-nums">{counts[k] == null ? '—' : counts[k]}</div>
          </div>
        ))}
      </div>
      {rs && (
        <button type="button" onClick={onRisk} data-testid="overview-risk"
          className="w-full text-left rounded-lg border border-white/[0.06] bg-cyber-card px-3 py-2 flex flex-wrap items-center gap-4 hover:border-blue-500/30">
          <span className="inline-flex items-center gap-1.5 text-xs text-slate-300"><ShieldAlert size={14} className="text-amber-400" />{t('ocp_rb_tab_risk')}</span>
          <span className={`text-xs ${rs.cluster_admin_holders ? 'text-red-300' : 'text-emerald-300'}`}>{t('ocp_rb_card_ca')}: <b>{rs.cluster_admin_holders}</b></span>
          <span className={`text-xs ${rs.wildcard_roles ? 'text-amber-300' : 'text-emerald-300'}`}>{t('ocp_rb_card_wild')}: <b>{rs.wildcard_roles}</b></span>
          <span className={`text-xs ${rs.broad_group_grants ? 'text-red-300' : 'text-emerald-300'}`}>{t('ocp_rb_card_broad')}: <b>{rs.broad_group_grants}</b></span>
          <span className="text-xs text-slate-400">{t('ocp_rb_card_orphan_b')}: <b>{rs.orphan_bindings}</b></span>
        </button>
      )}
      {Object.keys(data.errors || {}).length > 0 && (
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-[11px] text-amber-200 space-y-1">
          <div className="font-medium flex items-center gap-1"><AlertTriangle size={12} /> {t('ocp_acc_partial')}</div>
          {Object.entries(data.errors).map(([k, v]) => <div key={k} className="font-mono opacity-90">{k}: {String(v)}</div>)}
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
          IdP: {(data.identity_providers as any[]).map(p => `${p.name} (${p.type})`).join(', ')}
        </div>
      )}
    </div>
  )
}

function DetailPanel({ clusterId, item, listKind, isAdmin, t, onClose, onLookupSubject }: {
  clusterId: number; item: any; listKind: string; isAdmin: boolean; t: any
  onClose: () => void; onLookupSubject: (kind: string, name: string, ns?: string) => void
}) {
  const [showYaml, setShowYaml] = useState(false)
  const [showRefMatrix, setShowRefMatrix] = useState(false)
  const isRole = listKind === 'roles' || listKind === 'clusterroles'
  const isBinding = listKind.includes('binding')
  const detailQ = useQuery({
    queryKey: ['ocp-access-get', clusterId, listKind, item.name, item.namespace],
    queryFn: () => accessRequest<any>(clusterId, 'get', { params: { kind: listKind, name: item.name, namespace: item.namespace || undefined } }),
  })
  const full = detailQ.data?.item || item
  const matrixQ = useQuery({
    queryKey: ['ocp-access-matrix', clusterId, listKind, item.name, item.namespace],
    enabled: isRole,
    queryFn: () => accessRequest<{ matrix: Matrix }>(clusterId, 'matrix', { params: { kind: listKind, name: item.name, namespace: item.namespace || undefined } }),
  })
  const ref = full.role_ref
  const refKind = ref?.kind === 'ClusterRole' ? 'clusterroles' : 'roles'
  const refMatrixQ = useQuery({
    queryKey: ['ocp-access-matrix', clusterId, refKind, ref?.name, full.namespace],
    enabled: isBinding && showRefMatrix && !!ref?.name,
    queryFn: () => accessRequest<{ matrix: Matrix }>(clusterId, 'matrix', { params: { kind: refKind, name: ref.name, namespace: refKind === 'roles' ? full.namespace : undefined } }),
  })
  const yamlQ = useQuery({
    queryKey: ['ocp-access-yaml', clusterId, listKind, item.name, item.namespace],
    enabled: isAdmin && showYaml,
    queryFn: () => accessRequest<{ yaml: string }>(clusterId, 'yaml', { params: { kind: listKind, name: item.name, namespace: item.namespace || undefined } }),
  })
  const ann = full.annotations || {}
  const subjKind = listKind === 'users' ? 'User' : listKind === 'groups' ? 'Group' : listKind === 'serviceaccounts' ? 'ServiceAccount' : ''

  return (
    <div className="space-y-3 text-xs min-w-0 max-w-full">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-mono text-sm text-white break-all">{full.name}</div>
          {full.namespace ? <div className="text-slate-500 break-all">ns: {full.namespace}</div> : null}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {isAdmin && (
            <button type="button" data-testid="btn-yaml" onClick={() => setShowYaml(v => !v)}
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm border text-[11px] ${showYaml ? 'border-blue-500/40 text-blue-200' : 'border-white/[0.1] text-slate-400 hover:text-white'}`}>
              <FileCode2 size={11} />{t('ocp_rb_yaml_btn')}
            </button>
          )}
          <button type="button" onClick={onClose} className="text-slate-500 hover:text-white text-lg leading-none">&times;</button>
        </div>
      </div>
      {detailQ.isFetching && <p className="text-slate-500">{t('mon_loading')}</p>}
      {isManagedByAinew(full.labels) && (
        <div className="text-[11px] text-blue-300/90">
          ainew · {ann['ainew.io/created-by'] || '—'} · {ann['ainew.io/created-at'] ? new Date(ann['ainew.io/created-at']).toLocaleString() : ''}
          {ann['ainew.io/description'] ? <div className="text-slate-400">{ann['ainew.io/description']}</div> : null}
        </div>
      )}

      {showYaml && isAdmin && (
        <div className="space-y-1" data-testid="yaml-pane">
          <div className="flex items-center justify-between text-[11px] text-slate-500">
            <span>{t('ocp_rb_yaml_title')}</span>
            {yamlQ.data && <button type="button" className="hover:text-white" onClick={() => navigator.clipboard?.writeText(yamlQ.data!.yaml)}>{t('ocp_rb_copy')}</button>}
          </div>
          {yamlQ.isFetching && <p className="text-slate-500">{t('mon_loading')}</p>}
          {yamlQ.error && <p className="text-amber-300">{(yamlQ.error as Error).message}</p>}
          {yamlQ.data && <pre className="bg-black/40 border border-white/[0.06] rounded-md p-2 font-mono text-[11px] text-slate-200 max-h-80 overflow-auto whitespace-pre-wrap break-all">{yamlQ.data.yaml}</pre>}
        </div>
      )}

      {full.full_name ? <div className="wrap-break-word">fullName: {full.full_name}</div> : null}
      {full.identities?.length ? (
        <div className="min-w-0">
          <div className="text-slate-500 mb-1">identities</div>
          <ul className="space-y-1 font-mono text-[11px] text-slate-300">
            {full.identities.map((id: string) => <li key={id} className="break-all rounded-sm bg-black/20 px-2 py-1 border border-white/[0.04]">{id}</li>)}
          </ul>
        </div>
      ) : null}
      {full.users?.length ? (
        <div className="min-w-0">
          <div className="text-slate-500 mb-1">members ({full.user_count})</div>
          <ul className="max-h-40 overflow-y-auto space-y-0.5 font-mono text-[11px] text-slate-300">
            {full.users.map((u: string) => (
              <li key={u}><button type="button" className="hover:text-blue-300 break-all text-left" onClick={() => onLookupSubject('User', u)}>{u}</button></li>
            ))}
          </ul>
        </div>
      ) : null}
      {ref && (
        <div className="text-slate-300 break-all space-y-1">
          <div>{t('ocp_rb_roleref')}: <span className="font-mono">{ref.kind}/{ref.name}</span></div>
          <button type="button" className="text-blue-300 hover:underline" onClick={() => setShowRefMatrix(v => !v)}>{t('ocp_rb_role_matrix_btn')}</button>
          {showRefMatrix && refMatrixQ.data && <PermissionMatrix matrix={refMatrixQ.data.matrix} maxHeight="max-h-64" />}
          {showRefMatrix && refMatrixQ.error && <p className="text-amber-300">{(refMatrixQ.error as Error).message}</p>}
        </div>
      )}
      {full.subjects?.length ? (
        <div className="min-w-0">
          <div className="text-slate-500 mb-1">subjects ({full.subject_count})</div>
          <ul className="max-h-40 overflow-y-auto space-y-1 text-[11px]">
            {full.subjects.map((s: any, i: number) => (
              <li key={i}>
                <button type="button" className="font-mono text-slate-300 hover:text-blue-300 text-left break-all"
                  onClick={() => onLookupSubject(s.kind || 'User', s.name, s.namespace)}>{subjLabel(s)}</button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {isRole && (
        <div className="min-w-0">
          <div className="text-slate-500 mb-1">{t('ocp_rb_matrix_title')} ({full.rule_count ?? 0})</div>
          {matrixQ.isFetching && <p className="text-slate-500">{t('mon_loading')}</p>}
          {matrixQ.data && <PermissionMatrix matrix={matrixQ.data.matrix} />}
        </div>
      )}
      {subjKind && (
        <button type="button" onClick={() => onLookupSubject(subjKind, full.name, full.namespace)} className="text-[11px] text-blue-300 hover:underline">
          {t('ocp_rb_effective_btn')}
        </button>
      )}
    </div>
  )
}

