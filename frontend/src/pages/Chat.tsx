import React, { useState, useRef, useEffect, useLayoutEffect } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API_BASE_URL } from '../config/api'
import * as XLSX from 'xlsx'

function _cleanCell(raw: string): string {
  return raw
    // Markdown bold/italic
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/__(.+?)__/g, '$1')
    .replace(/_(.+?)_/g, '$1')
    // HTML <br> tags → newline for readability
    .replace(/<br\s*\/?>/gi, '\n')
    // Strip remaining HTML tags
    .replace(/<[^>]+>/g, '')
    // Unicode dashes → plain hyphen
    .replace(/[\u2013\u2014\u2015]/g, '-')
    .trim()
}

function _parseMdTable(mdTable: string): string[][] {
  const lines = mdTable.trim().split('\n').map(l => l.trim()).filter(Boolean)
  const rows: string[][] = []
  for (const line of lines) {
    if (line.startsWith('|') && line.endsWith('|')) {
      const cells = line.split('|').slice(1, -1).map(c => _cleanCell(c.trim()))
      if (cells.length > 0 && cells.some(c => c)) {
        const isSep = cells.every(c => /^:?-+:?$/.test(c))
        if (!isSep) rows.push(cells)
      }
    }
  }
  return rows
}

function downloadTableAsCsv(mdTable: string, filename = 'tablo.csv') {
  const rows = _parseMdTable(mdTable)
  if (rows.length === 0) return
  const csv = rows.map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n')
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}

function downloadTableAsXlsx(mdTable: string, filename = 'tablo.xlsx') {
  const rows = _parseMdTable(mdTable)
  if (rows.length === 0) return
  const ws = XLSX.utils.aoa_to_sheet(rows)
  // Sütun genişliklerini otomatik ayarla (stil kütüphane gerektirdiğinden sadece genişlik)
  ws['!cols'] = rows[0].map((_, ci) => ({
    wch: Math.max(...rows.map(r => String(r[ci] || '').replace(/\n/g, ' ').length), 12)
  }))
  // Freeze ilk satır (header)
  ws['!freeze'] = { xSplit: 0, ySplit: 1, activeCell: 'A2', sqref: 'A2' }
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, 'Tablo')
  XLSX.writeFile(wb, filename)
}

function getFirstMarkdownTable(content: string): string | null {
  const lines = content.split('\n')
  let start = -1
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim().startsWith('|') && lines[i].trim().endsWith('|')) { start = i; break }
  }
  if (start === -1) return null
  const out: string[] = []
  for (let i = start; i < lines.length; i++) {
    const line = lines[i].trim()
    if (!line.startsWith('|')) break
    out.push(line)
  }
  return out.length > 0 ? out.join('\n') : null
}

interface Server { id: number; name: string; ip_address: string; ai_ready: boolean; status: string }
interface Hypervisor { id: number; name: string; type?: string; hostname?: string; ip_address?: string }
interface Message { id: number; role: 'user' | 'assistant'; content: string; created_at: string }
interface ChatSession { id: number; title: string; server_ids: number[]; created_at: string; updated_at?: string; message_count: number }
interface AIModel { name: string; size: number; parameter_size: string; family: string }

const ThinkingDots = () => (
  <div className="flex items-center gap-1 py-1">
    {[0, 150, 300].map(d => (
      <div key={d} className="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: `${d}ms` }} />
    ))}
  </div>
)

const StreamingText = ({ text }: { text: string }) => (
  <div className="chat-response-content text-sm leading-relaxed prose prose-invert prose-sm max-w-none prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5">
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        table: ({ children }) => (
          <div className="overflow-x-auto my-3 rounded-lg border border-slate-500 shadow-sm">
            <table className="min-w-full text-left text-sm border-collapse">{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead className="bg-white/[0.05]">{children}</thead>,
        th: ({ children }) => <th className="px-4 py-2.5 font-semibold text-slate-100 border-b border-slate-500 whitespace-nowrap">{children}</th>,
        td: ({ children }) => <td className="px-4 py-2 text-slate-200 border-b border-white/[0.06] whitespace-nowrap">{children}</td>,
        tr: ({ children, ...props }) => <tr className="even:bg-white/[0.02] hover:bg-white/[0.04] transition-colors" {...props}>{children}</tr>,
        code: ({ className, children }) => className
          ? <code className={className}>{children}</code>
          : <code className="bg-white/[0.08] px-1.5 py-0.5 rounded text-xs">{children}</code>,
        pre: ({ children }) => <pre className="bg-cyber-deep border border-white/[0.08] rounded-lg p-3 overflow-x-auto text-xs my-2">{children}</pre>
      }}
    >{text}</ReactMarkdown>
    <span className="inline-block w-1.5 h-4 bg-blue-400 animate-pulse ml-0.5 align-text-bottom rounded-sm" />
  </div>
)

const ConfirmDialog: React.FC<{
  open: boolean
  message: string
  onConfirm: () => void
  onCancel: () => void
}> = ({ open, message, onConfirm, onCancel }) => {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-cyber-card border border-white/[0.08] rounded-[10px] shadow-2xl p-6 w-80 max-w-[90vw]">
        <p className="text-sm text-slate-200 mb-6 text-center leading-relaxed">{message}</p>
        <div className="flex gap-3 justify-center">
          <button onClick={onCancel}
            className="flex-1 px-4 py-2 rounded-lg text-sm bg-white/[0.07] hover:bg-white/[0.12] text-slate-300 transition-colors">
            İptal
          </button>
          <button onClick={() => { onConfirm(); onCancel() }}
            className="flex-1 px-4 py-2 rounded-lg text-sm bg-red-600 hover:bg-red-500 text-white font-medium transition-colors">
            Sil
          </button>
        </div>
      </div>
    </div>
  )
}

const Chat: React.FC = () => {
  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null)
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [selectedServers, setSelectedServers] = useState<number[]>([])
  const [serverSearch, setServerSearch] = useState('')
  const [serverDropdownOpen, setServerDropdownOpen] = useState(false)
  const [selectedHypervisors, setSelectedHypervisors] = useState<number[]>([])
  const [hypervisorSearch, setHypervisorSearch] = useState('')
  const [hypervisorDropdownOpen, setHypervisorDropdownOpen] = useState(false)
  const [_suppressAutoCreate, setSuppressAutoCreate] = useState(false)
  const [selectedModel, setSelectedModel] = useState<string>(() => localStorage.getItem('chat_selected_model') || 'llama3:70b')
  const [useRag, setUseRag] = useState<boolean>(true)
  const [pendingUserMessage, setPendingUserMessage] = useState<string | null>(null)
  const [streamingText, setStreamingText] = useState<string>('')
  const [thinkingPhase, setThinkingPhase] = useState<'idle' | 'context' | 'streaming'>('idle')
  const [confirmDialog, setConfirmDialog] = useState<{
    open: boolean
    message: string
    onConfirm: () => void
  }>({ open: false, message: '', onConfirm: () => {} })
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const serverDropdownRef = useRef<HTMLDivElement>(null)
  const hypervisorDropdownRef = useRef<HTMLDivElement>(null)
  const serverBtnRef = useRef<HTMLButtonElement>(null)
  const hypervisorBtnRef = useRef<HTMLButtonElement>(null)
  const serverMenuRef = useRef<HTMLDivElement>(null)
  const hypervisorMenuRef = useRef<HTMLDivElement>(null)
  const [serverMenuRect, setServerMenuRect] = useState<{top:number;left:number;width:number}|null>(null)
  const [hypervisorMenuRect, setHypervisorMenuRect] = useState<{top:number;left:number;width:number}|null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const streamSessionRef = useRef<number | null>(null)  // hangi session için stream çalışıyor

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const t = e.target as Node
      if (
        serverDropdownRef.current && !serverDropdownRef.current.contains(t) &&
        serverMenuRef.current && !serverMenuRef.current.contains(t)
      ) { setServerDropdownOpen(false); setServerMenuRect(null) }
      if (
        hypervisorDropdownRef.current && !hypervisorDropdownRef.current.contains(t) &&
        hypervisorMenuRef.current && !hypervisorMenuRef.current.contains(t)
      ) { setHypervisorDropdownOpen(false); setHypervisorMenuRect(null) }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Reposition portals on scroll/resize
  useLayoutEffect(() => {
    if (!serverDropdownOpen) return
    const update = () => {
      const el = serverBtnRef.current; if (!el) return
      const r = el.getBoundingClientRect()
      setServerMenuRect({ top: r.bottom + 4, left: r.left, width: Math.max(r.width, 320) })
    }
    update()
    window.addEventListener('scroll', update, true); window.addEventListener('resize', update)
    return () => { window.removeEventListener('scroll', update, true); window.removeEventListener('resize', update) }
  }, [serverDropdownOpen])

  useLayoutEffect(() => {
    if (!hypervisorDropdownOpen) return
    const update = () => {
      const el = hypervisorBtnRef.current; if (!el) return
      const r = el.getBoundingClientRect()
      setHypervisorMenuRect({ top: r.bottom + 4, left: r.left, width: Math.max(r.width, 320) })
    }
    update()
    window.addEventListener('scroll', update, true); window.addEventListener('resize', update)
    return () => { window.removeEventListener('scroll', update, true); window.removeEventListener('resize', update) }
  }, [hypervisorDropdownOpen])

  const queryClient = useQueryClient()

  const { data: servers = [] } = useQuery<Server[]>({
    queryKey: ['ai-ready-servers'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/servers/ai-ready/list`)
      if (!res.ok) throw new Error('Failed')
      return res.json()
    }
  })

  const { data: hypervisors = [] } = useQuery<Hypervisor[]>({
    queryKey: ['hypervisors'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/hypervisors/`)
      if (!res.ok) {
        console.warn('Hypervisors fetch failed', res.status)
        return []
      }
      return res.json()
    },
    retry: 1,
  })

  const { data: modelsData } = useQuery<{ success: boolean; models: AIModel[]; default: string }>({
    queryKey: ['ai-models'],
    queryFn: async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/chat/models`, { signal: AbortSignal.timeout(5000) })
        if (!res.ok) return { success: false, models: [], default: 'llama3.2:3b' }
        return res.json()
      } catch { return { success: false, models: [], default: 'llama3.2:3b' } }
    },
    retry: false, staleTime: 60000
  })

  const availableModels: AIModel[] =
    modelsData?.models?.length
      ? modelsData.models
      : [
          { name: 'llama3.2:3b', size: 0, parameter_size: '3.2B', family: 'llama' },
          { name: 'llama3.1:8b', size: 0, parameter_size: '8.0B', family: 'llama' },
          { name: 'qwen2.5:7b', size: 0, parameter_size: '7.6B', family: 'qwen2' },
          { name: 'qwen:latest', size: 0, parameter_size: '4B', family: 'qwen2' },
          { name: 'llama3:70b', size: 0, parameter_size: '70.6B', family: 'llama' }
        ]

  const { data: sessions = [], refetch: refetchSessions } = useQuery<ChatSession[]>({
    queryKey: ['chat-sessions'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/chat/sessions`)
      if (!res.ok) throw new Error('Failed')
      return res.json()
    }
  })

  const { data: messages = [], refetch: refetchMessages } = useQuery<Message[]>({
    queryKey: ['chat-messages', selectedSessionId],
    queryFn: async () => {
      if (!selectedSessionId) return []
      const res = await fetch(`${API_BASE_URL}/chat/sessions/${selectedSessionId}/messages`)
      if (!res.ok) throw new Error('Failed')
      return res.json()
    },
    enabled: selectedSessionId !== null
  })

  const createSessionMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/chat/sessions`, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
      if (!res.ok) throw new Error('Failed')
      return res.json()
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
      abortRef.current?.abort()
      setIsLoading(false)
      setStreamingText('')
      setPendingUserMessage(null)
      setThinkingPhase('idle')
      setSelectedSessionId(data.id)
      setInput('')
      setSuppressAutoCreate(false)
    }
  })

  const deleteSessionMutation = useMutation({
    mutationFn: async (sessionId: number) => {
      const res = await fetch(`${API_BASE_URL}/chat/sessions/${sessionId}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('Failed')
    },
    onSuccess: (_: unknown, sessionId: number) => {
      queryClient.setQueryData<ChatSession[]>(['chat-sessions'], prev => (prev ?? []).filter(s => s.id !== sessionId))
      queryClient.removeQueries({ queryKey: ['chat-messages', sessionId] })
      if (selectedSessionId === sessionId) setSelectedSessionId(null)
    }
  })

  const clearAllSessionsMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/chat/sessions`, { method: 'DELETE' })
      if (!res.ok) throw new Error('Failed')
    },
    onSuccess: () => {
      queryClient.setQueryData<ChatSession[]>(['chat-sessions'], [])
      queryClient.removeQueries({ queryKey: ['chat-messages'] })
      setSelectedSessionId(null)
      setSuppressAutoCreate(true)
    }
  })

  const scrollToBottom = () => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  useEffect(() => { scrollToBottom() }, [messages, streamingText])

  useEffect(() => {
    if (sessions.length > 0 && selectedSessionId === null) {
      setSelectedSessionId(sessions[0].id)
      setSuppressAutoCreate(true)
    }
  }, [sessions, selectedSessionId])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return

    const messageText = input
    setInput('')  // Gönderilince anında temizle
    // SSH: log/process/config + OS/kernel/sistem bilgisi sorularında tetiklenir
    const SSH_ONLY_KEYWORDS = ['log','journal','proses','process','config','konfigür',
      '/etc/','/var/','systemctl','servis restart','service restart','kurulu','paket','version',
      'vmstat','iostat','1 dakika','1 dak','derin analiz','benchmark','io performans',
      'os','işletim','kernel','revision','revizyon','sürüm','release','versiyon','distro',
      'rhel','centos','ubuntu','debian','oracle','servis','service','hostname',
      'selinux','sestatus','getenforce','firewall','firewalld','iptables','güvenlik','security',
      'uname','kernel versiyonu','çekirdek versiyonu']
    const needsSsh = SSH_ONLY_KEYWORDS.some(k => messageText.toLowerCase().includes(k))
    setIsLoading(true)
    setPendingUserMessage(messageText)
    setStreamingText('')
    setThinkingPhase(needsSsh ? 'context' : 'streaming')

    const ctrl = new AbortController()
    abortRef.current = ctrl
    // Bu isteğin başladığı session — done gelince hâlâ aynı session'da mıyız?
    const startSessionId = selectedSessionId
    streamSessionRef.current = selectedSessionId

    try {
      const res = await fetch(`${API_BASE_URL}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: messageText,
          session_id: selectedSessionId,
          server_ids: selectedServers.length > 0 ? selectedServers : undefined,
          hypervisor_ids: selectedHypervisors.length > 0 ? selectedHypervisors : undefined,
          model: selectedModel,
          use_rag: useRag
        }),
        signal: ctrl.signal
      })

      if (!res.ok || !res.body) {
        throw new Error(`HTTP ${res.status}`)
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let accumulated = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const jsonStr = line.slice(6).trim()
          if (!jsonStr) continue
          try {
            const chunk = JSON.parse(jsonStr)
            if (chunk.start) {
              if (chunk.session_id && chunk.session_id !== selectedSessionId) {
                setSelectedSessionId(chunk.session_id)
              }
              setThinkingPhase('streaming')
            }
            if (chunk.token) {
              accumulated += chunk.token
              setStreamingText(accumulated)
            }
            if (chunk.error) {
              setStreamingText(`❌ Hata: ${chunk.error}`)
              setThinkingPhase('idle')
            }
            if (chunk.done) {
              setThinkingPhase('idle')
              // Sadece hâlâ aynı session'daysa güncelle — karışmaması için
              if (startSessionId === selectedSessionId || chunk.session_id === selectedSessionId) {
                await refetchMessages()
              }
              await refetchSessions()
              setStreamingText('')
              setPendingUserMessage(null)
              setInput('')
            }
            // Cache'den gelen yanıt: anında streaming gibi göster
            if (chunk.from_cache) {
              setThinkingPhase('streaming')
            }
          } catch { /* json parse error yoksay */ }
        }
      }
    } catch (err: any) {
      if (err?.name !== 'AbortError') {
        setStreamingText(`❌ Bağlantı hatası. Tekrar deneyin.`)
      }
      setThinkingPhase('idle')
    } finally {
      setIsLoading(false)
      abortRef.current = null
    }
  }

  const handleAbort = () => {
    abortRef.current?.abort()
    setIsLoading(false)
    setThinkingPhase('idle')
    setStreamingText('')
    setPendingUserMessage(null)
  }

  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    return date.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })
  }

  const formatSessionDate = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const days = Math.floor((now.getTime() - date.getTime()) / 86400000)
    if (days === 0) return date.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })
    if (days === 1) return 'Dün'
    if (days < 7) return `${days} gün önce`
    return date.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' })
  }

  const aiReadyServers = servers.filter(s => s.ai_ready && s.status === 'ONLINE')
  const filteredAiReadyServers = aiReadyServers.filter(s => {
    if (!serverSearch) return true
    const q = serverSearch.toLowerCase()
    return s.name.toLowerCase().includes(q) || s.ip_address.toLowerCase().includes(q)
  })

  const filteredHypervisors = hypervisors.filter(h => {
    if (!hypervisorSearch) return true
    const q = hypervisorSearch.toLowerCase()
    return (h.name || '').toLowerCase().includes(q) || (h.hostname || '').toLowerCase().includes(q) || (h.ip_address || '').toLowerCase().includes(q)
  })

  const thinkingLabel =
    thinkingPhase === 'context' ? 'Bağlam hazırlanıyor (SSH / Prometheus)...' :
    thinkingPhase === 'streaming' ? 'Yanıt üretiliyor...' : ''

  return (
    <>
    <div className="flex flex-col h-screen overflow-hidden bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
      {/* Üst bar */}
      <div className="flex-shrink-0 p-4 bg-cyber-deep/80 backdrop-blur border-b border-white/[0.06]">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="px-3 py-1 rounded-full border border-cyan-500/40 bg-cyan-500/10 text-cyan-200 text-xs font-semibold">Modern UI v2</div>
          <label className="flex items-center gap-2 cursor-pointer">
            <span className="text-slate-400 text-sm font-medium">RAG:</span>
            <span className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${useRag ? 'bg-blue-600' : 'bg-white/[0.1]'}`}
              onClick={() => setUseRag(v => !v)} role="switch" aria-checked={useRag}>
              <span className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow transition duration-200 ${useRag ? 'translate-x-5' : 'translate-x-1'}`}
                style={{ marginTop: 2 }} />
            </span>
            <span className="text-slate-300 text-sm">{useRag ? 'Açık' : 'Kapalı'}</span>
          </label>

          <div className="flex items-center gap-2">
            <span className="text-slate-400 text-sm font-medium">Model:</span>
            <select value={selectedModel} onChange={e => { setSelectedModel(e.target.value); localStorage.setItem('chat_selected_model', e.target.value) }}
              className="px-4 py-2.5 bg-gradient-to-r from-blue-600 to-blue-700 border border-blue-500 rounded-xl text-white text-sm font-medium hover:from-blue-500 hover:to-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-400 cursor-pointer min-w-[200px]"
              style={{ appearance: 'auto' }}>
              {availableModels.map(m => (
                <option key={m.name} value={m.name} className="bg-cyber-deep text-white">
                  {m.name} {m.parameter_size ? `(${m.parameter_size})` : ''}
                </option>
              ))}
            </select>
          </div>

          <div className="relative" ref={serverDropdownRef}>
            <button ref={serverBtnRef} type="button"
              onClick={() => {
                if (serverDropdownOpen) { setServerDropdownOpen(false); setServerMenuRect(null) }
                else {
                  const r = serverBtnRef.current!.getBoundingClientRect()
                  setServerMenuRect({ top: r.bottom + 4, left: r.left, width: Math.max(r.width, 320) })
                  setServerDropdownOpen(true)
                }
              }}
              className="flex items-center gap-2 px-4 py-2.5 bg-cyber-card border border-white/[0.08] rounded-[10px] text-left min-w-[240px] hover:bg-white/[0.06] focus:outline-none focus:ring-2 focus:ring-blue-500">
              <span className="text-slate-300 text-sm">
                {selectedServers.length === 0 ? 'Sunucu seçin (çoklu)' : `${selectedServers.length} sunucu seçili`}
              </span>
              <span className="ml-auto text-slate-500">{serverDropdownOpen ? '▲' : '▼'}</span>
            </button>
            {serverDropdownOpen && serverMenuRect && createPortal(
              <div ref={serverMenuRef} className="flex flex-col overflow-hidden bg-cyber-card border border-white/[0.08] rounded-[10px] shadow-2xl"
                style={{ position:'fixed', top: serverMenuRect.top, left: serverMenuRect.left, width: serverMenuRect.width,
                  maxHeight: `min(20rem, calc(100vh - ${serverMenuRect.top}px - 8px))`, zIndex: 9999 }}>
                <div className="p-2 border-b border-white/[0.06] shrink-0">
                  <input type="text" value={serverSearch} onChange={e => setServerSearch(e.target.value)}
                    placeholder="Sunucu ara..." autoFocus
                    className="w-full bg-cyber-deep border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div className="flex items-center gap-2 p-2 border-b border-white/[0.06] shrink-0">
                  <button type="button" onClick={() => setSelectedServers(filteredAiReadyServers.map(s => s.id))}
                    className="text-xs text-blue-400 hover:text-blue-300 px-2 py-1 rounded">Tümünü seç</button>
                  <button type="button" onClick={() => setSelectedServers([])}
                    className="text-xs text-slate-400 hover:text-slate-300 px-2 py-1 rounded">Temizle</button>
                  <span className="text-xs text-slate-500 ml-auto">{filteredAiReadyServers.length} sunucu</span>
                </div>
                <div className="overflow-y-auto flex-1 min-h-0">
                  {filteredAiReadyServers.length === 0 ? (
                    <div className="p-4 text-center text-slate-500 text-sm">AI Ready sunucu yok</div>
                  ) : filteredAiReadyServers.map(s => (
                    <label key={s.id} className="flex items-center gap-3 px-4 py-2.5 hover:bg-white/[0.04] cursor-pointer">
                      <input type="checkbox" checked={selectedServers.includes(s.id)}
                        onChange={e => {
                          if (e.target.checked) setSelectedServers(prev => [...prev, s.id])
                          else setSelectedServers(prev => prev.filter(id => id !== s.id))
                        }}
                        className="rounded border-white/[0.2] bg-cyber-card text-blue-500 focus:ring-blue-500" />
                      <div>
                        <div className="text-white text-sm font-medium">{s.name}</div>
                        <div className="text-slate-500 text-xs font-mono">{s.ip_address}</div>
                      </div>
                    </label>
                  ))}
                </div>
              </div>,
              document.body
            )}
          </div>

          <div className="relative" ref={hypervisorDropdownRef}>
            <button ref={hypervisorBtnRef} type="button"
              onClick={() => {
                if (hypervisorDropdownOpen) { setHypervisorDropdownOpen(false); setHypervisorMenuRect(null) }
                else {
                  const r = hypervisorBtnRef.current!.getBoundingClientRect()
                  setHypervisorMenuRect({ top: r.bottom + 4, left: r.left, width: Math.max(r.width, 320) })
                  setHypervisorDropdownOpen(true)
                }
              }}
              className="flex items-center gap-2 px-4 py-2.5 bg-cyber-card border border-white/[0.08] rounded-[10px] text-left min-w-[240px] hover:bg-white/[0.06] focus:outline-none focus:ring-2 focus:ring-blue-500">
              <span className="text-slate-300 text-sm">
                {selectedHypervisors.length === 0 ? 'Hypervisor seçin (çoklu)' : `${selectedHypervisors.length} hypervisor seçili`}
              </span>
              <span className="ml-auto text-slate-500">{hypervisorDropdownOpen ? '▲' : '▼'}</span>
            </button>
            {hypervisorDropdownOpen && hypervisorMenuRect && createPortal(
              <div ref={hypervisorMenuRef} className="flex flex-col overflow-hidden bg-cyber-card border border-white/[0.08] rounded-[10px] shadow-2xl"
                style={{ position:'fixed', top: hypervisorMenuRect.top, left: hypervisorMenuRect.left, width: hypervisorMenuRect.width,
                  maxHeight: `min(20rem, calc(100vh - ${hypervisorMenuRect.top}px - 8px))`, zIndex: 9999 }}>
                <div className="p-2 border-b border-white/[0.06] shrink-0">
                  <input type="text" value={hypervisorSearch} onChange={e => setHypervisorSearch(e.target.value)}
                    placeholder="Hypervisor ara..." autoFocus
                    className="w-full bg-cyber-deep border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div className="flex items-center gap-2 p-2 border-b border-white/[0.06] shrink-0">
                  <button type="button" onClick={() => setSelectedHypervisors(filteredHypervisors.map(h => h.id))}
                    className="text-xs text-blue-400 hover:text-blue-300 px-2 py-1 rounded">Tümünü seç</button>
                  <button type="button" onClick={() => setSelectedHypervisors([])}
                    className="text-xs text-slate-400 hover:text-slate-300 px-2 py-1 rounded">Temizle</button>
                  <span className="text-xs text-slate-500 ml-auto">{filteredHypervisors.length} hypervisor</span>
                </div>
                <div className="overflow-y-auto flex-1 min-h-0">
                  {filteredHypervisors.length === 0 ? (
                    <div className="p-4 text-center text-slate-500 text-sm">Hypervisor yok</div>
                  ) : filteredHypervisors.map(h => (
                    <label key={h.id} className="flex items-center gap-3 px-4 py-2.5 hover:bg-white/[0.04] cursor-pointer">
                      <input type="checkbox" checked={selectedHypervisors.includes(h.id)}
                        onChange={e => {
                          if (e.target.checked) setSelectedHypervisors(prev => [...prev, h.id])
                          else setSelectedHypervisors(prev => prev.filter(id => id !== h.id))
                        }}
                        className="rounded border-white/[0.2] bg-cyber-card text-blue-500 focus:ring-blue-500" />
                      <div>
                        <div className="text-white text-sm font-medium">{h.name}</div>
                        <div className="text-slate-500 text-xs font-mono">{h.hostname || h.ip_address || '-'}</div>
                      </div>
                    </label>
                  ))}
                </div>
              </div>,
              document.body
            )}
          </div>
        </div>
      </div>

      <div className="flex flex-1 gap-4 p-4 overflow-hidden max-w-[1700px] w-full mx-auto">
        {/* Sol Panel - Oturumlar */}
        <div className="w-72 flex-shrink-0 bg-cyber-card backdrop-blur rounded-[10px] border border-white/[0.06] flex flex-col overflow-hidden shadow-2xl">
          <div className="p-3 border-b border-white/[0.06] flex items-center justify-between flex-shrink-0">
            <h3 className="text-sm font-medium text-slate-300">Chat Geçmişi</h3>
            <div className="flex items-center gap-1">
              <button onClick={() => createSessionMutation.mutate()}
                className="px-2 py-1 bg-blue-600 text-white text-xs rounded-lg hover:bg-blue-500">+ Yeni</button>
              {sessions.length > 0 && (
                <button onClick={() => setConfirmDialog({ open: true, message: 'Tüm chat geçmişi silinecek. Devam edilsin mi?', onConfirm: () => clearAllSessionsMutation.mutate() })}
                  className="px-2 py-1 bg-white/[0.05] text-slate-400 text-xs rounded-lg hover:bg-white/[0.08]">✕</button>
              )}
            </div>
          </div>
          <div className="overflow-y-auto flex-1 p-2">
            {sessions.length === 0 ? (
              <div className="text-center py-6 text-slate-500 text-xs">Henüz chat yok</div>
            ) : sessions.map(session => (
              <div key={session.id}
                className={`group flex items-center gap-2 px-3 py-2.5 rounded-lg cursor-pointer mb-1 transition-colors ${
                  selectedSessionId === session.id ? 'bg-blue-600/20 border border-blue-500/30' : 'hover:bg-white/[0.04]'
                }`}
                onClick={() => {
                  if (session.id !== selectedSessionId) {
                    abortRef.current?.abort()
                    setIsLoading(false)
                    setStreamingText('')
                    setPendingUserMessage(null)
                    setThinkingPhase('idle')
                  }
                  setSelectedSessionId(session.id)
                  setInput('')
                }}>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-slate-200 truncate">{session.title}</p>
                  <p className="text-[10px] text-slate-500 mt-0.5">
                    {session.message_count} mesaj · {formatSessionDate(session.updated_at || session.created_at)}
                  </p>
                </div>
                <button onClick={e => { e.stopPropagation(); setConfirmDialog({ open: true, message: 'Bu chat silinecek?', onConfirm: () => deleteSessionMutation.mutate(session.id) }) }}
                  className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-red-400 text-xs p-1 rounded transition-opacity">
                  ✕
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Sağ Panel */}
        <div className="flex-1 bg-cyber-card backdrop-blur rounded-[10px] border border-white/[0.06] flex flex-col overflow-hidden shadow-2xl">
          {/* Mesajlar */}
          <div className="flex-1 overflow-y-auto p-8">
            {selectedSessionId === null ? (
              <div className="h-full flex flex-col items-center justify-center">
                <div className="w-20 h-20 bg-gradient-to-br from-blue-500 to-blue-500 rounded-2xl flex items-center justify-center mb-6 shadow-lg shadow-blue-500/25">
                  <span className="text-2xl font-bold text-white">AI</span>
                </div>
                <h2 className="text-3xl font-bold text-white mb-2">AINE Assistant</h2>
                <p className="text-slate-400 text-center max-w-md">Bir chat session'ı seçin veya yeni bir chat başlatın.</p>
              </div>
            ) : (messages.length === 0 && !pendingUserMessage) ? (
              <div className="h-full flex flex-col items-center justify-center">
                <div className="w-20 h-20 bg-gradient-to-br from-blue-500 to-blue-500 rounded-2xl flex items-center justify-center mb-6 shadow-lg shadow-blue-500/25">
                  <span className="text-4xl">💬</span>
                </div>
                <h2 className="text-3xl font-bold text-white mb-2">Yeni Sohbet</h2>
                <p className="text-slate-400 text-center max-w-md mb-8">Sunucularınız hakkında sorular sorun, performans analizi isteyin veya komut çalıştırın.</p>
              </div>
            ) : (
              <div className="space-y-4">
                {[
                  ...messages,
                  ...(pendingUserMessage && streamSessionRef.current === selectedSessionId
                    ? [{ id: -1, role: 'user' as const, content: pendingUserMessage, created_at: new Date().toISOString() }]
                    : [])
                ].map(msg => (
                  <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[82%] rounded-3xl px-5 py-4 shadow-lg ${
                      msg.role === 'user'
                        ? 'bg-gradient-to-r from-blue-600 to-indigo-600 text-white border border-blue-400/30'
                        : 'bg-white/[0.06] text-slate-100 border border-white/[0.06]'
                    }`}>
                      {msg.role === 'user' ? (
                        <div className="whitespace-pre-wrap text-sm leading-relaxed">{msg.content}</div>
                      ) : (
                        <div className="chat-response-content text-sm leading-relaxed prose prose-invert prose-sm max-w-none prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5">
                          <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
                            table: ({ children }) => (
                              <div className="overflow-x-auto my-3 rounded-lg border border-slate-500 shadow-sm">
                                <table className="min-w-full text-left text-sm border-collapse">{children}</table>
                              </div>
                            ),
                            thead: ({ children }) => <thead className="bg-white/[0.05]">{children}</thead>,
                            th: ({ children }) => <th className="px-4 py-2.5 font-semibold text-slate-100 border-b border-slate-500 whitespace-nowrap">{children}</th>,
                            td: ({ children }) => <td className="px-4 py-2 text-slate-200 border-b border-white/[0.06] whitespace-nowrap">{children}</td>,
                            tr: ({ children, ...props }) => <tr className="even:bg-white/[0.02] hover:bg-white/[0.04] transition-colors" {...props}>{children}</tr>,
                            code: ({ className, children }) => className
                              ? <code className={className}>{children}</code>
                              : <code className="bg-white/[0.08] px-1.5 py-0.5 rounded text-xs">{children}</code>,
                            pre: ({ children }) => <pre className="bg-cyber-deep border border-white/[0.08] rounded-lg p-3 overflow-x-auto text-xs my-2">{children}</pre>
                          }}>{msg.content}</ReactMarkdown>
                          {getFirstMarkdownTable(msg.content) && (
                            <div className="mt-2 flex gap-2">
                              <button type="button"
                                onClick={() => downloadTableAsCsv(getFirstMarkdownTable(msg.content)!, 'tablo.csv')}
                                className="text-xs px-2 py-1.5 rounded bg-white/[0.07] hover:bg-white/[0.12] text-slate-200 border border-white/[0.1] flex items-center gap-1">
                                CSV İndir
                              </button>
                              <button type="button"
                                onClick={() => downloadTableAsXlsx(getFirstMarkdownTable(msg.content)!, 'tablo.xlsx')}
                                className="text-xs px-2 py-1.5 rounded bg-green-700/60 hover:bg-green-600/70 text-green-200 border border-green-600/50 flex items-center gap-1">
                                Excel İndir
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                      <div className={`text-xs mt-2 ${msg.role === 'user' ? 'text-blue-200' : 'text-slate-500'}`}>
                        {formatDate(msg.created_at)}
                      </div>
                    </div>
                  </div>
                ))}

                {/* Streaming / thinking area — sadece bu isteğin session'ı için göster */}
                {isLoading && streamSessionRef.current === selectedSessionId && (
                  <div className="flex justify-start">
                    <div className="bg-white/[0.06] rounded-[10px] px-4 py-3 max-w-[85%] w-full">
                      {thinkingPhase === 'context' && (
                        <div className="space-y-2">
                          <div className="flex items-center gap-2 text-xs text-slate-400">
                            <div className="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin flex-shrink-0" />
                            <span>{thinkingLabel}</span>
                          </div>
                          <ThinkingDots />
                        </div>
                      )}
                      {thinkingPhase === 'streaming' && streamingText && (
                        <div>
                          <div className="flex items-center gap-2 text-[10px] text-slate-500 mb-2">
                            <div className="w-2.5 h-2.5 border-2 border-green-400 border-t-transparent rounded-full animate-spin flex-shrink-0" />
                            <span>Yanıt üretiliyor...</span>
                          </div>
                          <StreamingText text={streamingText} />
                        </div>
                      )}
                      {thinkingPhase === 'streaming' && !streamingText && <ThinkingDots />}
                    </div>
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>
            )}
          </div>

          {/* Input */}
          <div className="px-6 py-5 border-t border-white/[0.06] bg-cyber-deep/80 backdrop-blur">
            {selectedServers.length > 0 && (
              <div className="mb-2 flex items-center space-x-2 flex-wrap gap-2">
                <span className="text-xs text-slate-400">Seçili sunucular:</span>
                {selectedServers.map(serverId => {
                  const server = aiReadyServers.find(s => s.id === serverId)
                  return server ? (
                    <span key={serverId}
                      className="inline-flex items-center px-2 py-1 bg-blue-600/20 text-blue-400 text-xs rounded border border-blue-500/30">
                      {server.name}
                      <button onClick={() => setSelectedServers(prev => prev.filter(id => id !== serverId))} className="ml-1 hover:text-blue-300">✕</button>
                    </span>
                  ) : null
                })}
              </div>
            )}
            {selectedHypervisors.length > 0 && (
              <div className="mb-2 flex items-center space-x-2 flex-wrap gap-2">
                <span className="text-xs text-slate-400">Seçili hypervisorlar:</span>
                {selectedHypervisors.map(hypervisorId => {
                  const hypervisor = hypervisors.find(h => h.id === hypervisorId)
                  return hypervisor ? (
                    <span key={hypervisorId}
                      className="inline-flex items-center px-2 py-1 bg-blue-600/20 text-blue-300 text-xs rounded border border-blue-500/30">
                      {hypervisor.name}
                      <button onClick={() => setSelectedHypervisors(prev => prev.filter(id => id !== hypervisorId))} className="ml-1 hover:text-blue-200">✕</button>
                    </span>
                  ) : null
                })}
              </div>
            )}
            <form onSubmit={handleSubmit} className="flex items-center space-x-3 bg-cyber-deep/80 border border-white/[0.08] rounded-2xl p-2">
              <div className="flex-1 relative">
                <input type="text" value={input} onChange={e => setInput(e.target.value)}
                  placeholder={isLoading ? 'AI düşünüyor...' : 'Mesajınızı yazın... (Enter ile gönder)'}
                  className={`w-full bg-transparent border rounded-xl px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors ${
                    isLoading ? 'border-blue-500/60' : 'border-white/[0.06]'
                  }`}
                  disabled={isLoading}
                />
                {isLoading && (
                  <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-1">
                    {[0,1,2].map(i => (
                      <div key={i} className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: `${i * 100}ms` }} />
                    ))}
                  </div>
                )}
              </div>
              {isLoading ? (
                <button type="button" onClick={handleAbort}
                  className="px-5 py-3 bg-rose-600/90 text-white rounded-xl hover:bg-rose-500 transition-all text-sm font-medium">
                  ⏹ Durdur
                </button>
              ) : (
                <button type="submit" disabled={!input.trim()}
                  className="px-6 py-3 bg-gradient-to-r from-cyan-600 to-blue-600 text-white rounded-xl hover:from-cyan-500 hover:to-blue-500 transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-cyan-500/25">
                  <span className="flex items-center gap-2">
                    <span>Gönder</span><span>→</span>
                  </span>
                </button>
              )}
            </form>
          </div>
        </div>
      </div>
    </div>
    <ConfirmDialog
      open={confirmDialog.open}
      message={confirmDialog.message}
      onConfirm={confirmDialog.onConfirm}
      onCancel={() => setConfirmDialog(d => ({ ...d, open: false }))}
    />
    </>
  )
}

export default Chat
