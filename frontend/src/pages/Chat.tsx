import React, { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

const API_BASE_URL = 'http://192.168.1.166:8000/api/v1'

interface Server {
  id: number
  name: string
  ip_address: string
  ai_ready: boolean
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

const Chat: React.FC = () => {
  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null)
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const queryClient = useQueryClient()

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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
      if (selectedSessionId && sessions.find(s => s.id === selectedSessionId) === undefined) {
        setSelectedSessionId(null)
      }
    }
  })

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // İlk session yoksa oluştur
  useEffect(() => {
    if (sessions.length === 0 && !createSessionMutation.isPending) {
      createSessionMutation.mutate()
    } else if (sessions.length > 0 && selectedSessionId === null) {
      setSelectedSessionId(sessions[0].id)
    }
  }, [sessions.length, selectedSessionId])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return

    const messageText = input
    setInput('')
    setIsLoading(true)

    try {
      const response = await fetch(`${API_BASE_URL}/chat/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: messageText,
          session_id: selectedSessionId
        })
      })

      const data = await response.json()

      if (data.session_id && data.session_id !== selectedSessionId) {
        setSelectedSessionId(data.session_id)
      }

      // Mesajları yenile
      await refetchMessages()
      await refetchSessions()
    } catch (error) {
      console.error('Chat error:', error)
    } finally {
      setIsLoading(false)
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

  return (
    <div className="flex flex-col h-[calc(100vh-140px)]">
      {/* Üst Panel - Chat Session'ları */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 mb-4 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">Chat Session'ları</h3>
          <button
            onClick={() => createSessionMutation.mutate()}
            disabled={createSessionMutation.isPending}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
          >
            {createSessionMutation.isPending ? 'Oluşturuluyor...' : '+ Yeni Chat'}
          </button>
        </div>
        <div className="overflow-x-auto">
          <div className="flex space-x-2 p-3">
            {sessions.length === 0 ? (
              <div className="text-center py-4 text-slate-500 text-sm w-full">
                Henüz chat session'ı yok
              </div>
            ) : (
              sessions.map(session => (
                <div
                  key={session.id}
                  className={`flex items-center space-x-2 px-4 py-2 rounded-lg cursor-pointer transition-all min-w-[200px] ${
                    selectedSessionId === session.id
                      ? 'bg-blue-600 text-white'
                      : 'bg-slate-700/50 hover:bg-slate-700 text-slate-300'
                  }`}
                  onClick={() => setSelectedSessionId(session.id)}
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate">{session.title}</div>
                    <div className={`text-xs ${selectedSessionId === session.id ? 'text-blue-100' : 'text-slate-400'}`}>
                      {session.message_count} mesaj • {formatSessionDate(session.updated_at || session.created_at)}
                    </div>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      if (confirm('Bu chat session\'ını silmek istediğinize emin misiniz?')) {
                        deleteSessionMutation.mutate(session.id)
                      }
                    }}
                    className={`p-1 rounded hover:bg-opacity-20 ${
                      selectedSessionId === session.id ? 'hover:bg-white' : 'hover:bg-slate-600'
                    }`}
                    title="Sil"
                  >
                    <span className="text-xs">✕</span>
                  </button>
                </div>
              ))
            )}
          </div>
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
          ) : messages.length === 0 ? (
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
              {messages.map(message => (
                <div
                  key={message.id}
                  className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[70%] rounded-2xl px-4 py-3 ${
                      message.role === 'user'
                        ? 'bg-gradient-to-r from-blue-600 to-blue-700 text-white'
                        : 'bg-slate-700 text-slate-200'
                    }`}
                  >
                    <div className="whitespace-pre-wrap text-sm leading-relaxed">{message.content}</div>
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
          <form onSubmit={handleSubmit} className="flex items-center space-x-4">
            <div className="flex-1 relative">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={selectedSessionId ? "Mesajınızı yazın..." : "Önce bir chat session'ı seçin"}
                className="w-full bg-slate-800 border border-slate-600 rounded-xl px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                disabled={isLoading || selectedSessionId === null}
              />
            </div>
            <button
              type="submit"
              disabled={isLoading || !input.trim() || selectedSessionId === null}
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
  )
}

export default Chat
