import { useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, Info, Plus, Trash2 } from 'lucide-react'
import { Modal } from '../../aiops/ui'
import { useT } from '../../../i18n/LocaleProvider'
import { ACCESS_KINDS, accessRequest, type AccessKind, type Capabilities } from './accessApi'

/**
 * RBAC nesnesi OLUŞTURMA sihirbazı (yalnız Admin; düzenleme/silme YOK).
 * Akış: düzenle (form | YAML) → ön izle (sunucu dry-run + risk uyarıları) → onayla → oluştur.
 * Kritik uyarıda nesne adını yazma + onay kutusu zorunlu (sunucu da doğrular).
 */

type Subj = { kind: 'User' | 'Group' | 'ServiceAccount'; name: string; namespace: string }
type RuleRow = { verbs: string[]; groups: string; resources: string; names: string; urls: string }
const VERBS = ['get', 'list', 'watch', 'create', 'update', 'patch', 'delete', 'deletecollection', '*']
const emptyRule = (): RuleRow => ({ verbs: ['get', 'list', 'watch'], groups: '', resources: '', names: '', urls: '' })
const csv = (s: string) => s.split(',').map(x => x.trim()).filter(Boolean)

const TEMPLATES: Record<AccessKind, string> = {
  RoleBinding: `apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: dev-view
  namespace: dev
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: view
subjects:
- kind: User
  name: alice
  apiGroup: rbac.authorization.k8s.io
`,
  ClusterRoleBinding: `apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: ops-readers
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-reader
subjects:
- kind: Group
  name: ops
  apiGroup: rbac.authorization.k8s.io
`,
  Role: `apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-reader
  namespace: dev
rules:
- apiGroups: [""]
  resources: ["pods", "pods/log"]
  verbs: ["get", "list", "watch"]
`,
  ClusterRole: `apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: node-reader
rules:
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list", "watch"]
`,
}

const WARN_CLS: Record<string, string> = {
  critical: 'border-red-500/30 bg-red-500/10 text-red-300',
  warning: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
  info: 'border-slate-500/30 bg-slate-500/10 text-slate-300',
}

const inputCls = 'w-full bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1.5 text-xs text-slate-200 font-mono'
const labelCls = 'text-[10px] uppercase text-slate-500'

export default function CreateDialog({
  clusterId, caps, initialKind, nsOptions, clusterRoles, roles, onClose, onCreated,
}: {
  clusterId: number
  caps: Capabilities
  initialKind?: AccessKind
  nsOptions: string[]
  clusterRoles: string[]
  roles: { namespace: string; name: string }[]
  onClose: () => void
  onCreated: () => void
}) {
  const t = useT()
  const firstAllowed = ACCESS_KINDS.find(k => caps.kinds[k]?.allowed) || 'RoleBinding'
  const [mode, setMode] = useState<'form' | 'yaml'>('form')
  const [kind, setKind] = useState<AccessKind>(initialKind && caps.kinds[initialKind]?.allowed ? initialKind : firstAllowed)
  const [name, setName] = useState('')
  const [ns, setNs] = useState('')
  const [desc, setDesc] = useState('')
  const [refKind, setRefKind] = useState<'Role' | 'ClusterRole'>('ClusterRole')
  const [refName, setRefName] = useState('')
  const [subjects, setSubjects] = useState<Subj[]>([{ kind: 'User', name: '', namespace: '' }])
  const [rules, setRules] = useState<RuleRow[]>([emptyRule()])
  const [copyFrom, setCopyFrom] = useState('')
  const [yamlText, setYamlText] = useState(TEMPLATES[initialKind || 'RoleBinding'])
  const [step, setStep] = useState<'edit' | 'preview' | 'done'>('edit')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [prev, setPrev] = useState<any>(null)
  const [confirmName, setConfirmName] = useState('')
  const [confirmCheck, setConfirmCheck] = useState(false)

  const isBinding = kind === 'RoleBinding' || kind === 'ClusterRoleBinding'
  const namespaced = kind === 'RoleBinding' || kind === 'Role'
  const roleChoices = useMemo(
    () => refKind === 'ClusterRole' ? clusterRoles : roles.filter(r => r.namespace === ns).map(r => r.name),
    [refKind, clusterRoles, roles, ns],
  )

  const body = () => {
    if (mode === 'yaml') return { mode: 'yaml', yaml: yamlText }
    const spec: Record<string, unknown> = { name: name.trim(), description: desc.trim() || undefined }
    if (namespaced) spec.namespace = ns
    if (isBinding) {
      spec.role_ref = { kind: kind === 'ClusterRoleBinding' ? 'ClusterRole' : refKind, name: refName.trim() }
      spec.subjects = subjects
        .filter(s => s.name.trim())
        .map(s => ({ kind: s.kind, name: s.name.trim(), namespace: s.kind === 'ServiceAccount' ? s.namespace : undefined }))
    } else {
      spec.rules = rules
        .filter(r => r.verbs.length && (r.resources.trim() || r.urls.trim()))
        .map(r => ({
          verbs: r.verbs, apiGroups: r.groups.trim() ? csv(r.groups) : [''], resources: csv(r.resources),
          resourceNames: csv(r.names), nonResourceURLs: csv(r.urls),
        }))
    }
    const out: Record<string, unknown> = { mode: 'form', kind, spec }
    if (copyFrom && !isBinding) {
      const [k, rest] = copyFrom.split(':')
      const [cns, cname] = rest.includes('/') ? rest.split('/') : ['', rest]
      out.copy_from = { kind: k, name: cname, namespace: cns || undefined }
    }
    return out
  }

  const run = async (path: 'create/preview' | 'create', extra: Record<string, unknown> = {}) => {
    setBusy(true); setError('')
    try {
      return await accessRequest<any>(clusterId, path, { method: 'POST', body: { ...body(), ...extra } })
    } catch (e: any) {
      setError(e.message)
      return null
    } finally {
      setBusy(false)
    }
  }
  const doPreview = async () => {
    const r = await run('create/preview')
    if (r) { setPrev(r); setConfirmName(''); setConfirmCheck(false); setStep('preview') }
  }
  const needConfirm = !!prev?.requires_name_confirmation
  const confirmOk = !needConfirm || (confirmName.trim() === prev?.manifest?.metadata?.name && confirmCheck)
  const doCreate = async () => {
    const r = await run('create', { confirm_name: needConfirm ? confirmName.trim() : undefined })
    if (r) { setPrev(r); setStep('done'); onCreated() }
  }

  const setSubj = (i: number, patch: Partial<Subj>) => setSubjects(s => s.map((x, j) => (j === i ? { ...x, ...patch } : x)))
  const setRule = (i: number, patch: Partial<RuleRow>) => setRules(s => s.map((x, j) => (j === i ? { ...x, ...patch } : x)))

  return (
    <Modal title={t('ocp_rb_create_title')} subtitle={t('ocp_rb_create_sub')} onClose={onClose} maxWidth="max-w-3xl"
      footer={(
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] text-slate-500">{busy ? t('ocp_rb_busy') : ''}</span>
          <div className="flex gap-2">
            {step === 'preview' && (
              <button type="button" className="px-3 py-1.5 text-xs rounded-md border border-white/[0.1] text-slate-300 hover:text-white"
                onClick={() => { setStep('edit'); setError('') }}>{t('ocp_rb_back')}</button>
            )}
            {step === 'edit' && (
              <button type="button" data-testid="create-preview" disabled={busy}
                className="px-3 py-1.5 text-xs rounded-md bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-40"
                onClick={doPreview}>{t('ocp_rb_preview')}</button>
            )}
            {step === 'preview' && (
              <button type="button" data-testid="create-submit" disabled={busy || !prev?.dry_run?.ok || !confirmOk}
                className="px-3 py-1.5 text-xs rounded-md bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-40"
                onClick={doCreate}>{t('ocp_rb_submit')}</button>
            )}
            {step === 'done' && (
              <button type="button" className="px-3 py-1.5 text-xs rounded-md bg-blue-600 text-white hover:bg-blue-500" onClick={onClose}>{t('ocp_rb_close')}</button>
            )}
          </div>
        </div>
      )}>
      <div className="p-5 space-y-4 text-xs" data-testid="create-dialog">
        {error && (
          <div className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-red-300" data-testid="create-error">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" /> <span>{error}</span>
          </div>
        )}

        {step === 'edit' && (
          <>
            <div className="flex gap-1.5">
              {(['form', 'yaml'] as const).map(m => (
                <button key={m} type="button" data-testid={`mode-${m}`} onClick={() => setMode(m)}
                  className={`px-2.5 py-1 rounded-md text-[11px] font-medium ${mode === m ? 'bg-blue-600/30 text-blue-200 border border-blue-500/40' : 'text-slate-400 border border-white/[0.06]'}`}>
                  {t(m === 'form' ? 'ocp_rb_mode_form' : 'ocp_rb_mode_yaml')}
                </button>
              ))}
            </div>

            {mode === 'yaml' ? (
              <div className="space-y-2">
                <p className="text-slate-500">{t('ocp_rb_yaml_hint')}</p>
                <div className="flex gap-1.5 flex-wrap">
                  {ACCESS_KINDS.map(k => (
                    <button key={k} type="button" disabled={!caps.kinds[k]?.allowed} title={caps.kinds[k]?.reason}
                      onClick={() => setYamlText(TEMPLATES[k])}
                      className="px-2 py-0.5 rounded-sm border border-white/[0.08] text-[11px] text-slate-400 hover:text-white disabled:opacity-30">
                      {t('ocp_rb_yaml_load_template')}: {k}
                    </button>
                  ))}
                </div>
                <textarea value={yamlText} onChange={e => setYamlText(e.target.value)} rows={16} spellCheck={false}
                  data-testid="yaml-input" className={`${inputCls} leading-snug`} />
              </div>
            ) : (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className={labelCls}>{t('ocp_rb_f_kind')}</label>
                    <select value={kind} data-testid="kind-select" onChange={e => setKind(e.target.value as AccessKind)} className={inputCls}>
                      {ACCESS_KINDS.map(k => (
                        <option key={k} value={k} disabled={!caps.kinds[k]?.allowed}>
                          {k}{caps.kinds[k]?.allowed ? '' : ` — ${t('ocp_rb_cap_denied')}`}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className={labelCls}>{t('ocp_rb_f_name')}</label>
                    <input value={name} data-testid="f-name" onChange={e => setName(e.target.value)} className={inputCls} placeholder="ornek-ad" />
                  </div>
                  {namespaced && (
                    <div>
                      <label className={labelCls}>{t('ocp_rb_f_ns')}</label>
                      <select value={ns} data-testid="f-ns" onChange={e => setNs(e.target.value)} className={inputCls}>
                        <option value="">{t('ocp_rb_pick')}</option>
                        {nsOptions.map(n => <option key={n} value={n}>{n}</option>)}
                      </select>
                    </div>
                  )}
                  <div className={namespaced ? '' : 'col-span-1'}>
                    <label className={labelCls}>{t('ocp_rb_f_desc')}</label>
                    <input value={desc} onChange={e => setDesc(e.target.value)} className={inputCls} />
                  </div>
                </div>

                {isBinding ? (
                  <>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className={labelCls}>{t('ocp_rb_f_ref_kind')}</label>
                        <select value={kind === 'ClusterRoleBinding' ? 'ClusterRole' : refKind} disabled={kind === 'ClusterRoleBinding'}
                          onChange={e => { setRefKind(e.target.value as 'Role' | 'ClusterRole'); setRefName('') }} className={inputCls}>
                          <option>ClusterRole</option>
                          {kind === 'RoleBinding' && <option>Role</option>}
                        </select>
                      </div>
                      <div>
                        <label className={labelCls}>{t('ocp_rb_f_ref_name')}</label>
                        <input list="ocp-rb-roles" value={refName} data-testid="f-ref-name" onChange={e => setRefName(e.target.value)} className={inputCls} />
                        <datalist id="ocp-rb-roles">{roleChoices.map(n => <option key={n} value={n} />)}</datalist>
                      </div>
                    </div>
                    <div className="space-y-1.5">
                      <label className={labelCls}>{t('ocp_rb_f_subjects')}</label>
                      {subjects.map((s, i) => (
                        <div key={i} className="flex gap-1.5 items-center" data-testid="subject-row">
                          <select value={s.kind} onChange={e => setSubj(i, { kind: e.target.value as Subj['kind'] })} className={`${inputCls} w-36`}>
                            <option>User</option><option>Group</option><option>ServiceAccount</option>
                          </select>
                          <input value={s.name} placeholder={t('ocp_rb_f_subj_name')} data-testid="subject-name"
                            onChange={e => setSubj(i, { name: e.target.value })} className={inputCls} />
                          {s.kind === 'ServiceAccount' && (
                            <select value={s.namespace} onChange={e => setSubj(i, { namespace: e.target.value })} className={`${inputCls} w-44`}>
                              <option value="">{t('ocp_rb_f_subj_ns')}</option>
                              {nsOptions.map(n => <option key={n} value={n}>{n}</option>)}
                            </select>
                          )}
                          {subjects.length > 1 && (
                            <button type="button" title={t('ocp_rb_remove')} className="text-slate-500 hover:text-red-400"
                              onClick={() => setSubjects(x => x.filter((_, j) => j !== i))}><Trash2 size={13} /></button>
                          )}
                        </div>
                      ))}
                      <button type="button" className="text-[11px] text-blue-300 hover:underline inline-flex items-center gap-1"
                        onClick={() => setSubjects(x => [...x, { kind: 'User', name: '', namespace: '' }])}><Plus size={11} />{t('ocp_rb_add_subject')}</button>
                    </div>
                  </>
                ) : (
                  <>
                    <div>
                      <label className={labelCls}>{t('ocp_rb_copy_from')}</label>
                      <select value={copyFrom} data-testid="copy-from" onChange={e => setCopyFrom(e.target.value)} className={inputCls}>
                        <option value="">{t('ocp_rb_copy_none')}</option>
                        <optgroup label="ClusterRole">
                          {clusterRoles.map(n => <option key={n} value={`ClusterRole:${n}`}>{n}</option>)}
                        </optgroup>
                        {kind === 'Role' && ns && (
                          <optgroup label={`Role (${ns})`}>
                            {roles.filter(r => r.namespace === ns).map(r => <option key={r.name} value={`Role:${ns}/${r.name}`}>{r.name}</option>)}
                          </optgroup>
                        )}
                      </select>
                    </div>
                    <div className="space-y-2">
                      <label className={labelCls}>{t('ocp_rb_f_rules')}</label>
                      {rules.map((r, i) => (
                        <div key={i} className="rounded-md border border-white/[0.06] p-2 space-y-1.5" data-testid="rule-row">
                          <div className="flex flex-wrap gap-1.5 items-center">
                            <span className="text-slate-500">{t('ocp_rb_f_verbs')}:</span>
                            {VERBS.map(v => (
                              <label key={v} className="inline-flex items-center gap-1 text-[11px] text-slate-300">
                                <input type="checkbox" checked={r.verbs.includes(v)}
                                  onChange={e => setRule(i, { verbs: e.target.checked ? [...r.verbs, v] : r.verbs.filter(x => x !== v) })} />
                                {v}
                              </label>
                            ))}
                            {rules.length > 1 && (
                              <button type="button" title={t('ocp_rb_remove')} className="ml-auto text-slate-500 hover:text-red-400"
                                onClick={() => setRules(x => x.filter((_, j) => j !== i))}><Trash2 size={13} /></button>
                            )}
                          </div>
                          <div className="grid grid-cols-2 gap-1.5">
                            <div><label className={labelCls}>{t('ocp_rb_f_resources')}</label>
                              <input value={r.resources} data-testid="rule-resources" onChange={e => setRule(i, { resources: e.target.value })} className={inputCls} placeholder="pods, pods/log" /></div>
                            <div><label className={labelCls}>{t('ocp_rb_f_groups')}</label>
                              <input value={r.groups} onChange={e => setRule(i, { groups: e.target.value })} className={inputCls} placeholder='apps, batch' /></div>
                            <div><label className={labelCls}>{t('ocp_rb_f_res_names')}</label>
                              <input value={r.names} onChange={e => setRule(i, { names: e.target.value })} className={inputCls} /></div>
                            {kind === 'ClusterRole' && (
                              <div><label className={labelCls}>{t('ocp_rb_f_urls')}</label>
                                <input value={r.urls} onChange={e => setRule(i, { urls: e.target.value })} className={inputCls} placeholder="/healthz" /></div>
                            )}
                          </div>
                        </div>
                      ))}
                      <button type="button" className="text-[11px] text-blue-300 hover:underline inline-flex items-center gap-1"
                        onClick={() => setRules(x => [...x, emptyRule()])}><Plus size={11} />{t('ocp_rb_add_rule')}</button>
                    </div>
                  </>
                )}
              </div>
            )}
          </>
        )}

        {(step === 'preview' || step === 'done') && prev && (
          <div className="space-y-3" data-testid={step === 'done' ? 'create-done' : 'create-preview-pane'}>
            {step === 'done' ? (
              <div className="flex items-start gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-emerald-300">
                <CheckCircle2 size={14} className="mt-0.5 shrink-0" />
                <span><b>{t('ocp_rb_done')}:</b> {prev.manifest.kind} {prev.manifest.metadata.namespace ? `${prev.manifest.metadata.namespace}/` : ''}{prev.manifest.metadata.name}. {t('ocp_rb_done_hint')}</span>
              </div>
            ) : (
              <>
                <p className="text-slate-400 font-medium">{t('ocp_rb_preview_title')}</p>
                {prev.dry_run?.ok ? (
                  <div className="flex items-center gap-2 text-emerald-300"><CheckCircle2 size={13} />{t('ocp_rb_dry_ok')}</div>
                ) : (
                  <div className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-red-300" data-testid="dry-fail">
                    <AlertTriangle size={14} className="mt-0.5 shrink-0" /><span><b>{t('ocp_rb_dry_fail')}:</b> {prev.dry_run?.message}</span>
                  </div>
                )}
              </>
            )}
            {prev.warnings?.length > 0 && (
              <div className="space-y-1" data-testid="create-warnings">
                <div className="text-slate-400 font-medium">{t('ocp_rb_warnings')}</div>
                {prev.warnings.map((w: any, i: number) => (
                  <div key={i} className={`flex items-start gap-2 rounded-md border px-2 py-1.5 ${WARN_CLS[w.level] || WARN_CLS.info}`}>
                    <AlertTriangle size={12} className="mt-0.5 shrink-0" /><span>{w.message}</span>
                  </div>
                ))}
              </div>
            )}
            {prev.ignored?.length > 0 && (
              <div className="text-slate-500"><Info size={11} className="inline mr-1" />{t('ocp_rb_ignored')}: {prev.ignored.join(' · ')}</div>
            )}
            <pre className="bg-black/40 border border-white/[0.06] rounded-md p-3 font-mono text-[11px] text-slate-200 whitespace-pre-wrap max-h-64 overflow-auto" data-testid="manifest-yaml">{prev.yaml}</pre>
            <div className="text-[11px] text-slate-500">
              {t('ocp_rb_delete_note')}: <code className="font-mono text-slate-400" data-testid="equivalent-delete">{prev.equivalent_delete}</code>
            </div>
            {step === 'preview' && needConfirm && (
              <div className="space-y-2 rounded-md border border-red-500/20 bg-red-500/5 p-3" data-testid="confirm-box">
                <label className={labelCls}>{t('ocp_rb_confirm_name')}: <span className="font-mono text-slate-300 normal-case">{prev.manifest.metadata.name}</span></label>
                <input value={confirmName} data-testid="confirm-name" onChange={e => setConfirmName(e.target.value)} className={inputCls} />
                <label className="flex items-center gap-2 text-slate-300">
                  <input type="checkbox" data-testid="confirm-check" checked={confirmCheck} onChange={e => setConfirmCheck(e.target.checked)} />
                  {t('ocp_rb_confirm_check')}
                </label>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  )
}
