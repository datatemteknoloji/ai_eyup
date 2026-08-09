/**
 * KubeVirt serial console — tam ekran xterm (SSH terminal ile aynı UX).
 * Bağlantı: ainew WS proxy → cluster /console subresource.
 * KubeVirt yalnızca binary WebSocket frame kabul eder.
 */
import React, { useEffect, useRef, useCallback } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import '@xterm/xterm/css/xterm.css'

const encoder = new TextEncoder()

const OpenShiftVmConsolePage: React.FC = () => {
  const { clusterId, namespace, name } = useParams<{
    clusterId: string
    namespace: string
    name: string
  }>()
  const [searchParams] = useSearchParams()
  const title = searchParams.get('title') || `${namespace}/${name}`

  useEffect(() => {
    document.title = `Console — ${title}`
  }, [title])

  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<Terminal | null>(null)
  const fitRef = useRef<FitAddon | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const statusRef = useRef<HTMLSpanElement | null>(null)

  const setStatus = (msg: string, color: string) => {
    if (statusRef.current) {
      statusRef.current.textContent = msg
      statusRef.current.style.color = color
    }
  }

  const connect = useCallback(() => {
    if (!containerRef.current || !clusterId || !namespace || !name) return

    if (wsRef.current) wsRef.current.close()
    if (termRef.current) termRef.current.dispose()

    const term = new Terminal({
      cursorBlink: true,
      theme: {
        background: '#0d1117',
        foreground: '#c9d1d9',
        cursor: '#58a6ff',
        selectionBackground: '#264f78',
        black: '#0d1117', red: '#ff7b72',
        green: '#3fb950', yellow: '#d29922',
        blue: '#58a6ff', magenta: '#bc8cff',
        cyan: '#39c5cf', white: '#b1bac4',
        brightBlack: '#6e7681', brightWhite: '#f0f6fc',
      },
      fontFamily: "'Cascadia Code', 'JetBrains Mono', 'Fira Code', Menlo, Consolas, monospace",
      fontSize: 14,
      lineHeight: 1.2,
      scrollback: 10000,
    })

    const fitAddon = new FitAddon()
    term.loadAddon(fitAddon)
    term.loadAddon(new WebLinksAddon())
    term.open(containerRef.current)
    setTimeout(() => fitAddon.fit(), 50)

    termRef.current = term
    fitRef.current = fitAddon

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const jwt = localStorage.getItem('auth_token') || ''
    const path =
      `/api/v1/openshift/clusters/${clusterId}/kubevirt/vms/` +
      `${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/console`
    const wsUrl = `${proto}://${window.location.host}${path}?token=${encodeURIComponent(jwt)}`
    const ws = new WebSocket(wsUrl)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    setStatus('Bağlanılıyor…', '#58a6ff')

    ws.onopen = () => {
      setStatus('Bağlandı (serial console)', '#3fb950')
      document.title = `Console — ${title}`
      // getty uyandır — proxy de CR gönderir; istemci yedek
      try {
        ws.send(encoder.encode('\r'))
      } catch {
        /* ignore */
      }
    }

    ws.onmessage = (ev) => {
      if (ev.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(ev.data))
      } else if (typeof ev.data === 'string') {
        term.write(ev.data)
      }
    }

    ws.onclose = (ev) => {
      const detail = ev.code && ev.code !== 1000 ? ` (kod ${ev.code})` : ''
      setStatus(`Bağlantı kapatıldı${detail}`, '#d29922')
      term.write('\r\n\x1b[33m--- Bağlantı kapatıldı ---\x1b[0m\r\n')
    }

    ws.onerror = () => setStatus('Bağlantı hatası', '#ff7b72')

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(encoder.encode(data))
      }
    })

    const onResize = () => {
      fitAddon.fit()
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [clusterId, namespace, name, title])

  useEffect(() => {
    const cleanup = connect()
    return () => {
      cleanup?.()
      wsRef.current?.close()
      termRef.current?.dispose()
    }
  }, [connect])

  return (
    <div className="fixed inset-0 bg-[#0d1117] flex flex-col">
      <div className="flex items-center justify-between px-4 py-2 border-b border-white/10 bg-[#161b22]">
        <div className="text-sm text-slate-200 truncate">
          Serial console · <span className="text-white font-medium">{title}</span>
        </div>
        <div className="flex items-center gap-3">
          <span ref={statusRef} className="text-xs text-slate-400">…</span>
          <button
            type="button"
            onClick={() => connect()}
            className="text-xs px-2 py-1 rounded border border-white/15 text-slate-300 hover:bg-white/5"
          >
            Yeniden bağlan
          </button>
          <button
            type="button"
            onClick={() => window.close()}
            className="text-xs px-2 py-1 rounded border border-white/15 text-slate-300 hover:bg-white/5"
          >
            Kapat
          </button>
        </div>
      </div>
      <div ref={containerRef} className="flex-1 min-h-0 p-2" />
    </div>
  )
}

export default OpenShiftVmConsolePage
