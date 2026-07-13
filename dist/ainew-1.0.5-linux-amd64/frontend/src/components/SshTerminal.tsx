import React, { useEffect, useRef, useCallback } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import '@xterm/xterm/css/xterm.css'

interface Props {
  serverId: number
  serverName: string
  serverIp: string
  onClose: () => void
}

const SshTerminalModal: React.FC<Props> = ({ serverId, serverName, serverIp, onClose }) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef      = useRef<Terminal | null>(null)
  const fitRef       = useRef<FitAddon | null>(null)
  const wsRef        = useRef<WebSocket | null>(null)
  const isConnected  = useRef(false)

  const connect = useCallback(() => {
    if (!containerRef.current) return

    // xterm başlat
    const term = new Terminal({
      cols: 220,
      rows: 50,
      cursorBlink: true,
      theme: {
        background:  '#0d1117',
        foreground:  '#c9d1d9',
        cursor:      '#58a6ff',
        selectionBackground: '#264f78',
        black:       '#0d1117',
        red:         '#ff7b72',
        green:       '#3fb950',
        yellow:      '#d29922',
        blue:        '#58a6ff',
        magenta:     '#bc8cff',
        cyan:        '#39c5cf',
        white:       '#b1bac4',
        brightBlack: '#6e7681',
        brightWhite: '#f0f6fc',
      },
      fontFamily: "'Cascadia Code', 'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
      fontSize: 13,
      lineHeight: 1.2,
      scrollback: 5000,
    })

    const fitAddon      = new FitAddon()
    const webLinksAddon = new WebLinksAddon()
    term.loadAddon(fitAddon)
    term.loadAddon(webLinksAddon)
    term.open(containerRef.current)
    fitAddon.fit()

    termRef.current = term
    fitRef.current  = fitAddon

    // WebSocket bağlantısı — JWT token query param olarak gönderilir
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const token = localStorage.getItem('auth_token') || ''
    const wsUrl = `${proto}://${window.location.host}/api/v1/terminal/ws/${serverId}?token=${encodeURIComponent(token)}`
    const ws = new WebSocket(wsUrl)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      isConnected.current = true
    }

    ws.onmessage = (ev) => {
      if (ev.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(ev.data))
      } else {
        term.write(ev.data)
      }
    }

    ws.onclose = () => {
      isConnected.current = false
      term.write('\r\n\x1b[33mBağlantı kapatıldı.\x1b[0m\r\n')
    }

    ws.onerror = () => {
      term.write('\r\n\x1b[31mWebSocket bağlantı hatası.\x1b[0m\r\n')
    }

    // Kullanıcı girişi → WebSocket
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(new TextEncoder().encode(data))
      }
    })

    // Terminal yeniden boyutlandırma
    term.onResize(({ cols, rows }) => {
      if (ws.readyState === WebSocket.OPEN) {
        const msg = `\x01${cols},${rows}`
        ws.send(new TextEncoder().encode(msg))
      }
    })

  }, [serverId])

  // Pencere boyutu değişince yeniden fit
  useEffect(() => {
    const onResize = () => {
      fitRef.current?.fit()
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  useEffect(() => {
    connect()
    return () => {
      wsRef.current?.close()
      termRef.current?.dispose()
    }
  }, [connect])

  const handleClose = () => {
    wsRef.current?.close()
    termRef.current?.dispose()
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black/85" onClick={e => e.stopPropagation()}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-slate-800 border-b border-slate-700 flex-shrink-0">
        <div className="flex items-center gap-3">
          {/* Trafik ışıkları */}
          <div className="flex items-center gap-1.5">
            <button onClick={handleClose}
              className="w-3 h-3 rounded-full bg-red-500 hover:bg-red-400 transition-colors" title="Kapat" />
            <div className="w-3 h-3 rounded-full bg-yellow-500 opacity-50" />
            <div className="w-3 h-3 rounded-full bg-green-500 opacity-50" />
          </div>
          <span className="text-sm text-slate-300 font-medium font-mono">
            SSH — {serverName}
            <span className="text-slate-500 ml-2">{serverIp}</span>
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { termRef.current?.clear() }}
            className="text-xs text-slate-400 hover:text-white px-2 py-1 hover:bg-slate-700 rounded transition-colors"
          >
            Temizle
          </button>
          <button
            onClick={() => { wsRef.current?.close(); connect() }}
            className="text-xs text-slate-400 hover:text-white px-2 py-1 hover:bg-slate-700 rounded transition-colors"
          >
            Yeniden Bağlan
          </button>
          <button onClick={handleClose}
            className="text-slate-400 hover:text-white text-xl leading-none px-1 transition-colors">
            ×
          </button>
        </div>
      </div>

      {/* Terminal area */}
      <div className="flex-1 overflow-hidden p-2 bg-[#0d1117]">
        <div
          ref={containerRef}
          className="w-full h-full"
          style={{ minHeight: 0 }}
        />
      </div>
    </div>
  )
}

export default SshTerminalModal
