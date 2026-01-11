import React, { useState, useRef, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'

const API_BASE_URL = 'http://192.168.1.166:8000/api/v1'

interface Server {
  id: number
  name: string
  ip_address: string
  ai_ready: boolean
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

const Chat: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [selectedServers, setSelectedServers] = useState<number[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const { data: servers = [] } = useQuery<Server[]>({
    queryKey: ['ai-ready-servers'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/servers/ai-ready/list`)
      if (!response.ok) throw new Error('Failed to fetch servers')
      return response.json()
    }
  })

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input,
      timestamp: new Date()
    }

    setMessages(prev => [...prev, userMessage])
    setInput('')
    setIsLoading(true)

    try {
      const response = await fetch(`${API_BASE_URL}/chat/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: input,
          server_ids: selectedServers.length > 0 ? selectedServers : undefined
        })
      })

      const data = await response.json()

      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: data.response || data.message || 'Yanıt alınamadı',
        timestamp: new Date()
      }

      setMessages(prev => [...prev, assistantMessage])
    } catch (error) {
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: `Hata: ${error instanceof Error ? error.message : 'Bilinmeyen hata'}`,
        timestamp: new Date()
      }
      setMessages(prev => [...prev, errorMessage])
    } finally {
      setIsLoading(false)
    }
  }

  const quickActions = [
    { icon: '📊', text: 'Sunucu durumlarını göster' },
    { icon: '⚡', text: 'Son 1 saatlik performans analizi yap' },
    { icon: '💾', text: 'Disk kullanımı yüksek sunucuları bul' },
    { icon: '🔥', text: 'CPU kullanımı kritik olan sunucular' },
    { icon: '🔍', text: 'Tüm sunucularda uptime kontrolü yap' },
    { icon: '📈', text: 'Memory kullanımı analizi' },
  ]

  const aiReadyServers = servers.filter(s => s.ai_ready)

  return (
    <div className="flex h-[calc(100vh-140px)] gap-6">
      {/* Sol Panel - Sunucu Seçimi */}
      <div className="w-72 bg-slate-800 rounded-xl border border-slate-700 flex flex-col overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-700">
          <h3 className="text-sm font-semibold text-white">AI Ready Sunucular</h3>
          <p className="text-xs text-slate-400 mt-1">{aiReadyServers.length} sunucu</p>
        </div>
        <div className="flex-1 overflow-y-auto p-3">
          {aiReadyServers.length === 0 ? (
            <div className="text-center py-8 text-slate-500 text-sm">
              <span className="text-2xl block mb-2">🤖</span>
              AI Ready sunucu bulunamadı
            </div>
          ) : (
            <div className="space-y-2">
              {aiReadyServers.map(server => (
                <label
                  key={server.id}
                  className={`flex items-center p-3 rounded-lg cursor-pointer transition-all ${
                    selectedServers.includes(server.id)
                      ? 'bg-blue-600/20 border border-blue-500/50'
                      : 'bg-slate-700/50 border border-transparent hover:bg-slate-700'
                  }`}
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
                  <div className="ml-3">
                    <p className="text-sm font-medium text-white">{server.name}</p>
                    <p className="text-xs text-slate-400 font-mono">{server.ip_address}</p>
                  </div>
                </label>
              ))}
            </div>
          )}
        </div>
        {selectedServers.length > 0 && (
          <div className="px-4 py-3 border-t border-slate-700 bg-slate-900/50">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-400">{selectedServers.length} seçili</span>
              <button
                onClick={() => setSelectedServers([])}
                className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
              >
                Temizle
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Sağ Panel - Chat */}
      <div className="flex-1 bg-slate-800 rounded-xl border border-slate-700 flex flex-col overflow-hidden">
        {/* Mesajlar */}
        <div className="flex-1 overflow-y-auto p-6">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center">
              <div className="w-20 h-20 bg-gradient-to-br from-purple-500 to-blue-500 rounded-2xl flex items-center justify-center mb-6 shadow-lg shadow-purple-500/25">
                <span className="text-4xl">🤖</span>
              </div>
              <h2 className="text-2xl font-bold text-white mb-2">AI Asistan</h2>
              <p className="text-slate-400 text-center max-w-md mb-8">
                Sunucularınız hakkında sorular sorun, performans analizi isteyin veya komut çalıştırın.
              </p>
              <div className="grid grid-cols-2 gap-3 max-w-lg">
                {quickActions.map((action, index) => (
                  <button
                    key={index}
                    onClick={() => setInput(action.text)}
                    className="flex items-center space-x-2 p-3 bg-slate-700/50 hover:bg-slate-700 rounded-lg text-left transition-colors border border-slate-600 hover:border-slate-500"
                  >
                    <span className="text-xl">{action.icon}</span>
                    <span className="text-sm text-slate-300">{action.text}</span>
                  </button>
                ))}
              </div>
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
                      {message.timestamp.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })}
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
  )
}

export default Chat
