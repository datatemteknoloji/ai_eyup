import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { useT } from '../../../i18n/LocaleProvider'
import { ColumnTable, type TableColumn } from '../../ColumnTable'
import { accessRequest, type Matrix } from './accessApi'
import PermissionMatrix from './PermissionMatrix'

export type SubjectSel = { kind: string; name: string; ns: string }

/** Etkin yetki: kullanıcı/grup/SA → doğrudan + grup üyeliği ile gelen binding'ler ve birleşik izin matrisleri. */
export default function EffectivePanel({ clusterId, subject, onChange, nsOptions, suggestions }: {
  clusterId: number
  subject: SubjectSel
  onChange: (s: SubjectSel) => void
  nsOptions: string[]
  suggestions: { users: string[]; groups: string[] }
}) {
  const t = useT()
  const [nsView, setNsView] = useState('')
  const enabled = !!subject.name.trim() && (subject.kind !== 'ServiceAccount' || !!subject.ns)
  const q = useQuery({
    queryKey: ['ocp-access-effective', clusterId, subject.kind, subject.name, subject.ns],
    enabled,
    queryFn: () => accessRequest<any>(clusterId, 'effective', {
      params: { subject_kind: subject.kind, subject_name: subject.name.trim(), subject_namespace: subject.ns },
    }),
  })
  const d = q.data
  const list = subject.kind === 'Group' ? suggestions.groups : subject.kind === 'User' ? suggestions.users : []
  const nsKeys = Object.keys(d?.namespace_matrices || {})
  const cols: TableColumn<any>[] = [
    { id: 'binding', label: t('ocp_rb_col_binding'), text: g => `${g.binding_kind} ${g.namespace}/${g.binding}`,
      render: g => <span className="font-mono">{g.binding_kind === 'ClusterRoleBinding' ? 'CRB' : 'RB'} · {g.namespace ? `${g.namespace}/` : ''}{g.binding}</span> },
    { id: 'role', label: t('ocp_rb_col_role'), text: g => `${g.role_kind}/${g.role}`,
      render: g => <span className={`font-mono ${g.role_found ? '' : 'text-amber-400'}`}>{g.role_kind}/{g.role}</span> },
    { id: 'scope', label: t('ocp_rb_col_scope'), text: g => (g.scope === 'cluster' ? 'cluster' : g.namespace) },
    { id: 'via', label: t('ocp_rb_col_via'), text: g => g.via, render: g => g.via === 'direct' ? t('ocp_rb_eff_direct') : <span className="font-mono">{g.via}</span> },
  ]
  return (
    <div className="space-y-3" data-testid="effective-panel">
      <p className="text-xs text-slate-500">{t('ocp_rb_eff_hint')}</p>
      <div className="flex flex-wrap gap-2 items-end">
        <div>
          <label className="text-[10px] uppercase text-slate-500">{t('ocp_acc_subj_kind')}</label>
          <select value={subject.kind} onChange={e => onChange({ kind: e.target.value, name: '', ns: '' })}
            className="block bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1.5 text-xs text-slate-200">
            <option>User</option><option>Group</option><option>ServiceAccount</option>
          </select>
        </div>
        <div className="min-w-[200px] flex-1">
          <label className="text-[10px] uppercase text-slate-500">{t('ocp_acc_subj_name')}</label>
          <input list="ocp-eff-names" value={subject.name} onChange={e => onChange({ ...subject, name: e.target.value })}
            data-testid="effective-name"
            className="w-full bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1.5 text-xs text-slate-200 font-mono" />
          <datalist id="ocp-eff-names">{list.slice(0, 500).map(n => <option key={n} value={n} />)}</datalist>
        </div>
        {subject.kind === 'ServiceAccount' && (
          <div className="w-56">
            <label className="text-[10px] uppercase text-slate-500">{t('ocp_rb_f_subj_ns')}</label>
            <select value={subject.ns} onChange={e => onChange({ ...subject, ns: e.target.value })}
              className="w-full bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1.5 text-xs text-slate-200 font-mono">
              <option value="">{t('ocp_acc_ns_pick')}</option>
              {nsOptions.map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
        )}
      </div>
      {!enabled && <p className="text-xs text-slate-500">{t('ocp_acc_subj_hint')}</p>}
      {q.isFetching && <p className="text-xs text-slate-500">{t('ocp_rb_loading')}</p>}
      {q.error && <p className="text-xs text-amber-300">{(q.error as Error).message}</p>}
      {d && (
        <div className="space-y-3">
          {d.is_cluster_admin && (
            <div className="flex items-center gap-1.5 rounded-md border border-red-500/30 bg-red-500/10 px-2 py-1.5 text-xs text-red-300" data-testid="effective-ca">
              <AlertTriangle size={13} /> {t('ocp_rb_eff_ca')}
            </div>
          )}
          {d.member_groups?.length > 0 && (
            <div className="text-xs text-slate-400">
              <span className="text-slate-500">{t('ocp_rb_eff_groups')}: </span>
              {d.member_groups.map((g: string) => (
                <button key={g} type="button" onClick={() => onChange({ kind: 'Group', name: g, ns: '' })}
                  className="mr-1.5 px-1.5 py-0.5 rounded-sm bg-white/[0.05] font-mono text-[11px] hover:text-blue-300">{g}</button>
              ))}
            </div>
          )}
          {d.missing_roles?.length > 0 && (
            <p className="text-xs text-amber-300">{t('ocp_rb_eff_missing')}: <span className="font-mono">{d.missing_roles.join(', ')}</span></p>
          )}
          <div>
            <h3 className="text-xs font-semibold text-slate-300 mb-1.5">{t('ocp_rb_eff_grants')} ({d.grant_count})</h3>
            <ColumnTable<any> testId="effective-grants" rows={d.grants || []} columns={cols}
              rowKey={g => `${g.binding_kind}:${g.namespace}:${g.binding}:${g.via}`} searchPlaceholder={t('ocp_acc_search_ph')}
              empty={t('ocp_rb_eff_none')} pageSize={10} maxHeightClass="max-h-72" />
          </div>
          <div>
            <h3 className="text-xs font-semibold text-slate-300 mb-1.5">{t('ocp_rb_eff_cluster')}</h3>
            <PermissionMatrix matrix={d.cluster_matrix as Matrix} />
          </div>
          {nsKeys.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-slate-300 mb-1.5 flex items-center gap-2">
                {t('ocp_rb_eff_ns')}
                <select value={nsView || nsKeys[0]} onChange={e => setNsView(e.target.value)}
                  className="bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-0.5 text-[11px] text-slate-200 font-mono">
                  {nsKeys.map(k => <option key={k} value={k}>{k}</option>)}
                </select>
              </h3>
              <PermissionMatrix matrix={d.namespace_matrices[nsView && nsKeys.includes(nsView) ? nsView : nsKeys[0]] as Matrix} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
