import React, { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'

interface Server {
  id: number
  name: string
  hostname: string
  ip_address: string
  status: string
  ai_ready?: boolean
}

interface McpTool {
  name: string
  description?: string
}

interface ToolResponse {
  tools: McpTool[]
  warning?: string | null
}

const McpTools: React.FC = () => {
  const [selectedServerId, setSelectedServerId] = useState<number | null>(null)
  const [selectedTool, setSelectedTool] = useState<string>('')
  const [result, setResult] = useState<any | null>(null)
  const [error, setError] = useState<string>('')
  const [isRunning, setIsRunning] = useState(false)

  const { data: servers = [], isLoading: serversLoading } = useQuery<Server[]>({
    queryKey: ['mcp-ai-ready-servers'],
    queryFn: async () => {
      const aiReadyResp = await fetch(`${API_BASE_URL}/servers/ai-ready/list`)
      if (aiReadyResp.ok) {
        const aiReady = await aiReadyResp.json()
        if (Array.isArray(aiReady) && aiReady.length > 0) return aiReady
      }

      const allResp = await fetch(`${API_BASE_URL}/servers/`)
      if (!allResp.ok) throw new Error('Sunucu listesi alinamadi')
      const allServers: Server[] = await allResp.json()
      return allServers
    }
  })

  const { data: toolsData, isLoading: toolsLoading, refetch: refetchTools } = useQuery<ToolResponse>({
    queryKey: ['mcp-tools'],
    queryFn: async () => {
      const resp = await fetch(`${API_BASE_URL}/mcp/tools`)
      const body = await resp.json().catch(() => ({}))
      if (!resp.ok) throw new Error(body?.detail || 'MCP arac listesi alinamadi')
      return {
        tools: Array.isArray(body?.tools) ? body.tools : [],
        warning: body?.warning || null,
      }
    }
  })

  const selectedServer = useMemo(
    () => servers.find((s) => s.id === selectedServerId) ?? null,
    [servers, selectedServerId]
  )

  const runTool = async () => {
    if (!selectedServer || !selectedTool) return
    setIsRunning(true)
    setError('')
    setResult(null)
    try {
      const response = await fetch(`${API_BASE_URL}/mcp/call-tool`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_name: selectedTool,
          host: selectedServer.ip_address || selectedServer.hostname,
          arguments: {},
        })
      })
      const body = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(body?.detail || 'Arac calistirilamadi')
      }
      setResult(body)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Bilinmeyen hata')
    } finally {
      setIsRunning(false)
    }
  }

  const tools = toolsData?.tools || []

  return (
    <div className="space-y-6">
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-6">
        <h2 className="text-xl font-semibold text-white">Linux MCP</h2>
        <p className="text-slate-400 text-sm mt-2">
          Once AI Ready sunucular listelenir. MCP araclari yoksa built-in araclar gosterilir.
        </p>
      </div>

      <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 space-y-4">
        <div>
          <label className="block text-sm text-slate-300 mb-2">Sunucu (AI Ready)</label>
          <select
            value={selectedServerId ?? ''}
            onChange={(e) => setSelectedServerId(e.target.value ? Number(e.target.value) : null)}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white"
            disabled={serversLoading}
          >
            <option value="">{serversLoading ? 'Yukleniyor...' : 'Sunucu secin'}</option>
            {servers.map((server) => (
              <option key={server.id} value={server.id}>
                {server.name} - {server.ip_address || server.hostname} ({server.status}{server.ai_ready ? ', AI Ready' : ''})
              </option>
            ))}
          </select>
        </div>

        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="block text-sm text-slate-300">Arac secin</label>
            <button
              onClick={() => void refetchTools()}
              className="text-xs px-2 py-1 rounded bg-slate-700 text-slate-200 hover:bg-slate-600"
              type="button"
            >
              Yenile
            </button>
          </div>
          <select
            value={selectedTool}
            onChange={(e) => setSelectedTool(e.target.value)}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white"
            disabled={toolsLoading}
          >
            <option value="">{toolsLoading ? 'Araclar yukleniyor...' : 'Arac secin'}</option>
            {tools.map((tool) => (
              <option key={tool.name} value={tool.name}>
                {tool.name}{tool.description ? ` - ${tool.description}` : ''}
              </option>
            ))}
          </select>
          {toolsData?.warning && (
            <p className="text-xs text-amber-300 mt-2">MCP uyarisi: {toolsData.warning}</p>
          )}
        </div>

        <button
          type="button"
          onClick={() => void runTool()}
          disabled={!selectedServer || !selectedTool || isRunning}
          className="px-4 py-2 rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 text-white disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isRunning ? 'Calistiriliyor...' : 'Calistir'}
        </button>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-300 text-sm">
          {error}
        </div>
      )}

      {result && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-6">
          <h3 className="text-white font-medium mb-3">Sonuc</h3>
          <pre className="text-xs text-slate-200 whitespace-pre-wrap bg-slate-900 border border-slate-700 rounded-lg p-3 overflow-auto">
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

export default McpTools
