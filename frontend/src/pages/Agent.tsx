import React, { useState, useEffect, useRef } from 'react'
import { API_BASE_URL } from '../config/api'

interface Server { id: number; name: string; ip_address: string; ai_ready: boolean; status: string }
interface AIModel { name: string }

interface StepResult {
  ok?: boolean
  stdout?: string
  stderr?: string
  command?: string
  server?: string
  error?: string
  rejected?: boolean
}
interface GuardVerdict { decision?: string; reason?: string; model?: string; enabled?: boolean; degraded?: boolean }
interface Step {
  type: 'read_only' | 'approval_required' | 'executed' | 'rejected' | 'error' | 'blocked'
  tool: string
  args?: Record<string, unknown>
  preview?: string
  result?: StepResult
  action_id?: number
  detail?: string
  guard?: GuardVerdict
}
interface AgentResponse {
  status: 'done' | 'pending' | 'error' | 'max_steps'
  answer?: string
  steps: Step[]
  action_id?: number
  preview?: string
  tool?: string
  error?: string
  session_id?: number
}

type TimelineItem =
  | { kind: 'user'; text: string }
  | { kind: 'step'; step: Step }
  | { kind: 'answer'; text: string }
  | { kind: 'error'; text: string }

// Tool-calling yapamayan modelleri ele: embedding modelleri + tool desteklemeyenler
const isToolCapable = (name: string) => {
  const n = name.toLowerCase()
  if (n.includes('embed')) return false
  if (n.startsWith('deepseek-r1')) return false   // reasoning, tool desteği yok
  if (n === 'qwen:latest') return false           // eski Qwen, tool desteği yok
  return true
}

const riskBadge = (tool: string) => {
  const mutating = ['clean_logs', 'restart_service', 'update_packages', 'manage_lvm'].includes(tool)
  return mutating
    ? <span className="px-2 py-0.5 rounded text-[10px] bg-amber-500/15 text-amber-300 border border-amber-500/40">MUTATING</span>
    : <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-500/15 text-emerald-300 border border-emerald-500/40">READ-ONLY</span>
}

const Agent: React.FC = () => {
  const [servers, setServers] = useState<Server[]>([])
  const [models, setModels] = useState<string[]>([])
  const [selectedModel, setSelectedModel] = useState<string>(() => localStorage.getItem('agent_model') || 'qwen3.5:35b')
  const [selectedServers, setSelectedServers] = useState<number[]>([])
  const [input, setInput] = useState('')
  const [timeline, setTimeline] = useState<TimelineItem[]>([])
  const [loading, setLoading] = useState(false)
  const [pendingActionId, setPendingActionId] = useState<number | null>(null)
  const [sessionId, setSessionId] = useState<number | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetch(`${API_BASE_URL}/servers/ai-ready/list`)
      .then(r => r.ok ? r.json() : [])
      .then((d: Server[] | { servers: Server[] }) => {
        const list = Array.isArray(d) ? d : (d.servers || [])
        setServers(list.filter(s => s.ai_ready))
      })
      .catch(() => {})
    fetch(`${API_BASE_URL}/chat/models`)
      .then(r => r.ok ? r.json() : { models: [] })
      .then((d: { models?: AIModel[]; default?: string }) => {
        const names = (d.models || []).map(m => m.name).filter(Boolean).filter(isToolCapable)
        setModels(names)
        if (names.length && !names.includes(selectedModel)) {
          setSelectedModel(names.includes('qwen3.5:35b') ? 'qwen3.5:35b' : names[0])
        }
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => { localStorage.setItem('agent_model', selectedModel) }, [selectedModel])
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [timeline, loading])

  const applyResponse = (resp: AgentResponse) => {
    const items: TimelineItem[] = (resp.steps || []).map(s => ({ kind: 'step' as const, step: s }))
    if (resp.status === 'done' && resp.answer) items.push({ kind: 'answer', text: resp.answer })
    if (resp.status === 'max_steps') items.push({ kind: 'answer', text: resp.answer || 'Maksimum adıma ulaşıldı.' })
    if (resp.status === 'error') items.push({ kind: 'error', text: resp.error || 'Bilinmeyen hata' })
    setTimeline(prev => [...prev, ...items])
    setPendingActionId(resp.status === 'pending' ? (resp.action_id ?? null) : null)
    if (resp.session_id) setSessionId(resp.session_id)
  }

  const send = async () => {
    const msg = input.trim()
    if (!msg || loading) return
    setInput('')
    setTimeline(prev => [...prev, { kind: 'user', text: msg }])
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE_URL}/agent/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: msg,
          model: selectedModel,
          server_ids: selectedServers.length ? selectedServers : null,
          session_id: sessionId,
        }),
      })
      const data: AgentResponse = await res.json()
      applyResponse(data)
    } catch (e) {
      setTimeline(prev => [...prev, { kind: 'error', text: String(e) }])
    } finally {
      setLoading(false)
    }
  }

  const decide = async (actionId: number, approve: boolean) => {
    setLoading(true)
    setPendingActionId(null)
    try {
      const res = await fetch(`${API_BASE_URL}/agent/actions/${actionId}/${approve ? 'approve' : 'reject'}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      const data: AgentResponse = await res.json()
      applyResponse(data)
    } catch (e) {
      setTimeline(prev => [...prev, { kind: 'error', text: String(e) }])
    } finally {
      setLoading(false)
    }
  }

  const toggleServer = (id: number) =>
    setSelectedServers(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])

  const resetChat = () => {
    setTimeline([]); setSessionId(null); setPendingActionId(null)
  }

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      {/* Controls */}
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 space-y-3">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="text-2xl">🤖</span>
            <div>
              <h2 className="text-white font-semibold">AI Agent</h2>
              <p className="text-xs text-slate-400">Otonom teşhis + onaylı düzeltme (human-in-the-loop)</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-400">Model</label>
            <select
              value={selectedModel}
              onChange={e => setSelectedModel(e.target.value)}
              className="bg-slate-900 border border-slate-600 text-slate-200 text-sm rounded-lg px-2 py-1.5"
            >
              {!models.includes(selectedModel) && <option value={selectedModel}>{selectedModel}</option>}
              {models.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
            <button onClick={resetChat} className="text-xs px-3 py-1.5 rounded-lg bg-slate-700 text-slate-300 hover:bg-slate-600">
              Yeni
            </button>
          </div>
        </div>

        {/* Server selector */}
        <div className="flex flex-wrap gap-2">
          {servers.length === 0 && <span className="text-xs text-slate-500">AI-ready sunucu yok.</span>}
          {servers.map(s => {
            const sel = selectedServers.includes(s.id)
            return (
              <button
                key={s.id}
                onClick={() => toggleServer(s.id)}
                className={`text-xs px-2.5 py-1 rounded-lg border transition-colors ${
                  sel ? 'bg-blue-600 border-blue-500 text-white'
                      : 'bg-slate-900 border-slate-600 text-slate-300 hover:border-slate-500'
                }`}
                title={s.ip_address}
              >
                {s.name}
              </button>
            )
          })}
        </div>
      </div>

      {/* Timeline */}
      <div className="space-y-3">
        {timeline.map((item, i) => {
          if (item.kind === 'user') {
            return (
              <div key={i} className="flex justify-end">
                <div className="bg-blue-600 text-white rounded-2xl rounded-br-sm px-4 py-2 max-w-[80%]">
                  {item.text}
                </div>
              </div>
            )
          }
          if (item.kind === 'answer') {
            return (
              <div key={i} className="bg-slate-800 border border-slate-700 rounded-xl p-4 text-slate-200 whitespace-pre-wrap">
                {item.text}
              </div>
            )
          }
          if (item.kind === 'error') {
            return (
              <div key={i} className="bg-red-500/10 border border-red-500/40 rounded-xl p-3 text-red-300 text-sm">
                ⚠️ {item.text}
              </div>
            )
          }
          // step
          const s = item.step
          if (s.type === 'approval_required') {
            const isPending = pendingActionId === s.action_id
            return (
              <div key={i} className="bg-amber-500/5 border border-amber-500/40 rounded-xl p-4 space-y-3">
                <div className="flex items-center gap-2">
                  <span className="text-amber-300 font-medium">Onay gerekiyor</span>
                  {riskBadge(s.tool)}
                </div>
                <div className="text-sm text-slate-300">
                  <span className="text-slate-400">Tool:</span> <code className="text-amber-200">{s.tool}</code>
                </div>
                <pre className="bg-slate-900 border border-slate-700 rounded-lg p-3 text-xs text-slate-200 overflow-x-auto">{s.preview}</pre>
                {s.guard && s.guard.enabled && (
                  <div className="text-xs flex items-start gap-2 bg-slate-900/60 border border-slate-700 rounded-lg p-2">
                    <span className="text-slate-400">🛡️ Guard:</span>
                    <span className={s.guard.degraded ? 'text-slate-400' : 'text-emerald-300'}>
                      {s.guard.degraded ? 'erişilemedi (fail-open)' : 'izin verdi'}
                    </span>
                    {s.guard.reason && <span className="text-slate-500">— {s.guard.reason}</span>}
                  </div>
                )}
                {isPending ? (
                  <div className="flex gap-2">
                    <button
                      onClick={() => s.action_id && decide(s.action_id, true)}
                      disabled={loading}
                      className="px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium disabled:opacity-50"
                    >
                      ✓ Onayla & Çalıştır
                    </button>
                    <button
                      onClick={() => s.action_id && decide(s.action_id, false)}
                      disabled={loading}
                      className="px-4 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm disabled:opacity-50"
                    >
                      ✕ Reddet
                    </button>
                  </div>
                ) : (
                  <div className="text-xs text-slate-500">Karar verildi.</div>
                )}
              </div>
            )
          }

          if (s.type === 'blocked') {
            return (
              <div key={i} className="bg-red-500/5 border border-red-500/40 rounded-xl p-4 space-y-2">
                <div className="flex items-center gap-2">
                  <span className="text-red-300 font-medium">🛡️ Guard engelledi</span>
                  <code className="text-red-200 text-sm">{s.tool}</code>
                </div>
                {s.preview && <pre className="bg-slate-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-300 overflow-x-auto">{s.preview}</pre>}
                {s.guard?.reason && <div className="text-xs text-red-300">Gerekçe: {s.guard.reason}</div>}
                <div className="text-[11px] text-slate-500">Bu işlem güvenlik politikası nedeniyle çalıştırılmadı; agent alternatif arayacak.</div>
              </div>
            )
          }

          const okColor = s.result?.ok ? 'text-emerald-300' : 'text-red-300'
          const label = s.type === 'read_only' ? 'Teşhis' : s.type === 'executed' ? 'Çalıştırıldı' : s.type === 'rejected' ? 'Reddedildi' : 'Hata'
          return (
            <details key={i} className="bg-slate-800 border border-slate-700 rounded-xl p-3" open={s.type !== 'read_only'}>
              <summary className="cursor-pointer flex items-center gap-2 text-sm">
                <span className="text-slate-400">{label}</span>
                <code className="text-cyan-300">{s.tool}</code>
                {riskBadge(s.tool)}
                {s.result && <span className={`ml-auto text-xs ${okColor}`}>{s.result.ok ? 'OK' : (s.result.error || s.detail || 'hata')}</span>}
              </summary>
              {s.preview && <div className="mt-2 text-xs text-slate-400">{s.preview}</div>}
              {s.result?.stdout && (
                <pre className="mt-2 bg-slate-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-200 overflow-x-auto max-h-64">{s.result.stdout}</pre>
              )}
              {s.result?.stderr && (
                <pre className="mt-2 bg-red-500/5 border border-red-500/30 rounded-lg p-2 text-xs text-red-300 overflow-x-auto max-h-40">{s.result.stderr}</pre>
              )}
            </details>
          )
        })}
        {loading && (
          <div className="flex items-center gap-2 text-slate-400 text-sm">
            <span className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
            Agent çalışıyor...
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <div className="sticky bottom-0 bg-slate-900 pt-2">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
            placeholder="Örn: web01 sunucusunda disk doluluğunu kontrol et, gerekirse eski logları temizle"
            rows={2}
            disabled={loading}
            className="flex-1 bg-slate-800 border border-slate-700 rounded-xl px-4 py-3 text-slate-200 text-sm resize-none focus:outline-none focus:border-blue-500 disabled:opacity-60"
          />
          <button
            onClick={send}
            disabled={loading || !input.trim()}
            className="px-5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-medium disabled:opacity-50"
          >
            Gönder
          </button>
        </div>
      </div>
    </div>
  )
}

export default Agent
