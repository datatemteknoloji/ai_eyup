import { useMemo, useState } from 'react'
import { AlertTriangle, Check } from 'lucide-react'
import { useT } from '../../../i18n/LocaleProvider'
import type { Matrix } from './accessApi'

/** Kaynak × fiil izin matrisi (Role/ClusterRole veya etkin yetki). Wildcard ve kısıtlı (resourceNames) satırlar işaretlenir. */
export default function PermissionMatrix({ matrix, maxHeight = 'max-h-80' }: { matrix: Matrix; maxHeight?: string }) {
  const t = useT()
  const [q, setQ] = useState('')
  const rows = useMemo(() => {
    const n = q.trim().toLowerCase()
    return n ? matrix.rows.filter(r => `${r.api_group}/${r.resource}`.toLowerCase().includes(n)) : matrix.rows
  }, [matrix.rows, q])
  if (!matrix.rows.length && !matrix.non_resource.length) {
    return <p className="text-xs text-slate-500" data-testid="matrix-empty">{t('ocp_rb_matrix_empty')}</p>
  }
  return (
    <div className="space-y-2" data-testid="permission-matrix">
      {matrix.full_access ? (
        <div className="flex items-center gap-1.5 rounded-md border border-red-500/30 bg-red-500/10 px-2 py-1 text-[11px] text-red-300" data-testid="matrix-full">
          <AlertTriangle size={12} /> {t('ocp_rb_matrix_full')}
        </div>
      ) : (matrix.wildcard_verbs || matrix.wildcard_resources) ? (
        <div className="flex items-center gap-1.5 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-300" data-testid="matrix-wildcard">
          <AlertTriangle size={12} /> {t('ocp_rb_matrix_wild')}
        </div>
      ) : null}
      {matrix.rows.length > 8 && (
        <input value={q} onChange={e => setQ(e.target.value)} placeholder={t('ocp_rb_matrix_search')}
          className="w-full max-w-xs bg-white/[0.04] border border-white/[0.08] rounded-md px-2 py-1 text-[11px] text-slate-200" />
      )}
      <div className={`${maxHeight} overflow-auto border border-white/[0.06] rounded-md`}>
        <table className="w-full text-[11px]">
          <thead className="sticky top-0 bg-cyber-card z-10 text-slate-400">
            <tr>
              <th className="text-left px-2 py-1.5 font-medium">{t('ocp_rb_col_resource')}</th>
              {matrix.columns.map(c => <th key={c} className="px-1.5 py-1.5 font-medium text-center">{c}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={`${r.api_group}/${r.resource}`} className="border-t border-white/[0.04]" data-testid="matrix-row">
                <td className="px-2 py-1 font-mono text-slate-300 break-all">
                  {r.resource}
                  {r.api_group ? <span className="text-slate-600"> · {r.api_group}</span> : null}
                  {r.restricted && r.resource_names.length > 0 && (
                    <span className="ml-1 text-amber-400/80">({t('ocp_rb_matrix_names')}{r.resource_names.join(', ')})</span>
                  )}
                </td>
                {matrix.columns.map(c => (
                  <td key={c} className="px-1.5 py-1 text-center">
                    {r.verbs.includes(c) || r.all_verbs
                      ? <Check size={12} className={`inline ${c === 'delete' || c === 'deletecollection' ? 'text-red-400' : c === 'get' || c === 'list' || c === 'watch' ? 'text-emerald-400' : 'text-amber-400'}`} />
                      : <span className="text-slate-700">·</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {matrix.rows.some(r => r.verbs.some(v => !matrix.columns.includes(v) && v !== '*')) && (
        <p className="text-[10px] text-slate-500">
          {matrix.rows.flatMap(r => r.verbs.filter(v => !matrix.columns.includes(v) && v !== '*').map(v => `${r.resource}:${v}`)).slice(0, 12).join(' · ')}
        </p>
      )}
      {matrix.non_resource.length > 0 && (
        <div className="text-[11px] text-slate-400">
          <div className="text-slate-500">{t('ocp_rb_matrix_nonres')}</div>
          {matrix.non_resource.map((n, i) => <div key={i} className="font-mono break-all">{n.urls.join(', ')} → {n.verbs.join(', ')}</div>)}
        </div>
      )}
    </div>
  )
}
