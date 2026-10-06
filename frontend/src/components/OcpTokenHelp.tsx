import { useEffect, useRef, useState } from 'react'
import { Info } from 'lucide-react'
import { useT } from '../i18n/LocaleProvider'

const CMD_ROUTE = `oc get route thanos-querier -n openshift-monitoring -o jsonpath='{.spec.host}'`

const CMD_SA = `oc create sa ainew-monitoring -n openshift-monitoring
oc adm policy add-cluster-role-to-user cluster-monitoring-view \\
  -z ainew-monitoring -n openshift-monitoring
oc create token ainew-monitoring -n openshift-monitoring --duration=8760h`

const CMD_SA_SECRET = `oc apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: ainew-monitoring-token
  namespace: openshift-monitoring
  annotations:
    kubernetes.io/service-account.name: ainew-monitoring
type: kubernetes.io/service-account-token
EOF
oc get secret ainew-monitoring-token -n openshift-monitoring \\
  -o jsonpath='{.data.token}' | base64 -d`

const CMD_USER = `oc whoami -t`

function Cmd({ children }: { children: string }) {
  return (
    <pre className="mt-1 mb-2 whitespace-pre-wrap break-all rounded bg-black/40 border border-slate-700 px-2 py-1.5 text-[10px] leading-snug font-mono text-emerald-200 select-all">
      {children}
    </pre>
  )
}

/** (i) bilgi balonu: OpenShift Thanos / monitoring için Bearer token nasıl alınır. */
export default function OcpTokenHelp() {
  const t = useT()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <span ref={ref} className="relative inline-flex align-middle ml-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={t('ocp_token_help_title')}
        aria-expanded={open}
        title={t('ocp_token_help_title')}
        className="text-slate-500 hover:text-blue-300"
      >
        <Info size={13} strokeWidth={1.8} />
      </button>
      {open && (
        <div
          role="dialog"
          className="absolute left-0 top-5 z-30 w-[min(30rem,86vw)] max-h-[70vh] overflow-y-auto rounded-lg border border-slate-600 bg-cyber-deep shadow-xl p-3 text-[11px] text-slate-300 font-normal normal-case tracking-normal"
        >
          <div className="text-xs font-semibold text-slate-100 mb-1">{t('ocp_token_help_title')}</div>
          <p className="mb-2">{t('ocp_token_help_intro')}</p>

          <div className="font-semibold text-slate-200">1) {t('ocp_token_help_url')}</div>
          <Cmd>{CMD_ROUTE}</Cmd>
          <p className="mb-2 text-slate-400">{t('ocp_token_help_url_note')}</p>

          <div className="font-semibold text-slate-200">2) {t('ocp_token_help_sa')}</div>
          <Cmd>{CMD_SA}</Cmd>
          <p className="mb-1 text-slate-400">{t('ocp_token_help_sa_secret')}</p>
          <Cmd>{CMD_SA_SECRET}</Cmd>

          <div className="font-semibold text-slate-200">3) {t('ocp_token_help_user')}</div>
          <Cmd>{CMD_USER}</Cmd>
          <p className="mb-2 text-slate-400">{t('ocp_token_help_user_note')}</p>

          <p className="text-slate-400">{t('ocp_token_help_ssl')}</p>
        </div>
      )}
    </span>
  )
}
