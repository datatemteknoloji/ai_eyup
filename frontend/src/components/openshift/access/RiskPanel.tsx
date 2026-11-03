import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, RefreshCw, ShieldAlert } from 'lucide-react'
import { useT } from '../../../i18n/LocaleProvider'
import { ColumnTable, type TableColumn } from '../../ColumnTable'
import { accessRequest } from './accessApi'

type Summary = {
  cluster_admin_holders: number; wildcard_roles: number; broad_group_grants: number
  orphan_bindings: number; orphan_subjects: number
}

const SEV_CLS: Record<string, string> = {
  critical: 'bg-red-500/15 text-red-300 border-red-500/30',
  warning: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  info: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
}
const SEV_RANK: Record<string, number> = { critical: 3, warning: 2, info: 1 }

function Sev({ s }: { s: string }) {
  return <span className={`px-1.5 py-0.5 rounded-sm border text-[10px] uppercase ${SEV_CLS[s] || SEV_CLS.info}`}>{s}</span>
}

/** Risk paneli: cluster-admin sahipleri, wildcard roller, geniş grup yetkileri, yetim binding/özneler. */
export default function RiskPanel({ clusterId, onSubject }: {
  clusterId: number
  onSubject?: (kind: string, name: string, ns?: string) => void
}) {
  const t = useT()
  const qc = useQueryClient()
  const [section, setSection] = useState<'ca' | 'wild' | 'broad' | 'orphan'>('ca')
  const q = useQuery({
    queryKey: ['ocp-access-risks', clusterId],
    queryFn: () => accessRequest<any>(clusterId, 'risks'),
    staleTime: 30_000,
  })
  const refresh = async () => {
    await accessRequest(clusterId, 'overview', { params: { refresh: 'true' } }).catch(() => undefined)
    qc.invalidateQueries({ queryKey: ['ocp-access-risks', clusterId] })
    qc.invalidateQueries({ queryKey: ['ocp-access-overview', clusterId] })
  }
  const d = q.data
  const sum: Summary | undefined = d?.summary
  const subjLink = (r: any) => (
    <button type="button" className="font-mono text-left hover:text-blue-300 break-all"
      onClick={e => { e.stopPropagation(); onSubject?.(r.subject_kind, r.subject, r.subject_namespace) }}>
      {r.subject_kind}/{r.subject_namespace ? `${r.subject_namespace}/` : ''}{r.subject}
    </button>
  )
  const bindingCols: TableColumn<any>[] = [
    { id: 'subject', label: t('ocp_acc_subj_name'), text: r => `${r.subject_kind}/${r.subject}`, render: subjLink },
    { id: 'binding', label: t('ocp_rb_col_binding'), text: r => `${r.binding_kind} ${r.namespace || ''}/${r.binding}`,
      render: r => <span className="font-mono">{r.binding_kind === 'ClusterRoleBinding' ? 'CRB' : 'RB'} · {r.namespace ? `${r.namespace}/` : ''}{r.binding}</span> },
    { id: 'role', label: t('ocp_rb_col_role'), text: r => `${r.role_kind}/${r.role}`, render: r => <span className="font-mono">{r.role_kind}/{r.role}</span> },
    { id: 'sev', label: t('ocp_rb_col_severity'), text: r => r.severity, num: r => SEV_RANK[r.severity] || 0, render: r => <Sev s={r.severity} /> },
  ]
  const cards: { id: typeof section; label: string; n: number; tone: string }[] = sum ? [
    { id: 'ca', label: t('ocp_rb_card_ca'), n: sum.cluster_admin_holders, tone: sum.cluster_admin_holders > 0 ? 'text-red-300' : 'text-emerald-300' },
    { id: 'wild', label: t('ocp_rb_card_wild'), n: sum.wildcard_roles, tone: sum.wildcard_roles > 0 ? 'text-amber-300' : 'text-emerald-300' },
    { id: 'broad', label: t('ocp_rb_card_broad'), n: sum.broad_group_grants, tone: sum.broad_group_grants > 0 ? 'text-red-300' : 'text-emerald-300' },
    { id: 'orphan', label: t('ocp_rb_card_orphan_b'), n: sum.orphan_bindings, tone: sum.orphan_bindings > 0 ? 'text-amber-300' : 'text-emerald-300' },
    { id: 'orphan', label: t('ocp_rb_card_orphan_s'), n: sum.orphan_subjects, tone: 'text-slate-300' },
  ] : []

  return (
    <div className="space-y-3" data-testid="risk-panel">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs text-slate-500">{t('ocp_rb_risk_hint')}</p>
        <button type="button" onClick={refresh} className="shrink-0 inline-flex items-center gap-1 text-[11px] text-slate-400 hover:text-white">
          <RefreshCw size={12} className={q.isFetching ? 'animate-spin' : ''} /> {t('ocp_rb_refresh')}
        </button>
      </div>
      {q.isLoading && <p className="text-xs text-slate-500">{t('ocp_rb_loading')}</p>}
      {q.error && <p className="text-xs text-amber-300">{(q.error as Error).message}</p>}
      {d?.ok === false && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" /> {d.error}
        </div>
      )}
      {sum && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            {cards.map((c, i) => (
              <button key={i} type="button" onClick={() => setSection(c.id)} data-testid={`risk-card-${i}`}
                className={`text-left rounded-lg border px-3 py-2 bg-cyber-card ${section === c.id ? 'border-blue-500/40' : 'border-white/[0.06]'}`}>
                <div className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">{c.label}</div>
                <div className={`text-lg font-semibold tabular-nums mt-0.5 ${c.tone}`}>{c.n}</div>
              </button>
            ))}
          </div>

          {section === 'ca' && (
            <Section title={t('ocp_rb_sec_ca')} icon>
              <ColumnTable<any>
                testId="risk-ca" rows={d.cluster_admin_holders || []} columns={[
                  ...bindingCols.slice(0, 2),
                  { id: 'members', label: t('ocp_rb_col_members'), text: r => String(r.member_count ?? ''), num: r => r.member_count ?? null,
                    render: r => r.member_count != null ? <span title={(r.members || []).join(', ')}>{r.member_count} {t('ocp_rb_risk_members')}</span> : '—' },
                ]}
                rowKey={r => `${r.binding}:${r.subject}`} searchPlaceholder={t('ocp_acc_search_ph')} empty={t('ocp_rb_risk_none')} pageSize={15} />
            </Section>
          )}
          {section === 'wild' && (
            <Section title={t('ocp_rb_sec_wild')}>
              <ColumnTable<any>
                testId="risk-wild" rows={d.wildcard_roles || []} defaultSort={{ id: 'sev', dir: 'desc' }} columns={[
                  { id: 'role', label: t('ocp_rb_col_role'), text: r => `${r.role_kind}/${r.role}`,
                    render: r => <span className="font-mono">{r.role_kind}/{r.namespace ? `${r.namespace}/` : ''}{r.role}{r.builtin && <span className="ml-1 text-slate-500">({t('ocp_rb_risk_builtin')})</span>}</span> },
                  { id: 'wild', label: 'wildcard', text: r => r.wildcard },
                  { id: 'sev', label: t('ocp_rb_col_severity'), text: r => r.severity, num: r => SEV_RANK[r.severity] || 0, render: r => <Sev s={r.severity} /> },
                ]}
                rowKey={r => `${r.role_kind}:${r.namespace}:${r.role}`} searchPlaceholder={t('ocp_acc_search_ph')} empty={t('ocp_rb_risk_none')} pageSize={15} />
            </Section>
          )}
          {section === 'broad' && (
            <Section title={t('ocp_rb_sec_broad')}>
              <ColumnTable<any> testId="risk-broad" rows={d.broad_group_grants || []} columns={bindingCols}
                rowKey={r => `${r.binding}:${r.subject}`} searchPlaceholder={t('ocp_acc_search_ph')} empty={t('ocp_rb_risk_none')} pageSize={15} />
            </Section>
          )}
          {section === 'orphan' && (
            <Section title={t('ocp_rb_sec_orphan')}>
              <ColumnTable<any>
                testId="risk-orphan" rows={d.orphans || []} defaultSort={{ id: 'sev', dir: 'desc' }} columns={[
                  { id: 'binding', label: t('ocp_rb_col_binding'), text: r => `${r.namespace || ''}/${r.binding}`,
                    render: r => <span className="font-mono">{r.binding_kind === 'ClusterRoleBinding' ? 'CRB' : 'RB'} · {r.namespace ? `${r.namespace}/` : ''}{r.binding}</span> },
                  { id: 'subject', label: t('ocp_acc_subj_name'), text: r => r.subject || '', render: r => r.subject ? subjLink(r) : '—' },
                  { id: 'detail', label: t('ocp_rb_col_detail'), text: r => r.message, render: r => <span className="text-slate-400">{r.message}</span> },
                  { id: 'sev', label: t('ocp_rb_col_severity'), text: r => r.severity, num: r => SEV_RANK[r.severity] || 0, render: r => <Sev s={r.severity} /> },
                ]}
                rowKey={r => `${r.binding}:${r.subject}:${r.type}`} searchPlaceholder={t('ocp_acc_search_ph')} empty={t('ocp_rb_risk_none')} pageSize={15} />
            </Section>
          )}
        </>
      )}
    </div>
  )
}

function Section({ title, children, icon }: { title: string; children: React.ReactNode; icon?: boolean }) {
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
        {icon && <ShieldAlert size={13} className="text-red-400" />}{title}
      </h3>
      {children}
    </div>
  )
}
