import React, { useEffect, useRef, useCallback } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import '@xterm/xterm/css/xterm.css'

const TerminalPage: React.FC = () => {
  const { serverId } = useParams<{ serverId: string }>()
  const [searchParams] = useSearchParams()
  const serverName = searchParams.get('name') || `Server #${serverId}`
  const serverIp   = searchParams.get('ip')   || ''

  // Başlığı hemen set et
  useEffect(() => {
    document.title = `SSH — ${serverName}`
  }, [serverName])

  const containerRef = useRef<HTMLDivElement>(null)
  const termRef      = useRef<Terminal | null>(null)
  const fitRef       = useRef<FitAddon | null>(null)
  const wsRef        = useRef<WebSocket | null>(null)
  const statusRef    = useRef<HTMLSpanElement | null>(null)

  const setStatus = (msg: string, color: string) => {
    if (statusRef.current) {
      statusRef.current.textContent = msg
      statusRef.current.style.color = color
    }
  }

  const connect = useCallback(() => {
    if (!containerRef.current || !serverId) return

    // Önceki bağlantıyı temizle
    if (wsRef.current) {
      wsRef.current.close()
    }
    if (termRef.current) {
      termRef.current.dispose()
    }

    const term = new Terminal({
      cursorBlink: true,
      theme: {
        background:  '#0d1117',
        foreground:  '#c9d1d9',
        cursor:      '#58a6ff',
        selectionBackground: '#264f78',
        black:   '#0d1117', red:     '#ff7b72',
        green:   '#3fb950', yellow:  '#d29922',
        blue:    '#58a6ff', magenta: '#bc8cff',
        cyan:    '#39c5cf', white:   '#b1bac4',
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

    // Boyutlandır
    setTimeout(() => fitAddon.fit(), 50)

    termRef.current = term
    fitRef.current  = fitAddon

    // WebSocket
    const proto  = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const wsUrl  = `${proto}://${window.location.host}/api/v1/terminal/ws/${serverId}`
    const ws     = new WebSocket(wsUrl)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    setStatus('Bağlanılıyor...', '#58a6ff')

    ws.onopen = () => {
      setStatus('Bağlandı', '#3fb950')
      document.title = `SSH — ${serverName}`
    }

    ws.onmessage = (ev) => {
      if (ev.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(ev.data))
      } else {
        term.write(ev.data)
      }
    }

    ws.onclose = () => {
      setStatus('Bağlantı kapatıldı', '#d29922')
      term.write('\r\n\x1b[33m--- Bağlantı kapatıldı ---\x1b[0m\r\n')
    }

    ws.onerror = () => {
      setStatus('Hata', '#ff7b72')
      term.write('\r\n\x1b[31m--- WebSocket hatası ---\x1b[0m\r\n')
    }

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(new TextEncoder().encode(data))
      }
    })

    term.onResize(({ cols, rows }) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(new TextEncoder().encode(`\x01${cols},${rows}`))
      }
    })

  }, [serverId, serverName])

  // Pencere boyutu
  useEffect(() => {
    const onResize = () => fitRef.current?.fit()
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

  return (
    <div className="flex flex-col h-screen bg-[#0d1117] select-none">
      {/* Title bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-[#161b22] border-b border-slate-800 flex-shrink-0">
        <div className="flex items-center gap-3">
          {/* macOS dots */}
          <div className="flex gap-1.5">
            <button onClick={() => window.close()}
              className="w-3 h-3 rounded-full bg-red-500 hover:bg-red-400 transition-colors" />
            <div className="w-3 h-3 rounded-full bg-yellow-500 opacity-50 cursor-default" />
            <button onClick={() => { termRef.current?.clear(); fitRef.current?.fit() }}
              className="w-3 h-3 rounded-full bg-green-500 hover:bg-green-400 transition-colors" title="Ekranı Temizle" />
          </div>
          <span className="text-slate-300 text-sm font-medium font-mono">
            {serverName}
            {serverIp && <span className="text-slate-600 ml-2 text-xs">{serverIp}</span>}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span ref={statusRef} className="text-xs font-mono" style={{ color: '#58a6ff' }}>
            Bağlanılıyor...
          </span>
          <button
            onClick={connect}
            className="text-xs text-slate-500 hover:text-white px-2 py-1 hover:bg-slate-700 rounded transition-colors"
            title="Yeniden bağlan"
          >
            ↻ Yeniden Bağlan
          </button>
        </div>
      </div>

      {/* Terminal */}
      <div className="flex-1 overflow-hidden p-1.5 bg-[#0d1117]">
        <div ref={containerRef} className="w-full h-full" />
      </div>
    </div>
  )
}

export default TerminalPage
