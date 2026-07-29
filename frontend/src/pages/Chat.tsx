import React, { useState, useRef, useEffect, useLayoutEffect } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API_BASE_URL } from '../config/api'
import type { PlatformKey } from '../config/platformAiops'
import * as XLSX from 'xlsx'
import ChatMetricChart, { type ChatChartPayload } from '../components/ChatMetricChart'
import { FileDown } from 'lucide-react'
import { exportChatMessagesToPrintWindow, exportMarkdownToPrintWindow } from '../utils/pdfExport'
import { ChatPlatformStatsBar } from '../components/ChatPlatformStatsBar'
import { chatMarkdownComponents, chatBubbleShell, chatResponseBody } from '../components/chatMarkdown'

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
interface Message { id: number; role: 'user' | 'assistant'; content: string; created_at: string; meta?: { charts?: ChatChartPayload[] } | null }
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
  <div className={chatResponseBody}>
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>{text}</ReactMarkdown>
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

const Chat: React.FC<{
  embedded?: boolean
  inventoryPlatform?: PlatformKey
  initialQuestion?: string | null
  onInitialQuestionUsed?: () => void
}> = ({ embedded, inventoryPlatform = 'linux', initialQuestion = null, onInitialQuestionUsed }) => {
  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null)
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [selectedServers, setSelectedServers] = useState<number[]>([])
  const [serverSearch, setServerSearch] = useState('')
  const [serverDropdownOpen, setServerDropdownOpen] = useState(false)
  const [_suppressAutoCreate, setSuppressAutoCreate] = useState(false)
  const [selectedModel, setSelectedModel] = useState<string>(() => localStorage.getItem('chat_selected_model') || 'llama3:70b')
  const [localInventoryMessages, setLocalInventoryMessages] = useState<Message[]>([])
  // Envanter NLQ UI kaldırıldı — doğal dil = canlı/agentic (Virt formu)
  const effectiveInventoryMode = false
  const [pendingUserMessage, setPendingUserMessage] = useState<string | null>(null)
  const [streamingText, setStreamingText] = useState<string>('')
  const [thinkingPhase, setThinkingPhase] = useState<'idle' | 'context' | 'streaming'>('idle')
  const [toolCalls, setToolCalls] = useState<{ tool: string; label: string; done: boolean }[]>([])
  const inventoryMsgSeq = useRef(-1000)


  const [confirmDialog, setConfirmDialog] = useState<{
    open: boolean
    message: string
    onConfirm: () => void
  }>({ open: false, message: '', onConfirm: () => {} })
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const serverDropdownRef = useRef<HTMLDivElement>(null)
  const serverBtnRef = useRef<HTMLButtonElement>(null)
  const serverMenuRef = useRef<HTMLDivElement>(null)
  const [serverMenuRect, setServerMenuRect] = useState<{top:number;left:number;width:number}|null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const streamSessionRef = useRef<number | null>(null)  // hangi session için stream çalışıyor
  const initialHandled = useRef(false)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const t = e.target as Node
      if (
        serverDropdownRef.current && !serverDropdownRef.current.contains(t) &&
        serverMenuRef.current && !serverMenuRef.current.contains(t)
      ) { setServerDropdownOpen(false); setServerMenuRect(null) }
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


  const queryClient = useQueryClient()

  const { data: servers = [] } = useQuery<Server[]>({
    queryKey: ['ai-ready-servers', inventoryPlatform],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/servers/ai-ready/list?platform=${inventoryPlatform}`)
      if (!res.ok) throw new Error('Failed')
      return res.json()
    }
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

  const { data: sessions = [], refetch: refetchSessions, isFetched: sessionsFetched } = useQuery<ChatSession[]>({
    queryKey: ['chat-sessions', inventoryPlatform],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/chat/sessions?category=${inventoryPlatform}`)
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
      const res = await fetch(`${API_BASE_URL}/chat/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category: inventoryPlatform }),
      })
      if (!res.ok) throw new Error('Failed')
      return res.json()
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['chat-sessions', inventoryPlatform] })
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
      queryClient.setQueryData<ChatSession[]>(['chat-sessions', inventoryPlatform], prev => (prev ?? []).filter(s => s.id !== sessionId))
      queryClient.removeQueries({ queryKey: ['chat-messages', sessionId] })
      if (selectedSessionId === sessionId) setSelectedSessionId(null)
    }
  })

  const clearAllSessionsMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/chat/sessions?category=${inventoryPlatform}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('Failed')
    },
    onSuccess: () => {
      queryClient.setQueryData<ChatSession[]>(['chat-sessions', inventoryPlatform], [])
      queryClient.removeQueries({ queryKey: ['chat-messages'] })
      setSelectedSessionId(null)
      setSuppressAutoCreate(true)
    }
  })

  const scrollToBottom = (force = false) => {
    const el = messagesContainerRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120
    if (force || nearBottom) el.scrollTop = el.scrollHeight
  }
  useEffect(() => { scrollToBottom() }, [messages, streamingText])

  useEffect(() => {
    if (sessions.length > 0 && selectedSessionId === null) {
      setSelectedSessionId(sessions[0].id)
      setSuppressAutoCreate(true)
    }
  }, [sessions, selectedSessionId])

  // İlk kullanım: hiç chat session'ı yoksa kullanıcıyı "seçim ekranında" bırakmak yerine
  // otomatik olarak yeni bir sohbet başlat ki doğrudan yazmaya başlayabilsin.
  useEffect(() => {
    if (sessionsFetched && sessions.length === 0 && selectedSessionId === null && !createSessionMutation.isPending) {
      createSessionMutation.mutate()
    }
  }, [sessionsFetched, sessions.length, selectedSessionId])

  const sendInventoryQuery = async (messageText: string) => {
    if (!messageText.trim() || isLoading) return
    setIsLoading(true)
    setPendingUserMessage(messageText)
    setStreamingText('')
    setThinkingPhase('streaming')
    const ctrl = new AbortController()
    abortRef.current = ctrl
    streamSessionRef.current = selectedSessionId
    const ts = new Date().toISOString()
    try {
      const liveHint = /canlı|simdi dogrula|şimdi doğrula|live check|ssh ile|ssh at|çalıştır|calistir|journalctl|systemctl|sestatus/i.test(messageText)
      const res = await fetch(`${API_BASE_URL}/ai/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: messageText,
          model: selectedModel,
          live_check: liveHint,
          server_ids: selectedServers.length ? selectedServers : undefined,
        }),
        signal: ctrl.signal,
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(data?.detail || `HTTP ${res.status}`)
      }
      let content = ''
      if (data.status === 'success') {
        content = data.answer_markdown || `_Sonuç yok._`
      } else if (data.status === 'unsupported') {
        content = `Bu soru mevcut envanter alanlarıyla cevaplanamıyor.\n\n${data.reason || ''}\n\n_İpucu: Teknik SSH/diagnostik için «Envanter sorgu»yu kapatın veya soruya «canlı doğrula» ekleyin._`
      } else if (data.status === 'invalid_query') {
        content = `Sorgu geçersiz: ${data.message || 'bilinmeyen hata'}${data.invalid_field ? ` (alan: ${data.invalid_field})` : ''}`
      } else {
        content = typeof data.detail === 'string' ? data.detail : JSON.stringify(data, null, 2)
      }
      const uid = inventoryMsgSeq.current--
      const aid = inventoryMsgSeq.current--
      setLocalInventoryMessages(prev => [
        ...prev,
        { id: uid, role: 'user', content: messageText, created_at: ts },
        { id: aid, role: 'assistant', content, created_at: new Date().toISOString() },
      ])
      setPendingUserMessage(null)
      setStreamingText('')
      setInput('')
    } catch (err: any) {
      if (err?.name !== 'AbortError') {
        const uid = inventoryMsgSeq.current--
        const aid = inventoryMsgSeq.current--
        setLocalInventoryMessages(prev => [
          ...prev,
          { id: uid, role: 'user', content: messageText, created_at: ts },
          { id: aid, role: 'assistant', content: `❌ Envanter sorgu hatası: ${err?.message || 'bilinmeyen'}`, created_at: new Date().toISOString() },
        ])
      }
      setPendingUserMessage(null)
    } finally {
      setIsLoading(false)
      setThinkingPhase('idle')
      abortRef.current = null
    }
  }

  /** Envanter modunda bile SSH/diagnostik sorularını normal Chat'e yönlendir */
  const looksLikeLiveTechQuestion = (text: string) => {
    const t = text.toLowerCase()
    const tech = [
      'ssh', 'journalctl', 'systemctl', 'sestatus', 'getenforce', 'sysctl', 'dmesg',
      'tcpdump', 'strace', 'perf ', 'iostat', 'vmstat', 'sar ', 'lsof', 'netstat', ' ss ',
      'df -', 'du -', 'free -', 'top', 'htop', 'ps aux', 'crontab', 'iptables', 'firewalld',
      'selinux', 'apparmor', 'kernel', 'oom', 'coredump', 'tracepath', 'mtr ',
      'neden', 'kök neden', 'kok neden', 'root cause', 'teşhis', 'teshis', 'diagnos',
      'log incele', 'loglara bak', 'çalıştır', 'calistir', 'komut', 'canlı doğrula', 'canli dogrula',
      'multipath', 'lvm', 'vgdisplay', 'pvdisplay', 'zfs', 'smartctl',
      'docker', 'kubectl', 'podman', 'container',
    ]
    return tech.some(k => t.includes(k.trim()))
  }

  const sendMessage = async (messageText: string) => {
    if (!messageText.trim() || isLoading) return
    if (effectiveInventoryMode && !looksLikeLiveTechQuestion(messageText)) {
      await sendInventoryQuery(messageText)
      return
    }
    // SSH: log/process/config + OS/kernel/sistem bilgisi + tanı komutları
    const SSH_ONLY_KEYWORDS = ['log','journal','proses','process','config','konfigür',
      '/etc/','/var/','systemctl','servis restart','service restart','kurulu','paket','version',
      'vmstat','iostat','1 dakika','1 dak','derin analiz','benchmark','io performans',
      'os','işletim','kernel','revision','revizyon','sürüm','release','versiyon','distro',
      'rhel','centos','ubuntu','debian','oracle','servis','service','hostname',
      'selinux','sestatus','getenforce','firewall','firewalld','iptables','güvenlik','security',
      'uname','kernel versiyonu','çekirdek versiyonu',
      'sysctl','swappiness','dmesg','tcpdump','strace','perf','lsof','ss ','netstat',
      'multipath','lvm','vgdisplay','oom','coredump','smartctl','crontab','nftables',
      'docker','podman','kubectl','container','neden','kök neden','teşhis','diagnos']
    const needsSsh = SSH_ONLY_KEYWORDS.some(k => messageText.toLowerCase().includes(k))
    setIsLoading(true)
    setPendingUserMessage(messageText)
    setStreamingText('')
    setToolCalls([])
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
          hypervisor_ids: undefined,
          model: selectedModel,
          use_rag: true,
          ephemeral: false,
          platform: inventoryPlatform,
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
            if (chunk.type === 'tool_call') {
              const tool = chunk.tool || ''
              const label = chunk.label || tool
              setToolCalls(prev => [...prev, { tool, label, done: false }])
            }
            if (chunk.type === 'tool_result') {
              const tool = chunk.tool || ''
              setToolCalls(prev => {
                const idx = [...prev].reverse().findIndex(t => t.tool === tool && !t.done)
                if (idx === -1) return prev
                const realIdx = prev.length - 1 - idx
                const next = [...prev]
                next[realIdx] = { ...next[realIdx], done: true }
                return next
              })
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

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return
    const messageText = input
    setInput('')  // Gönderilince anında temizle
    sendMessage(messageText)
  }

  useEffect(() => {
    if (initialQuestion && !initialHandled.current) {
      initialHandled.current = true
      sendMessage(initialQuestion)
      onInitialQuestionUsed?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuestion])

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
    if (Number.isNaN(date.getTime())) return '—'
    const now = new Date()
    const days = Math.floor((now.getTime() - date.getTime()) / 86400000)
    if (days <= 0) return date.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })
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


  const thinkingLabel =
    thinkingPhase === 'context' ? 'Bağlam hazırlanıyor (SSH / Prometheus)...' :
    thinkingPhase === 'streaming' ? 'Yanıt üretiliyor...' : ''

  return (
    <>
    <div className={`flex flex-col overflow-hidden bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 ${embedded ? 'h-full min-h-0' : '-m-5 h-[calc(100vh-3.5rem)] min-h-0'}`}>
      {/* Üst bar — Virt formu: model + opsiyonel hedef + PDF */}
      <div className="flex-shrink-0 p-3 bg-cyber-deep/80 backdrop-blur border-b border-white/[0.06]">
        <div className="flex items-center gap-3 flex-wrap">
          {messages.length > 0 && (
            <button
              type="button"
              onClick={() => exportChatMessagesToPrintWindow(messages, {
                title: inventoryPlatform === 'openshift' ? 'OpenShift AI' : inventoryPlatform === 'exadata' ? 'Exadata AI' : 'Linux AI',
                subtitle: new Date().toLocaleString('tr-TR'),
                filename: `${inventoryPlatform}_ai_${new Date().toISOString().slice(0, 10)}`,
              })}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-red-500/15 text-red-300 border border-red-500/30 hover:bg-red-500/25"
              title="Sohbeti PDF olarak kaydet"
            >
              <FileDown size={13} /> Sohbeti PDF
            </button>
          )}
          <div className="flex items-center gap-2">
            <span className="text-slate-400 text-sm font-medium">Model:</span>
            <select value={selectedModel} onChange={e => { setSelectedModel(e.target.value); localStorage.setItem('chat_selected_model', e.target.value) }}
              className="px-4 py-2 bg-slate-800 border border-slate-600 rounded-xl text-white text-sm font-medium hover:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-400 cursor-pointer min-w-[180px]"
              style={{ appearance: 'auto' }}>
              {availableModels.map(m => (
                <option key={m.name} value={m.name} className="bg-cyber-deep text-white">
                  {m.name} {m.parameter_size ? `(${m.parameter_size})` : ''}
                </option>
              ))}
            </select>
          </div>
          {inventoryPlatform === 'openshift' ? (
            <div className="px-3 py-2 bg-cyan-500/10 border border-cyan-500/30 rounded-xl text-sm text-cyan-300">
              OpenShift API
            </div>
          ) : (
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
              className="flex items-center gap-2 px-3 py-2 bg-slate-800/80 border border-slate-600/80 rounded-xl text-left min-w-[200px] hover:border-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500">
              <span className="text-slate-300 text-sm">
                {selectedServers.length === 0 ? 'Hedef (opsiyonel)' : `${selectedServers.length} sunucu`}
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
          )}
        </div>
      </div>
      <ChatPlatformStatsBar platform={inventoryPlatform} />

      <div className="flex flex-1 min-h-0 gap-4 p-4 overflow-hidden max-w-[1700px] w-full mx-auto">
        {/* Sol Panel - Oturumlar */}
        <div className="w-72 flex-shrink-0 bg-cyber-card backdrop-blur rounded-[10px] border border-white/[0.06] flex flex-col overflow-hidden shadow-2xl min-h-0">
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
          <div className="overflow-y-auto flex-1 min-h-0 p-2">
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
                    setLocalInventoryMessages([])
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
        <div className="flex-1 min-h-0 bg-cyber-card backdrop-blur rounded-[10px] border border-white/[0.06] flex flex-col overflow-hidden shadow-2xl">
          {/* Mesajlar */}
          <div ref={messagesContainerRef} className="flex-1 min-h-0 overflow-y-auto overscroll-contain p-8">
            {selectedSessionId === null ? (
              <div className="h-full flex flex-col items-center justify-center">
                <div className="w-20 h-20 bg-gradient-to-br from-blue-500 to-blue-500 rounded-2xl flex items-center justify-center mb-6 shadow-lg shadow-blue-500/25">
                  <span className="text-2xl font-bold text-white">AI</span>
                </div>
                <h2 className="text-3xl font-bold text-white mb-2">{
                  inventoryPlatform === 'openshift' ? 'OpenShift Asistanı' :
                  inventoryPlatform === 'exadata' ? 'Exadata Asistanı' :
                  'Linux Asistanı'
                }</h2>
                <p className="text-slate-400 text-center max-w-md">Bir chat session'ı seçin veya yeni bir chat başlatın.</p>
              </div>
            ) : (messages.length === 0 && localInventoryMessages.length === 0 && !pendingUserMessage) ? (
              <div className="h-full flex flex-col items-center justify-center">
                <div className="w-20 h-20 bg-gradient-to-br from-blue-500 to-blue-500 rounded-2xl flex items-center justify-center mb-6 shadow-lg shadow-blue-500/25">
                  <span className="text-4xl">💬</span>
                </div>
                <h2 className="text-3xl font-bold text-white mb-2">Altyapınızı Sorgulayın</h2>
                <p className="text-slate-400 text-center max-w-md mb-6">
                  {inventoryPlatform === 'openshift'
                    ? 'Pod, node, proje ve cluster durumu hakkında doğal dilde sorun.'
                    : inventoryPlatform === 'exadata'
                    ? 'Exadata node’ları hakkında doğal dilde sorun.'
                    : 'Sunucu durumu, performans, servis ve log sorularını doğal dilde sorun.'}
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {[
                  ...messages,
                  ...localInventoryMessages,
                  ...(pendingUserMessage && streamSessionRef.current === selectedSessionId
                    ? [{ id: -1, role: 'user' as const, content: pendingUserMessage, created_at: new Date().toISOString() }]
                    : [])
                ].map(msg => (
                  <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`${chatBubbleShell} ${
                      msg.role === 'user'
                        ? 'bg-gradient-to-r from-blue-600 to-indigo-600 text-white border border-blue-400/30'
                        : 'bg-white/[0.06] text-slate-100 border border-white/[0.06]'
                    }`}>
                      {msg.role === 'user' ? (
                        <div className="whitespace-pre-wrap text-sm leading-relaxed">{msg.content}</div>
                      ) : (
                        <div className={chatResponseBody}>
                          <ReactMarkdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>{msg.content}</ReactMarkdown>
                          <div className="mt-2 flex flex-wrap gap-2">
                            {msg.content?.trim().length > 40 && (
                              <button type="button"
                                onClick={() => exportMarkdownToPrintWindow(msg.content, {
                                  title: 'Linux AI Asistan Yanıtı',
                                  subtitle: msg.created_at ? new Date(msg.created_at).toLocaleString('tr-TR') : undefined,
                                  filename: `linux_yanit_${(msg.created_at || '').slice(0, 10) || 'export'}`,
                                })}
                                className="text-xs px-2 py-1.5 rounded bg-red-700/40 hover:bg-red-600/50 text-red-100 border border-red-500/40 flex items-center gap-1">
                                <FileDown size={12} /> PDF
                              </button>
                            )}
                            {getFirstMarkdownTable(msg.content) && (
                              <>
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
                              </>
                            )}
                          </div>
                          {msg.meta?.charts?.map((chart, ci) => (
                            <ChatMetricChart key={`${msg.id}-chart-${ci}`} chart={chart} chartId={`msg-${msg.id}-${ci}`} />
                          ))}
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
                      {toolCalls.length > 0 && (
                        <div className="space-y-1 mb-2">
                          {toolCalls.map((tc, i) => (
                            <div key={`${tc.tool}-${i}`} className="flex items-center gap-2 text-[11px] text-slate-500">
                              <span className={tc.done ? 'opacity-60' : 'animate-pulse'}>
                                🔧 {tc.label}{tc.done ? '' : '…'}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
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
            <form onSubmit={handleSubmit} className="flex items-center space-x-3 bg-cyber-deep/80 border border-white/[0.08] rounded-2xl p-2">
              <div className="flex-1 relative">
                <input type="text" value={input} onChange={e => setInput(e.target.value)}
                  placeholder={
                    isLoading ? 'AI düşünüyor...' :
                    'Altyapınızı sorgulayın… (Enter ile gönder)'
                  }
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
