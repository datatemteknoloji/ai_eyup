import React, { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import { API_BASE_URL } from '../config/api'

/** Markdown tablo metnini CSV'ye çevirip indir */
function downloadTableAsCsv(mdTable: string, filename = 'tablo.csv') {
  const lines = mdTable.trim().split('\n').map(l => l.trim()).filter(Boolean)
  const rows: string[][] = []
  for (const line of lines) {
    if (line.startsWith('|') && line.endsWith('|')) {
      const cells = line.split('|').slice(1, -1).map(c => c.trim())
      if (cells.length > 0 && cells.some(c => c)) {
        const isSeparator = cells.every(c => /^:?-+:?$/.test(c) || /^-+$/.test(c))
        if (!isSeparator) rows.push(cells)
      }
    }
  }
  if (rows.length === 0) return
  const csv = rows.map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n')
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/** İçerikte markdown tablo var mı (ilk tabloyu döndür) */
function getFirstMarkdownTable(content: string): string | null {
  const lines = content.split('\n')
  let start = -1
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim().startsWith('|') && lines[i].trim().endsWith('|')) {
      start = i
      break
    }
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

interface Server {
  id: number
  name: string
  ip_address: string
  ai_ready: boolean
  status: string
}

interface Message {
  id: number
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

interface ChatSession {
  id: number
  title: string
  server_ids: number[]
  created_at: string
  updated_at?: string
  message_count: number
}

interface AIModel {
  name: string
  size: number
  parameter_size: string
  family: string
}

const Chat: React.FC = () => {
  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null)
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [selectedServers, setSelectedServers] = useState<number[]>([])
  const [serverSearch, setServerSearch] = useState('')
  const [serverDropdownOpen, setServerDropdownOpen] = useState(false)
  const [_suppressAutoCreate, setSuppressAutoCreate] = useState(false)
  const [selectedModel, setSelectedModel] = useState<string>('llama3:70b')
  const [useRag, setUseRag] = useState<boolean>(true)
  const [pendingUserMessage, setPendingUserMessage] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const serverDropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (serverDropdownRef.current && !serverDropdownRef.current.contains(e.target as Node)) {
        setServerDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const queryClient = useQueryClient()

  // AI Ready sunucuları getir
  const { data: servers = [] } = useQuery<Server[]>({
    queryKey: ['ai-ready-servers'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/servers/ai-ready/list`)
      if (!response.ok) throw new Error('Failed to fetch servers')
      return response.json()
    }
  })

  // Ollama modellerini getir (hata olursa default kullan)
  const { data: modelsData } = useQuery<{ success: boolean; models: AIModel[]; default: string }>({
    queryKey: ['ai-models'],
    queryFn: async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/chat/models`, { timeout: 5000 } as any)
        if (!response.ok) {
          // DEV: console.warn(...)
          return {
            success: false,
            models: [],
            default: 'llama3.2:3b'
          }
        }
        return response.json()
      } catch (error) {
        // DEV: console.error(...)
        return {
          success: false,
          models: [],
          default: 'llama3.2:3b'
        }
      }
    },
    retry: false,
    staleTime: 60000 // 1 dakika cache
  })

  const availableModels: AIModel[] =
    modelsData?.models && modelsData.models.length > 0
      ? modelsData.models
      : [
          { name: 'llama3.2:3b', size: 0, parameter_size: '3.2B', family: 'llama' },
          { name: 'llama3.1:8b', size: 0, parameter_size: '8.0B', family: 'llama' },
          { name: 'qwen2.5:7b', size: 0, parameter_size: '7.6B', family: 'qwen2' },
          { name: 'qwen:latest', size: 0, parameter_size: '4B', family: 'qwen2' },
          { name: 'llama3:70b', size: 0, parameter_size: '70.6B', family: 'llama' }
        ]

  // Chat session'larını getir
  const { data: sessions = [], refetch: refetchSessions } = useQuery<ChatSession[]>({
    queryKey: ['chat-sessions'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/chat/sessions`)
      if (!response.ok) throw new Error('Failed to fetch sessions')
      return response.json()
    }
  })

  // Seçili session'ın mesajlarını getir
  const { data: messages = [], refetch: refetchMessages } = useQuery<Message[]>({
    queryKey: ['chat-messages', selectedSessionId],
    queryFn: async () => {
      if (!selectedSessionId) return []
      const response = await fetch(`${API_BASE_URL}/chat/sessions/${selectedSessionId}/messages`)
      if (!response.ok) throw new Error('Failed to fetch messages')
      return response.json()
    },
    enabled: selectedSessionId !== null
  })

  // Yeni session oluştur
  const createSessionMutation = useMutation({
    mutationFn: async () => {
      const response = await fetch(`${API_BASE_URL}/chat/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      })
      if (!response.ok) throw new Error('Failed to create session')
      return response.json()
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
      setSelectedSessionId(data.id)
      setSuppressAutoCreate(false)
    }
  })

  // Session sil
  const deleteSessionMutation = useMutation({
    mutationFn: async (sessionId: number) => {
      const response = await fetch(`${API_BASE_URL}/chat/sessions/${sessionId}`, {
        method: 'DELETE'
      })
      if (!response.ok) throw new Error('Failed to delete session')
    },
    onSuccess: (_: unknown, sessionId: number) => {
      // Listeden silinen session'ı hemen kaldır; refetch yapma, geri gelmesin
      queryClient.setQueryData<ChatSession[]>(['chat-sessions'], (prev: ChatSession[] | undefined) =>
        (prev ?? []).filter((s: ChatSession) => s.id !== sessionId)
      )
      queryClient.removeQueries({ queryKey: ['chat-messages', sessionId] })
      if (selectedSessionId === sessionId) {
        setSelectedSessionId(null)
      }
    }
  })

  const clearAllSessionsMutation = useMutation({
    mutationFn: async () => {
      const response = await fetch(`${API_BASE_URL}/chat/sessions`, {
        method: 'DELETE'
      })
      if (!response.ok) throw new Error('Failed to clear sessions')
    },
    onSuccess: () => {
      // Sadece cache güncelle; refetch yapma, silinenler geri gelmesin
      queryClient.setQueryData<ChatSession[]>(['chat-sessions'], [])
      queryClient.removeQueries({ queryKey: ['chat-messages'] })
      setSelectedSessionId(null)
      setSuppressAutoCreate(true)
    }
  })

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // İlk session'ı otomatik seç
  useEffect(() => {
    if (sessions.length > 0 && selectedSessionId === null) {
      // DEV: console.log(...)
      setSelectedSessionId(sessions[0].id)
      setSuppressAutoCreate(true)
    }
  }, [sessions, selectedSessionId])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return

    const messageText = input
    setInput('')
    setIsLoading(true)
    setPendingUserMessage(messageText)

    try {
      const response = await fetch(`${API_BASE_URL}/chat/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: messageText,
          session_id: selectedSessionId,
          server_ids: selectedServers.length > 0 ? selectedServers : undefined,
          model: selectedModel,
          use_rag: useRag
        })
      })

      const data = await response.json()

      if (response.ok) {
        if (data.session_id && data.session_id !== selectedSessionId) {
          setSelectedSessionId(data.session_id)
        }

        // Mesajları yenile (gönderilen mesaj artık sunucuda)
        await refetchMessages()
        await refetchSessions()
      } else {
        // DEV: console.error(...)
        alert(`Chat hatası: ${data.response || data.detail || 'Bilinmeyen hata'}`)
      }
    } catch (error) {
      // DEV: console.error(...)
    } finally {
      setIsLoading(false)
      setPendingUserMessage(null)
    }
  }

  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    return date.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })
  }

  const formatSessionDate = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    const days = Math.floor(diff / (1000 * 60 * 60 * 24))
    
    if (days === 0) {
      return date.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })
    } else if (days === 1) {
      return 'Dün'
    } else if (days < 7) {
      return `${days} gün önce`
    } else {
      return date.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' })
    }
  }

  // Sadece AI Ready ve ONLINE/WARNING sunucular - OFFLINE olanlari cikart
  // Sadece AI Ready ve ONLINE sunucular
  const aiReadyServers = servers.filter(s => s.ai_ready && s.status === 'ONLINE')
  const filteredAiReadyServers = aiReadyServers.filter(server => {
    if (!serverSearch) return true
    const search = serverSearch.toLowerCase()
    return server.name.toLowerCase().includes(search) || server.ip_address.toLowerCase().includes(search)
  })

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      {/* Sunucu ve Model seçimi */}
      <div className="flex-shrink-0 p-4 bg-slate-900 border-b border-slate-700">
        <div className="flex items-center gap-3 flex-wrap">
        {/* RAG Aç/Kapa */}
        <label className="flex items-center gap-2 cursor-pointer">
          <span className="text-slate-400 text-sm font-medium">📚 RAG:</span>
          <span className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-slate-900 ${useRag ? 'bg-blue-600' : 'bg-slate-600'}`}
            onClick={() => setUseRag(prev => !prev)}
            role="switch"
            aria-checked={useRag}
          >
            <span className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${useRag ? 'translate-x-5' : 'translate-x-1'}`}
              style={{ marginTop: 2 }}
            />
          </span>
          <span className="text-slate-300 text-sm">{useRag ? 'Açık' : 'Kapalı'}</span>
        </label>

        {/* Model Seçimi */}
        <div className="flex items-center gap-2">
          <span className="text-slate-400 text-sm font-medium">🤖 Model:</span>
          <select
            value={selectedModel}
            onChange={(e) => {
              const newModel = e.target.value
              // DEV: console.log(...)
              setSelectedModel(newModel)
            }}
            className="px-4 py-2.5 bg-gradient-to-r from-purple-600 to-purple-700 border border-purple-500 rounded-xl text-white text-sm font-medium hover:from-purple-500 hover:to-purple-600 focus:outline-none focus:ring-2 focus:ring-purple-400 cursor-pointer min-w-[200px]"
            style={{ appearance: 'auto' }}
          >
            {availableModels.map((m) => (
              <option key={m.name} value={m.name} className="bg-slate-900 text-white">
                {m.name} {m.parameter_size ? `(${m.parameter_size})` : ''}
              </option>
            ))}
          </select>
        </div>

        {/* Sunucu Seçimi */}
        <div className="relative" ref={serverDropdownRef}>
          <button
            type="button"
            onClick={() => setServerDropdownOpen(prev => !prev)}
            className="flex items-center gap-2 px-4 py-2.5 bg-slate-800 border border-slate-600 rounded-xl text-left min-w-[240px] hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <span className="text-slate-300 text-sm">
              {selectedServers.length === 0
                ? 'Sunucu seçin (çoklu)'
                : `${selectedServers.length} sunucu seçili`}
            </span>
            <span className="ml-auto text-slate-500">{serverDropdownOpen ? '▲' : '▼'}</span>
          </button>
          {serverDropdownOpen && (
            <div className="absolute top-full left-0 mt-1 w-80 max-h-80 overflow-hidden bg-slate-800 border border-slate-600 rounded-xl shadow-xl z-50 flex flex-col">
              <div className="p-2 border-b border-slate-700">
                <input
                  type="text"
                  value={serverSearch}
                  onChange={(e) => setServerSearch(e.target.value)}
                  placeholder="Sunucu ara..."
                  className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div className="flex items-center gap-2 p-2 border-b border-slate-700">
                <button
                  type="button"
                  onClick={() => {
                    setSelectedServers(filteredAiReadyServers.map(s => s.id))
                  }}
                  className="text-xs text-blue-400 hover:text-blue-300 px-2 py-1 rounded"
                >
                  Tümünü seç
                </button>
                <button
                  type="button"
                  onClick={() => setSelectedServers([])}
                  className="text-xs text-slate-400 hover:text-slate-300 px-2 py-1 rounded"
                >
                  Temizle
                </button>
                <span className="text-xs text-slate-500 ml-auto">
                  {filteredAiReadyServers.length} sunucu
                </span>
              </div>
              <div className="overflow-y-auto flex-1 p-2">
                {filteredAiReadyServers.length === 0 ? (
                  <div className="py-4 text-center text-slate-500 text-sm">Sunucu bulunamadı</div>
                ) : (
                  <div className="space-y-0.5">
                    {filteredAiReadyServers.map(server => (
                      <label
                        key={server.id}
                        className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer hover:bg-slate-700/50"
                      >
                        <input
                          type="checkbox"
                          checked={selectedServers.includes(server.id)}
                          onChange={() => {
                            setSelectedServers(prev =>
                              prev.includes(server.id)
                                ? prev.filter(id => id !== server.id)
                                : [...prev, server.id]
                            )
                          }}
                          className="h-4 w-4 text-blue-500 rounded border-slate-600 bg-slate-800 focus:ring-blue-500"
                        />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-white truncate">{server.name}</p>
                          <p className="text-xs text-slate-400 font-mono truncate">{server.ip_address}</p>
                        </div>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
        {selectedServers.length > 0 && (
          <span className="text-xs text-slate-400">
            Sohbet bu sunuculara göre yanıt verecek
          </span>
        )}
        </div>
      </div>

      {/* Ana Panel - Chat Sessions ve Mesajlar */}
      <div className="flex-1 flex gap-4 overflow-hidden p-4">
        {/* Sol Panel - Chat Session'ları */}
        <div className="w-64 bg-slate-800 rounded-xl border border-slate-700 flex flex-col overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-white">Chat Session'ları</h3>
            <div className="flex items-center gap-2">
              <button
                onClick={() => createSessionMutation.mutate()}
                disabled={createSessionMutation.isPending}
                className="px-2 py-1 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded transition-colors disabled:opacity-50"
                title="Yeni Chat"
              >
                +
              </button>
              <button
                onClick={() => {
                  if (confirm('Tüm chat sessionlarını silmek istediğinize emin misiniz?')) {
                    clearAllSessionsMutation.mutate()
                  }
                }}
                disabled={sessions.length === 0 || clearAllSessionsMutation.isPending}
                className="px-2 py-1 bg-red-600 hover:bg-red-700 text-white text-xs rounded transition-colors disabled:opacity-50"
                title="Tümünü Sil"
              >
                🗑️
              </button>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            {sessions.length === 0 ? (
              <div className="text-center py-8 text-slate-500 text-sm">
                <span className="text-2xl block mb-2">💬</span>
                Henüz chat session'ı yok
              </div>
            ) : (
              <div className="space-y-2">
                {sessions.map(session => (
                  <div
                    key={session.id}
                    className={`relative flex items-start space-x-2 p-3 rounded-lg cursor-pointer transition-all group ${
                      selectedSessionId === session.id
                        ? 'bg-blue-600 text-white'
                        : 'bg-slate-700/50 hover:bg-slate-700 text-slate-300'
                    }`}
                    onClick={() => setSelectedSessionId(session.id)}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">{session.title}</div>
                      <div className={`text-xs mt-1 ${selectedSessionId === session.id ? 'text-blue-100' : 'text-slate-400'}`}>
                        {session.message_count} mesaj
                      </div>
                      <div className={`text-xs ${selectedSessionId === session.id ? 'text-blue-100' : 'text-slate-500'}`}>
                        {formatSessionDate(session.updated_at || session.created_at)}
                      </div>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        if (confirm('Bu chat session\'ını silmek istediğinize emin misiniz?')) {
                          deleteSessionMutation.mutate(session.id)
                        }
                      }}
                      className={`opacity-0 group-hover:opacity-100 p-1 rounded transition-opacity ${
                        selectedSessionId === session.id ? 'hover:bg-white/20' : 'hover:bg-slate-600'
                      }`}
                      title="Sil"
                    >
                      <span className="text-xs">✕</span>
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Sağ Panel - Chat Mesajları */}
        <div className="flex-1 bg-slate-800 rounded-xl border border-slate-700 flex flex-col overflow-hidden">
        {/* Mesajlar */}
        <div className="flex-1 overflow-y-auto p-6">
          {selectedSessionId === null ? (
            <div className="h-full flex flex-col items-center justify-center">
              <div className="w-20 h-20 bg-gradient-to-br from-purple-500 to-blue-500 rounded-2xl flex items-center justify-center mb-6 shadow-lg shadow-purple-500/25">
                <span className="text-4xl">🤖</span>
              </div>
              <h2 className="text-2xl font-bold text-white mb-2">AI Asistan</h2>
              <p className="text-slate-400 text-center max-w-md">
                Bir chat session'ı seçin veya yeni bir chat başlatın.
              </p>
            </div>
          ) : (messages.length === 0 && !pendingUserMessage) ? (
            <div className="h-full flex flex-col items-center justify-center">
              <div className="w-20 h-20 bg-gradient-to-br from-purple-500 to-blue-500 rounded-2xl flex items-center justify-center mb-6 shadow-lg shadow-purple-500/25">
                <span className="text-4xl">💬</span>
              </div>
              <h2 className="text-2xl font-bold text-white mb-2">Yeni Konuşma</h2>
              <p className="text-slate-400 text-center max-w-md mb-8">
                Sunucularınız hakkında sorular sorun, performans analizi isteyin veya komut çalıştırın.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {[
                ...messages,
                ...(pendingUserMessage
                  ? [{ id: -1, role: 'user' as const, content: pendingUserMessage, created_at: new Date().toISOString() }]
                  : [])
              ].map(message => (
                <div
                  key={message.id}
                  className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                      message.role === 'user'
                        ? 'bg-gradient-to-r from-blue-600 to-blue-700 text-white'
                        : 'bg-slate-700 text-slate-200'
                    }`}
                  >
                    {message.role === 'user' ? (
                      <div className="whitespace-pre-wrap text-sm leading-relaxed">{message.content}</div>
                    ) : (
                      <div className="chat-response-content text-sm leading-relaxed prose prose-invert prose-sm max-w-none prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5">
                        <ReactMarkdown
                          components={{
                            table: ({ children }) => (
                              <div className="overflow-x-auto my-3 rounded-lg border border-slate-600">
                                <table className="min-w-full text-left text-sm border-collapse">{children}</table>
                              </div>
                            ),
                            thead: ({ children }) => <thead className="bg-slate-600/50">{children}</thead>,
                            th: ({ children }) => (
                              <th className="px-3 py-2 font-medium text-slate-200 border-b border-slate-600">{children}</th>
                            ),
                            td: ({ children }) => (
                              <td className="px-3 py-2 border-b border-slate-600/50">{children}</td>
                            ),
                            tr: ({ children }) => <tr>{children}</tr>,
                            code: ({ className, children }) =>
                              className ? (
                                <code className={className}>{children}</code>
                              ) : (
                                <code className="bg-slate-600/70 px-1.5 py-0.5 rounded text-xs">{children}</code>
                              ),
                            pre: ({ children }) => (
                              <pre className="bg-slate-900 border border-slate-600 rounded-lg p-3 overflow-x-auto text-xs my-2">{children}</pre>
                            )
                          }}
                        >
                          {message.content}
                        </ReactMarkdown>
                        {getFirstMarkdownTable(message.content) && (
                          <button
                            type="button"
                            onClick={() => downloadTableAsCsv(getFirstMarkdownTable(message.content)!, 'tablo.csv')}
                            className="mt-2 text-xs px-2 py-1.5 rounded bg-slate-600 hover:bg-slate-500 text-slate-200 border border-slate-500"
                          >
                            📥 CSV / Excel olarak indir
                          </button>
                        )}
                      </div>
                    )}
                    <div className={`text-xs mt-2 ${
                      message.role === 'user' ? 'text-blue-200' : 'text-slate-500'
                    }`}>
                      {formatDate(message.created_at)}
                    </div>
                  </div>
                </div>
              ))}
              {isLoading && (
                <div className="flex justify-start">
                  <div className="bg-slate-700 rounded-2xl px-4 py-3">
                    <div className="flex items-center space-x-2">
                      <div className="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                      <div className="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                      <div className="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input */}
        <div className="px-6 py-4 border-t border-slate-700 bg-slate-900/50">
          {selectedServers.length > 0 && (
            <div className="mb-2 flex items-center space-x-2 flex-wrap gap-2">
              <span className="text-xs text-slate-400">Seçili sunucular:</span>
              {selectedServers.map(serverId => {
                const server = aiReadyServers.find(s => s.id === serverId)
                return server ? (
                  <span
                    key={serverId}
                    className="inline-flex items-center px-2 py-1 bg-blue-600/20 text-blue-400 text-xs rounded border border-blue-500/30"
                  >
                    {server.name}
                    <button
                      onClick={() => setSelectedServers(prev => prev.filter(id => id !== serverId))}
                      className="ml-1 hover:text-blue-300"
                    >
                      ✕
                    </button>
                  </span>
                ) : null
              })}
            </div>
          )}
          <form onSubmit={handleSubmit} className="flex items-center space-x-4">
            <div className="flex-1 relative">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Mesajınızı yazın..."
                className="w-full bg-slate-800 border border-slate-600 rounded-xl px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                disabled={isLoading}
              />
            </div>
            <button
              type="submit"
              disabled={isLoading || !input.trim()}
              className="px-6 py-3 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-xl hover:from-blue-500 hover:to-blue-600 transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-blue-500/25"
            >
              <span className="flex items-center">
                {isLoading ? (
                  <span className="animate-spin">⏳</span>
                ) : (
                  <>
                    <span>Gönder</span>
                    <span className="ml-2">→</span>
                  </>
                )}
              </span>
            </button>
          </form>
        </div>
        </div>
      </div>
    </div>
  )
}

export default Chat
