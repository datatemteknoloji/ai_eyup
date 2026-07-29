import React, { useState, useRef, useEffect, useLayoutEffect } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API_BASE_URL } from '../config/api'
import type { PlatformKey } from '../config/platformAiops'
import * as XLSX from 'xlsx'
import ChatMetricChart, { type ChatChartPayload } from '../components/ChatMetricChart'
import { FileDown, Server as ServerIcon, Boxes, Layers } from 'lucide-react'
import { exportChatMessagesToPrintWindow, exportMarkdownToPrintWindow } from '../utils/pdfExport'
import { ChatPlatformStatsBar } from '../components/ChatPlatformStatsBar'
import { chatMarkdownComponents, chatResponseBody } from '../components/chatMarkdown'
import {
  NlChatRoot,
  NlHistorySidebar,
  NlChatPanel,
  NlTopBar,
  NlModelSelect,
  NlEmptyState,
  NlChatInput,
  nlUserBubbleClass,
  nlAssistantBubbleClass,
} from '../components/nlChatUi'

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

  const aiReadyServers = servers.filter(s => s.ai_ready && s.status === 'ONLINE')
  const filteredAiReadyServers = aiReadyServers.filter(s => {
    if (!serverSearch) return true
    const q = serverSearch.toLowerCase()
    return s.name.toLowerCase().includes(q) || s.ip_address.toLowerCase().includes(q)
  })


  const thinkingLabel =
    thinkingPhase === 'context' ? 'Bağlam hazırlanıyor (SSH / Prometheus)...' :
    thinkingPhase === 'streaming' ? 'Yanıt üretiliyor...' : ''

  const emptyDescription =
    inventoryPlatform === 'openshift'
      ? 'Pod, node, proje ve cluster durumu hakkında doğal dilde sorun.'
      : inventoryPlatform === 'exadata'
      ? 'Exadata node’ları hakkında doğal dilde sorun.'
      : 'Sunucu durumu, performans, servis ve log sorularını doğal dilde sorun.'

  const emptyIcon =
    inventoryPlatform === 'openshift' ? <Boxes size={24} className="text-white" /> :
    inventoryPlatform === 'exadata' ? <Layers size={24} className="text-white" /> :
    <ServerIcon size={24} className="text-white" />

  const hasMessages =
    messages.length > 0 ||
    localInventoryMessages.length > 0 ||
    (pendingUserMessage != null && streamSessionRef.current === selectedSessionId)

  const showEmpty = selectedSessionId === null || !hasMessages

  const pdfTitle =
    inventoryPlatform === 'openshift' ? 'OpenShift AI' :
    inventoryPlatform === 'exadata' ? 'Exadata AI' :
    'Linux AI'

  const handleSessionSelect = (id: number) => {
    if (id !== selectedSessionId) {
      abortRef.current?.abort()
      setIsLoading(false)
      setStreamingText('')
      setPendingUserMessage(null)
      setThinkingPhase('idle')
      setLocalInventoryMessages([])
    }
    setSelectedSessionId(id)
    setInput('')
  }

  return (
    <>
      <NlChatRoot embedded={embedded}>
        <NlHistorySidebar
          sessions={sessions}
          selectedId={selectedSessionId}
          onSelect={handleSessionSelect}
          onNew={() => createSessionMutation.mutate()}
          onDelete={id => setConfirmDialog({
            open: true,
            message: 'Bu chat silinecek?',
            onConfirm: () => deleteSessionMutation.mutate(id),
          })}
          onClearAll={() => setConfirmDialog({
            open: true,
            message: 'Tüm chat geçmişi silinecek. Devam edilsin mi?',
            onConfirm: () => clearAllSessionsMutation.mutate(),
          })}
        />
        <NlChatPanel>
          <NlTopBar>
            {messages.length > 0 && (
              <button
                type="button"
                onClick={() => exportChatMessagesToPrintWindow(messages, {
                  title: pdfTitle,
                  subtitle: new Date().toLocaleString('tr-TR'),
                  filename: `${inventoryPlatform}_ai_${new Date().toISOString().slice(0, 10)}`,
                })}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-red-500/15 text-red-300 border border-red-500/30 hover:bg-red-500/25"
                title="Sohbeti PDF olarak kaydet"
              >
                <FileDown size={13} /> Sohbeti PDF
              </button>
            )}
            <NlModelSelect
              value={selectedModel}
              onChange={setSelectedModel}
              models={availableModels}
              storageKey="chat_selected_model"
            />
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
          </NlTopBar>

          <ChatPlatformStatsBar platform={inventoryPlatform} />

          <div ref={messagesContainerRef} className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-4 py-4">
            {showEmpty ? (
              <NlEmptyState icon={emptyIcon} description={emptyDescription} />
            ) : (
              <div className="max-w-3xl mx-auto">
                {[
                  ...messages,
                  ...localInventoryMessages,
                  ...(pendingUserMessage && streamSessionRef.current === selectedSessionId
                    ? [{ id: -1, role: 'user' as const, content: pendingUserMessage, created_at: new Date().toISOString() }]
                    : [])
                ].map(msg => (
                  <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} mb-4`}>
                    <div className={msg.role === 'user' ? nlUserBubbleClass : nlAssistantBubbleClass}>
                      {msg.role === 'user' ? (
                        <div className="whitespace-pre-wrap leading-relaxed">{msg.content}</div>
                      ) : (
                        <div className={chatResponseBody}>
                          <ReactMarkdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>{msg.content}</ReactMarkdown>
                          <div className="mt-2 flex flex-wrap gap-2">
                            {msg.content?.trim().length > 40 && (
                              <button type="button"
                                onClick={() => exportMarkdownToPrintWindow(msg.content, {
                                  title: `${pdfTitle} Asistan Yanıtı`,
                                  subtitle: msg.created_at ? new Date(msg.created_at).toLocaleString('tr-TR') : undefined,
                                  filename: `${inventoryPlatform}_yanit_${(msg.created_at || '').slice(0, 10) || 'export'}`,
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

                {isLoading && streamSessionRef.current === selectedSessionId && (
                  <div className="flex justify-start mb-4">
                    <div className={nlAssistantBubbleClass}>
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

          <NlChatInput
            value={input}
            onChange={setInput}
            onSubmit={() => {
              if (!input.trim() || isLoading) return
              const messageText = input
              setInput('')
              sendMessage(messageText)
            }}
            onAbort={handleAbort}
            loading={isLoading}
            placeholder="Altyapınızı sorgulayın…"
            extra={selectedServers.length > 0 ? (
              <div className="mb-2 flex items-center flex-wrap gap-2">
                <span className="text-xs text-slate-400">Seçili sunucular:</span>
                {selectedServers.map(serverId => {
                  const server = aiReadyServers.find(s => s.id === serverId)
                  return server ? (
                    <span key={serverId}
                      className="inline-flex items-center px-2 py-1 bg-blue-600/20 text-blue-400 text-xs rounded border border-blue-500/30">
                      {server.name}
                      <button type="button" onClick={() => setSelectedServers(prev => prev.filter(id => id !== serverId))} className="ml-1 hover:text-blue-300">✕</button>
                    </span>
                  ) : null
                })}
              </div>
            ) : undefined}
          />
        </NlChatPanel>
      </NlChatRoot>
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
