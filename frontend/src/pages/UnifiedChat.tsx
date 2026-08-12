import React, { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API_BASE_URL } from '../config/api'
import { FileDown, Globe, Wrench } from 'lucide-react'
import { exportChatMessagesToPrintWindow, exportMarkdownToPrintWindow } from '../utils/pdfExport'
import { ChatPlatformStatsBar } from '../components/ChatPlatformStatsBar'
import ChatFeedbackButtons, { priorUserQuestion } from '../components/ChatFeedbackButtons'
import ChatPinFact from '../components/ChatPinFact'
import { chatMarkdownComponents, chatResponseBody } from '../components/chatMarkdown'
import {
  NlChatRoot, NlHistorySidebar, NlChatPanel, NlTopBar, NlModelSelect,
  NlModelUnavailableBanner,
  NlEmptyState, NlChatInput, nlUserBubbleClass, nlAssistantBubbleClass,
} from '../components/nlChatUi'
import {
  useChatStream,
  startChatStream,
  abortChatStream,
  clearChatClarify,
  loadPersistedSessionId,
  persistSessionId,
} from '../lib/chatStreamStore'

function _cleanCell(raw: string): string {
  return raw
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/__(.+?)__/g, '$1')
    .replace(/_(.+?)_/g, '$1')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]+>/g, '')
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

async function downloadTableAsXlsx(mdTable: string, filename = 'tablo.xlsx') {
  const rows = _parseMdTable(mdTable)
  if (rows.length === 0) return
  const XLSX = await import('xlsx')
  const ws = XLSX.utils.aoa_to_sheet(rows)
  ws['!cols'] = rows[0].map((_, ci) => ({
    wch: Math.max(...rows.map(r => String(r[ci] || '').replace(/\n/g, ' ').length), 12)
  }))
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

interface Message { id: number; role: 'user' | 'assistant'; content: string; created_at: string }
interface ChatSession { id: number; title: string; server_ids: number[]; created_at: string; updated_at?: string; message_count: number }
interface AIModel { name: string; size: number; parameter_size: string; family: string }

const ThinkingDots = () => (
  <div className="flex items-center gap-1 py-1">
    {[0, 150, 300].map(d => (
      <div key={d} className="w-2 h-2 bg-sky-400 rounded-full animate-bounce" style={{ animationDelay: `${d}ms` }} />
    ))}
  </div>
)

const StreamingText = ({ text }: { text: string }) => (
  <div className={chatResponseBody}>
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>{text}</ReactMarkdown>
    <span className="inline-block w-1.5 h-4 bg-sky-400 animate-pulse ml-0.5 align-text-bottom rounded-sm" />
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

const SUGGESTED_QUESTIONS = [
  'Genel altyapı durumunu özetle: Linux, Windows ve sanallaştırma',
  'Tüm sunucularda en yüksek CPU/RAM kullanan 5 sunucu hangisi?',
  'Linux ve Windows arasında güvenlik yaması durumu karşılaştırması yap',
  'Hangi sunucular AI Ready değil, neden?',
]

const UnifiedChat: React.FC<{
  embedded?: boolean
  initialQuestion?: string | null
  onInitialQuestionUsed?: () => void
}> = ({ embedded, initialQuestion = null, onInitialQuestionUsed }) => {
  const streamChannel = 'unified'
  const stream = useChatStream(streamChannel)
  const isLoading = stream.isLoading
  const pendingUserMessage = stream.pendingUserMessage
  const streamingText = stream.streamingText
  const thinkingPhase = stream.thinkingPhase
  const toolCalls = stream.toolCalls
  const clarifyOptions = stream.clarifyOptions

  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(() =>
    loadPersistedSessionId(streamChannel),
  )
  const [input, setInput] = useState('')
  const [_suppressAutoCreate, setSuppressAutoCreate] = useState(false)
  const [selectedModel, setSelectedModel] = useState<string>(() => localStorage.getItem('unified_chat_selected_model') || 'llama3:70b')
  const [confirmDialog, setConfirmDialog] = useState<{
    open: boolean
    message: string
    onConfirm: () => void
  }>({ open: false, message: '', onConfirm: () => {} })
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const streamSessionRef = useRef<number | null>(null)
  const initialHandled = useRef(false)

  useEffect(() => {
    persistSessionId(streamChannel, selectedSessionId)
  }, [streamChannel, selectedSessionId])

  useEffect(() => {
    if (stream.isLoading && stream.sessionId != null) {
      setSelectedSessionId(stream.sessionId)
    }
    streamSessionRef.current = stream.sessionId ?? streamSessionRef.current
  }, [stream.isLoading, stream.sessionId])

  const queryClient = useQueryClient()

  const { data: modelsData, isFetched: modelsFetched } = useQuery<{
    success: boolean
    reachable?: boolean
    models: AIModel[]
    default: string
    error?: string
    remote?: boolean
    provider?: string
  }>({
    queryKey: ['unified-ai-models'],
    queryFn: async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/chat/models`, { signal: AbortSignal.timeout(5000) })
        if (!res.ok) return { success: false, reachable: false, models: [], default: 'llama3.2:3b', error: `HTTP ${res.status}` }
        return res.json()
      } catch (e) {
        return {
          success: false,
          reachable: false,
          models: [],
          default: 'llama3.2:3b',
          error: e instanceof Error ? e.message : 'bağlantı hatası',
        }
      }
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
          { name: 'llama3:70b', size: 0, parameter_size: '70.6B', family: 'llama' }
        ]

  const { data: sessions = [], isFetched: sessionsFetched } = useQuery<ChatSession[]>({
    queryKey: ['unified-chat-sessions'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/unified-chat/sessions`)
      if (!res.ok) throw new Error('Failed')
      return res.json()
    }
  })

  const { data: messages = [] } = useQuery<Message[]>({
    queryKey: ['unified-chat-messages', selectedSessionId],
    queryFn: async () => {
      if (!selectedSessionId) return []
      const res = await fetch(`${API_BASE_URL}/unified-chat/sessions/${selectedSessionId}/messages`)
      if (!res.ok) throw new Error('Failed')
      return res.json()
    },
    enabled: selectedSessionId !== null
  })

  const createSessionMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/unified-chat/sessions`, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
      if (!res.ok) throw new Error('Failed')
      return res.json()
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['unified-chat-sessions'] })
      abortChatStream(streamChannel)
      setSelectedSessionId(data.id)
      setInput('')
      setSuppressAutoCreate(false)
    }
  })

  const deleteSessionMutation = useMutation({
    mutationFn: async (sessionId: number) => {
      const res = await fetch(`${API_BASE_URL}/unified-chat/sessions/${sessionId}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('Failed')
    },
    onSuccess: (_: unknown, sessionId: number) => {
      queryClient.setQueryData<ChatSession[]>(['unified-chat-sessions'], prev => (prev ?? []).filter(s => s.id !== sessionId))
      queryClient.removeQueries({ queryKey: ['unified-chat-messages', sessionId] })
      if (selectedSessionId === sessionId) setSelectedSessionId(null)
    }
  })

  const clearAllSessionsMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/unified-chat/sessions`, { method: 'DELETE' })
      if (!res.ok) throw new Error('Failed')
    },
    onSuccess: () => {
      queryClient.setQueryData<ChatSession[]>(['unified-chat-sessions'], [])
      queryClient.removeQueries({ queryKey: ['unified-chat-messages'] })
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

  const sendMessage = async (messageText: string) => {
    if (!messageText.trim() || isLoading) return
    const CONTEXT_KEYWORDS = ['cpu', 'ram', 'memory', 'bellek', 'disk', 'servis', 'service', 'log',
      'update', 'güncelleme', 'yama', 'patch', 'network', 'ağ', 'os', 'işletim sistemi',
      'performans', 'performance', 'kullanım', 'usage', 'güvenlik', 'security', 'durum', 'genel', 'özet']
    const needsContext = CONTEXT_KEYWORDS.some(k => messageText.toLowerCase().includes(k))
    streamSessionRef.current = selectedSessionId

    await startChatStream({
      channel: streamChannel,
      url: `${API_BASE_URL}/unified-chat/stream`,
      body: {
        message: messageText,
        session_id: selectedSessionId,
        model: selectedModel,
        use_rag: true,
      },
      sessionId: selectedSessionId,
      message: messageText,
      initialPhase: needsContext ? 'context' : 'streaming',
      onSessionId: (id) => {
        setSelectedSessionId(id)
        streamSessionRef.current = id
      },
      onDone: async (sid) => {
        const id = sid ?? selectedSessionId
        if (id != null) {
          await queryClient.invalidateQueries({ queryKey: ['unified-chat-messages', id] })
        }
        await queryClient.invalidateQueries({ queryKey: ['unified-chat-sessions'] })
        setInput('')
      },
    })
  }

  const handleSubmit = () => {
    if (!input.trim() || isLoading) return
    const messageText = input
    setInput('')
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
    abortChatStream(streamChannel)
  }

  const streamBelongsHere =
    pendingUserMessage != null &&
    (stream.sessionId === selectedSessionId ||
      (stream.isLoading && (stream.sessionId == null || stream.sessionId === selectedSessionId)))


  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    return date.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })
  }

  const thinkingLabel =
    thinkingPhase === 'context' ? 'Bağlam hazırlanıyor (Linux SSH / Windows WinRM / RAG)...' :
    thinkingPhase === 'tools' ? 'Tanı araçları çalışıyor...' :
    thinkingPhase === 'streaming' ? 'Yanıt üretiliyor...' : ''

  return (
    <>
      <NlChatRoot embedded={embedded}>
        <NlHistorySidebar
          sessions={sessions}
          selectedId={selectedSessionId}
          onSelect={id => {
            if (id !== selectedSessionId) {
              abortChatStream(streamChannel)
            }
            setSelectedSessionId(id)
            setInput('')
          }}
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
            <span className="px-2.5 py-1 rounded-full border border-sky-500/40 bg-sky-500/10 text-sky-200 text-[11px] font-medium">
              Tüm Altyapı
            </span>
            {messages.length > 0 && (
              <button
                type="button"
                onClick={() => exportChatMessagesToPrintWindow(messages, {
                  title: 'Tüm Altyapı AI Asistan',
                  subtitle: new Date().toLocaleString('tr-TR'),
                  filename: `unified_ai_${new Date().toISOString().slice(0, 10)}`,
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
              storageKey="unified_chat_selected_model"
            />
          </NlTopBar>

          <NlModelUnavailableBanner modelsData={modelsData} isFetched={modelsFetched} />

          <ChatPlatformStatsBar platform="all" />

          <div ref={messagesContainerRef} className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-4 py-4">
            {messages.length === 0 && !streamBelongsHere ? (
              <NlEmptyState
                icon={<Globe size={24} className="text-white" />}
                description="Linux, Windows ve sanallaştırma altyapınızın tamamı hakkında doğal dilde sorun — platformlar arası karşılaştırma ve genel özet dahil."
                suggestions={SUGGESTED_QUESTIONS}
                onSelectSuggestion={sendMessage}
              />
            ) : (
              <div className="max-w-3xl mx-auto space-y-4">
                {[
                  ...messages,
                  ...(streamBelongsHere
                    ? [{ id: -1, role: 'user' as const, content: pendingUserMessage!, created_at: new Date().toISOString() }]
                    : [])
                ].map(msg => (
                  <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={msg.role === 'user' ? nlUserBubbleClass : nlAssistantBubbleClass}>
                      {msg.role === 'user' ? (
                        <div className="whitespace-pre-wrap">{msg.content}</div>
                      ) : (
                        <div className={chatResponseBody}>
                          <ReactMarkdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>{msg.content}</ReactMarkdown>
                          <div className="mt-2 flex flex-wrap gap-2">
                            {msg.content?.trim().length > 40 && (
                              <button
                                type="button"
                                onClick={() => exportMarkdownToPrintWindow(msg.content, {
                                  title: 'AI Asistan Yanıtı',
                                  subtitle: msg.created_at ? new Date(msg.created_at).toLocaleString('tr-TR') : undefined,
                                  filename: `ai_yanit_${(msg.created_at || '').slice(0, 10) || 'export'}`,
                                })}
                                className="text-xs px-2 py-1.5 rounded bg-red-700/40 hover:bg-red-600/50 text-red-100 border border-red-500/40 flex items-center gap-1"
                              >
                                <FileDown size={12} /> PDF
                              </button>
                            )}
                            {getFirstMarkdownTable(msg.content) && (
                              <>
                                <button
                                  type="button"
                                  onClick={() => downloadTableAsCsv(getFirstMarkdownTable(msg.content)!, 'tablo.csv')}
                                  className="text-xs px-2 py-1.5 rounded bg-slate-700/70 hover:bg-slate-700 text-slate-200 border border-slate-600/50 flex items-center gap-1"
                                >
                                  CSV İndir
                                </button>
                                <button
                                  type="button"
                                  onClick={() => downloadTableAsXlsx(getFirstMarkdownTable(msg.content)!, 'tablo.xlsx')}
                                  className="text-xs px-2 py-1.5 rounded bg-green-700/60 hover:bg-green-600/70 text-green-200 border border-green-600/50 flex items-center gap-1"
                                >
                                  Excel İndir
                                </button>
                              </>
                            )}
                          </div>
                          {msg.id > 0 && (
                            <>
                              <ChatFeedbackButtons
                                platform="unified"
                                question={priorUserQuestion(messages, msg.id)}
                                answer={msg.content}
                                sessionId={selectedSessionId}
                                messageId={msg.id}
                              />
                              <ChatPinFact />
                            </>
                          )}
                        </div>
                      )}
                      <div className={`text-xs mt-2 ${msg.role === 'user' ? 'text-blue-200' : 'text-slate-500'}`}>
                        {formatDate(msg.created_at)}
                      </div>
                    </div>
                  </div>
                ))}

                {isLoading && streamBelongsHere && (
                  <div className="flex justify-start">
                    <div className={`${nlAssistantBubbleClass} max-w-[min(85%,48rem)] w-full`}>
                      {toolCalls.length > 0 && (
                        <div className="space-y-1 mb-2">
                          {toolCalls.map((tc, i) => (
                            <div key={`${tc.tool}-${i}`} className="flex items-center gap-2 text-[11px] text-slate-500">
                              <span className={`inline-flex items-center gap-1 ${tc.done ? 'opacity-60' : 'animate-pulse'}`}>
                                <Wrench size={11} strokeWidth={2} /> {tc.label}{tc.done ? '' : '…'}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                      {thinkingPhase === 'context' && (
                        <div className="space-y-2">
                          <div className="flex items-center gap-2 text-xs text-slate-400">
                            <div className="w-3 h-3 border-2 border-sky-400 border-t-transparent rounded-full animate-spin flex-shrink-0" />
                            <span>{thinkingLabel}</span>
                          </div>
                          <ThinkingDots />
                        </div>
                      )}
                      {thinkingPhase === 'tools' && (
                        <div className="space-y-2">
                          <div className="flex items-center gap-2 text-xs text-cyan-400/90">
                            <div className="w-3 h-3 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin flex-shrink-0" />
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

            {clarifyOptions && clarifyOptions.length > 0 && !isLoading && (
              <div className="px-1 pb-2 flex flex-wrap gap-2">
                {clarifyOptions.map(opt => (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => {
                      clearChatClarify(streamChannel)
                      sendMessage(opt.prompt)
                    }}
                    className="text-left text-xs px-3 py-2 rounded-lg border border-sky-500/40 bg-sky-500/10 text-sky-200 hover:bg-sky-500/20 hover:border-sky-400/60 transition-colors"
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          <NlChatInput
            value={input}
            onChange={setInput}
            onSubmit={handleSubmit}
            onAbort={handleAbort}
            loading={isLoading}
            placeholder="Örn: Genel altyapı durumu nasıl? · En yüksek CPU kullanan sunucular..."
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

export default UnifiedChat
