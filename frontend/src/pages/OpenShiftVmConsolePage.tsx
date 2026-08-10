/**
 * KubeVirt VNC konsol — Atlas ile aynı model (noVNC).
 * Tarayıcı → ainew WS proxy → cluster /vnc (plain.kubevirt.io). Guest parola yok.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { AlertTriangle, Loader2, Monitor, RefreshCw, Wifi, WifiOff } from 'lucide-react'
import RFB from '@novnc/novnc'

type Status = 'connecting' | 'connected' | 'disconnected' | 'error'

const OpenShiftVmConsolePage: React.FC = () => {
  const { clusterId, namespace, name } = useParams<{
    clusterId: string
    namespace: string
    name: string
  }>()
  const [searchParams] = useSearchParams()
  const title = searchParams.get('title') || `${namespace}/${name}`

  const screenRef = useRef<HTMLDivElement | null>(null)
  const rfbRef = useRef<{ disconnect: () => void; sendCtrlAltDel?: () => void } | null>(null)
  const [status, setStatus] = useState<Status>('connecting')
  const [error, setError] = useState('')

  useEffect(() => {
    document.title = `Konsol — ${title}`
  }, [title])

  const connect = useCallback(() => {
    if (!screenRef.current || !clusterId || !namespace || !name) return
    setStatus('connecting')
    setError('')
    if (rfbRef.current) {
      try {
        rfbRef.current.disconnect()
      } catch {
        /* ignore */
      }
      rfbRef.current = null
    }
    try {
      const jwt = localStorage.getItem('auth_token') || ''
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const path =
        `/api/v1/openshift/clusters/${clusterId}/kubevirt/vms/` +
        `${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/console`
      const url = `${proto}://${window.location.host}${path}?token=${encodeURIComponent(jwt)}`
      const rfb = new RFB(screenRef.current, url, { wsProtocols: ['binary'] })
      rfb.scaleViewport = true
      rfb.background = '#0a0f1a'
      rfb.addEventListener('connect', () => setStatus('connected'))
      rfb.addEventListener('disconnect', (e: Event) => {
        setStatus('disconnected')
        const detail = (e as CustomEvent)?.detail
        if (detail && !detail.clean) {
          setError('Bağlantı kapandı — VM Running mi? VNC yetkisi (subresource) var mı?')
        }
      })
      rfb.addEventListener('securityfailure', () => {
        setStatus('error')
        setError('Kimlik doğrulama başarısız — küme token / VNC RBAC kontrol edin')
      })
      rfbRef.current = rfb
    } catch {
      setStatus('error')
      setError('Konsol başlatılamadı')
    }
  }, [clusterId, namespace, name])

  useEffect(() => {
    connect()
    return () => {
      if (rfbRef.current) {
        try {
          rfbRef.current.disconnect()
        } catch {
          /* ignore */
        }
      }
    }
  }, [connect])

  const statusMeta = {
    connecting: { icon: <Loader2 className="w-3.5 h-3.5 animate-spin" />, label: 'Bağlanıyor', cls: 'text-amber-400' },
    connected: { icon: <Wifi className="w-3.5 h-3.5" />, label: 'Bağlı (VNC)', cls: 'text-emerald-400' },
    disconnected: { icon: <WifiOff className="w-3.5 h-3.5" />, label: 'Kesildi', cls: 'text-slate-400' },
    error: { icon: <AlertTriangle className="w-3.5 h-3.5" />, label: 'Hata', cls: 'text-red-400' },
  }[status]

  return (
    <div className="fixed inset-0 bg-[#0a0f1a] flex flex-col">
      <div className="h-12 flex items-center gap-3 px-4 border-b border-white/10 bg-[#161b22] flex-shrink-0">
        <Monitor className="w-4 h-4 text-violet-400" />
        <span className="text-sm font-semibold text-slate-200">KubeVirt Konsol</span>
        <span className="text-xs text-slate-500 font-mono truncate">{title}</span>
        <span className={`flex items-center gap-1.5 text-xs ${statusMeta.cls}`}>
          {statusMeta.icon} {statusMeta.label}
        </span>
        <div className="ml-auto flex items-center gap-2">
          {status === 'connected' && (
            <button
              type="button"
              onClick={() => {
                try {
                  rfbRef.current?.sendCtrlAltDel?.()
                } catch {
                  /* ignore */
                }
              }}
              className="text-xs px-2.5 py-1.5 rounded border border-white/15 text-slate-300 hover:bg-white/5"
            >
              Ctrl+Alt+Del
            </button>
          )}
          <button
            type="button"
            onClick={() => connect()}
            className="text-xs px-2.5 py-1.5 rounded border border-white/15 text-slate-300 hover:bg-white/5 inline-flex items-center gap-1.5"
          >
            <RefreshCw className="w-3.5 h-3.5" /> Yeniden bağlan
          </button>
          <button
            type="button"
            onClick={() => window.close()}
            className="text-xs px-2.5 py-1.5 rounded border border-white/15 text-slate-300 hover:bg-white/5"
          >
            Kapat
          </button>
        </div>
      </div>

      <div className="flex-1 relative overflow-hidden">
        <div ref={screenRef} className="absolute inset-0" />
        {(status === 'error' || (status === 'disconnected' && error)) && (
          <div className="absolute inset-0 flex items-center justify-center bg-[#0a0f1a]/80">
            <div className="rounded-xl border border-white/10 bg-[#161b22] p-6 max-w-md text-center shadow-xl">
              <AlertTriangle className="w-8 h-8 mx-auto mb-3 text-red-400" />
              <p className="text-sm text-slate-300">{error || 'Konsol bağlantısı kapandı'}</p>
              <button
                type="button"
                onClick={() => connect()}
                className="mt-4 text-xs px-3 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-white"
              >
                Yeniden dene
              </button>
            </div>
          </div>
        )}
        {status === 'connecting' && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <Loader2 className="w-8 h-8 text-violet-400 animate-spin" />
          </div>
        )}
      </div>
    </div>
  )
}

export default OpenShiftVmConsolePage
