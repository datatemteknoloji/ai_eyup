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

      if (!response.ok) {
        throw new Error('Chat request failed')
      }

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

  const toggleServerSelection = (serverId: number) => {
    setSelectedServers(prev => 
      prev.includes(serverId)
        ? prev.filter(id => id !== serverId)
        : [...prev, serverId]
    )
  }

  const aiReadyServers = servers.filter(s => s.ai_ready)

  return (
    <div className="flex h-[calc(100vh-120px)]">
      {/* Sol Panel - Sunucu Seçimi */}
      <div className="w-64 bg-white border-r border-gray-200 p-4 overflow-y-auto">
        <h3 className="text-sm font-medium text-gray-900 mb-3">AI Ready Sunucular</h3>
        {aiReadyServers.length === 0 ? (
          <p className="text-sm text-gray-500">AI Ready sunucu bulunamadı</p>
        ) : (
          <div className="space-y-2">
            {aiReadyServers.map(server => (
              <label
                key={server.id}
                className="flex items-center p-2 rounded-lg hover:bg-gray-50 cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={selectedServers.includes(server.id)}
                  onChange={() => toggleServerSelection(server.id)}
                  className="h-4 w-4 text-blue-600 rounded border-gray-300"
                />
                <div className="ml-3">
                  <p className="text-sm font-medium text-gray-900">{server.name}</p>
                  <p className="text-xs text-gray-500">{server.ip_address}</p>
                </div>
              </label>
            ))}
          </div>
        )}
        {selectedServers.length > 0 && (
          <div className="mt-4 pt-4 border-t">
            <p className="text-xs text-gray-500">
              {selectedServers.length} sunucu seçili
            </p>
            <button
              onClick={() => setSelectedServers([])}
              className="mt-2 text-xs text-blue-600 hover:text-blue-800"
            >
              Seçimi Temizle
            </button>
          </div>
        )}
      </div>

      {/* Sağ Panel - Chat */}
      <div className="flex-1 flex flex-col">
        {/* Mesajlar */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 ? (
            <div className="text-center py-12">
              <h2 className="text-xl font-semibold text-gray-900 mb-2">AI Asistan</h2>
              <p className="text-gray-500 mb-4">
                Sunucularınız hakkında sorular sorun, performans analizi isteyin veya komut çalıştırın.
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-w-2xl mx-auto">
                <button
                  onClick={() => setInput('Sunucuların genel durumu nedir?')}
                  className="p-3 text-left bg-gray-50 hover:bg-gray-100 rounded-lg text-sm"
                >
                  🖥️ Sunucuların genel durumu nedir?
                </button>
                <button
                  onClick={() => setInput('Son 1 saatlik performans kontrolü yap')}
                  className="p-3 text-left bg-gray-50 hover:bg-gray-100 rounded-lg text-sm"
                >
                  📊 Son 1 saatlik performans kontrolü yap
                </button>
                <button
                  onClick={() => setInput('Disk kullanımı yüksek olan sunucuları bul')}
                  className="p-3 text-left bg-gray-50 hover:bg-gray-100 rounded-lg text-sm"
                >
                  💾 Disk kullanımı yüksek sunucuları bul
                </button>
                <button
                  onClick={() => setInput('CPU kullanımı analiz et')}
                  className="p-3 text-left bg-gray-50 hover:bg-gray-100 rounded-lg text-sm"
                >
                  ⚙️ CPU kullanımı analiz et
                </button>
              </div>
            </div>
          ) : (
            messages.map(message => (
              <div
                key={message.id}
                className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-3xl rounded-lg px-4 py-2 ${
                    message.role === 'user'
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-100 text-gray-900'
                  }`}
                >
                  <div className="whitespace-pre-wrap text-sm">{message.content}</div>
                  <div className={`text-xs mt-1 ${
                    message.role === 'user' ? 'text-blue-200' : 'text-gray-500'
                  }`}>
                    {message.timestamp.toLocaleTimeString('tr-TR')}
                  </div>
                </div>
              </div>
            ))
          )}
          {isLoading && (
            <div className="flex justify-start">
              <div className="bg-gray-100 rounded-lg px-4 py-2">
                <div className="flex items-center space-x-2">
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }} />
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.4s' }} />
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="border-t border-gray-200 p-4 bg-white">
          <form onSubmit={handleSubmit} className="flex space-x-4">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Mesajınızı yazın..."
              className="flex-1 rounded-lg border border-gray-300 px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              disabled={isLoading}
            />
            <button
              type="submit"
              disabled={isLoading || !input.trim()}
              className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Gönder
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}

export default Chat
