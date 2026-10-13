import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Workflow, Wrench, Check, ArrowRight } from 'lucide-react'
import {
  NlChatRoot, NlHistorySidebar, NlChatPanel, NlTopBar, NlEmptyState, NlChatInput, NlTypingRow,
  nlChatColumnClass, nlUserBubbleClass, nlAssistantBubbleClass, type NlChatSession,
} from '../../components/nlChatUi'
import { useChatStickToBottom } from '../../lib/chatScroll'
import { AUTOMATION_API, apiGet, apiSend, executionPath, objectPath } from './api'
import { AutomicComponents, NoSystemNotice, SystemPicker, useSelectedSystem, type AutomicComponent } from './ui'
import { AnswerFooter, AutomicMarkdown, type AnswerScope, type Confidence } from './AnswerView'

type Meta = {
  intent: string
  severity: 'ok' | 'info' | 'warning' | 'critical'
  confidence?: Confidence
  scope: AnswerScope & Record<string, any>
  entities: { kind: 'execution' | 'object' | 'agent'; client?: number; run_id?: number; object_name?: string; name?: string }[]
  follow_ups: string[]
}

type Msg = {
  id: number | string
  role: 'user' | 'assistant'
  content: string
  meta?: { automic?: Meta | null; components?: AutomicComponent[]; tools_used?: string[]; error?: string | null }
}

type ToolStep = { tool: string; label?: string; done: boolean; fallback?: boolean }

// SSE `progress` olayları (düşünme METNİ gelmez; yalnız durum): understood → thinking → querying → found → answering
type ProgressStep = { step: string; text: string; tool?: string; count?: number }

const TOOL_LABELS: Record<string, string> = {
  automic_search_executions: 'Çalışma arama',
  automic_execution: 'Çalışma detayı',
  automic_active: 'Aktif işler',
  automic_object: 'Nesne özeti',
  automic_history: 'Analiz',
  automic_status: 'Entegrasyon durumu',
}

const SUGGESTIONS = [
  'Son 24 saatte en çok hata veren 5 job hangisi?',
  'Şu an p95 süresini aşan çalışan işler var mı?',
  'Bugünkü hataları hata imzasına göre grupla',
  'Son 7 günde hata trendi nasıl?',
  'En yavaş çalışan 10 nesne hangileri?',
  'Entegrasyon durumu ve kaynak gecikmesi nedir?',
]

export default function AutomationChat() {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const { systems, selected, setSystem } = useSelectedSystem()
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [search, setSearch] = useState('')
  const [streaming, setStreaming] = useState('')
  const [phase, setPhase] = useState<string | null>(null)
  const [tools, setTools] = useState<ToolStep[]>([])
  const [progress, setProgress] = useState<ProgressStep[]>([])
  const [liveComponents, setLiveComponents] = useState<AutomicComponent[]>([])
  const [pendingUser, setPendingUser] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const autoSent = useRef(false)

  const sessions = useQuery({
    queryKey: ['automic-chat-sessions'],
    queryFn: () => apiGet<NlChatSession[]>('/chat/sessions'),
  })

  useChatStickToBottom(listRef, {
    sessionId,
    messageCount: messages.length,
    followKey: `${streaming.length}|${phase}|${tools.length}|${progress.length}|${liveComponents.length}|${pendingUser ?? ''}`,
    sending: loading,
  })

  const openSession = async (id: number) => {
    if (loading) return
    setSessionId(id)
    const rows = await apiGet<Msg[]>(`/chat/sessions/${id}/messages`).catch(() => [])
    setMessages(rows)
  }

  const newChat = () => {
    if (loading) return
    setSessionId(null)
    setMessages([])
  }

  const deleteSession = async (id: number) => {
    await apiSend(`/chat/sessions/${id}`, 'DELETE').catch(() => null)
    if (id === sessionId) newChat()
    qc.invalidateQueries({ queryKey: ['automic-chat-sessions'] })
  }

  const clearAll = async () => {
    if (!window.confirm('Tüm Automic sohbetleri silinsin mi?')) return
    try {
      // Toplu silme — liste en fazla 50 gösterir; tek tek DELETE sonraki 50'yi yeniden getiriyordu
      await apiSend<{ ok: boolean; cleared: number }>('/chat/sessions', 'DELETE')
    } catch (e: any) {
      window.alert(e?.message || 'Sohbetler silinemedi')
      return
    }
    newChat()
    await qc.invalidateQueries({ queryKey: ['automic-chat-sessions'] })
  }

  const send = async (text?: string) => {
    const message = (text ?? input).trim()
    if (!message || loading || !selected) return
    setInput('')
    setPendingUser(message)
    setLoading(true)
    setStreaming('')
    setTools([])
    setProgress([{ step: 'sent', text: 'Soru gönderildi' }])
    setLiveComponents([])
    setPhase('tools')
    const ctrl = new AbortController()
    abortRef.current = ctrl
    let full = ''
    let comps: AutomicComponent[] = []
    let meta: Meta | null = null
    let sid = sessionId
    let toolsUsed: string[] = []
    let error: string | null = null
    try {
      const r = await fetch(`${AUTOMATION_API}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message, session_id: sessionId, system_id: selected.id,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Europe/Istanbul',
        }),
        signal: ctrl.signal,
      })
      if (!r.ok || !r.body) {
        const body = await r.json().catch(() => ({}))
        throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${r.status}`)
      }
      const reader = r.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        let idx
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const chunk = buf.slice(0, idx)
          buf = buf.slice(idx + 2)
          const line = chunk.split('\n').find(l => l.startsWith('data: '))
          if (!line) continue
          let ev: any
          try { ev = JSON.parse(line.slice(6)) } catch { continue }
          if (ev.session_id && !sid) {
            sid = ev.session_id
            setSessionId(ev.session_id)
          }
          if (ev.phase) setPhase(ev.phase)
          if (ev.type === 'progress') {
            // 'thinking' ve 'answering' geçici durumlardır: bir sonraki adım gelince yerini bırakır
            setProgress(p => {
              const keep = p.filter(x => x.step !== 'sent' && x.step !== 'thinking' && x.step !== 'answering')
              return [...keep, { step: ev.step, text: ev.text, tool: ev.tool, count: ev.count }]
            })
          } else if (ev.type === 'tool_call') {
            setTools(t => [...t, { tool: ev.tool, label: ev.label, done: false }])
          } else if (ev.type === 'tool_result') {
            toolsUsed = [...toolsUsed, ev.tool]
            setTools(t => {
              const i = t.findIndex(x => x.tool === ev.tool && !x.done)
              if (i < 0) return [...t, { tool: ev.tool, done: true, fallback: !!ev.fallback }]
              const next = [...t]
              next[i] = { ...next[i], done: true }
              return next
            })
          } else if (ev.type === 'components') {
            comps = ev.components || []
            setLiveComponents(comps)
          } else if (ev.type === 'meta') {
            meta = ev.meta
          } else if (typeof ev.error === 'string') {
            error = ev.error
          } else if (typeof ev.token === 'string') {
            full += ev.token
            setStreaming(full)
          }
        }
      }
    } catch (e: any) {
      if (e?.name === 'AbortError') error = 'Durduruldu'
      else error = e?.message || 'Bağlantı hatası'
    }
    const finalText = full || (error ? `_${error}_` : '')
    setMessages(m => [
      ...m,
      { id: `u-${Date.now()}`, role: 'user', content: message },
      { id: `a-${Date.now()}`, role: 'assistant', content: finalText, meta: { automic: meta, components: comps, tools_used: toolsUsed, error } },
    ])
    setPendingUser(null)
    setStreaming('')
    setLiveComponents([])
    setTools([])
    setProgress([])
    setPhase(null)
    setLoading(false)
    abortRef.current = null
    qc.invalidateQueries({ queryKey: ['automic-chat-sessions'] })
  }

  useEffect(() => {
    const q = params.get('q')
    if (!q || autoSent.current || !selected) return
    autoSent.current = true
    const next = new URLSearchParams(params)
    next.delete('q')
    setParams(next, { replace: true })
    void send(q)
  }, [params, selected]) // eslint-disable-line react-hooks/exhaustive-deps

  const filteredSessions = (sessions.data ?? []).filter(s => !search || s.title.toLowerCase().includes(search.toLowerCase()))

  if (systems.isLoading) return <div className="p-6 text-sm text-slate-400">Yükleniyor…</div>
  if (!selected) return <NoSystemNotice />

  return (
    <NlChatRoot>
      <NlHistorySidebar
        sessions={filteredSessions}
        selectedId={sessionId}
        search={search}
        onSearchChange={setSearch}
        onSelect={openSession}
        onNew={newChat}
        onDelete={deleteSession}
        onClearAll={clearAll}
        loading={sessions.isLoading}
      />
      <NlChatPanel>
        <NlTopBar>
          <div className="flex items-center gap-2">
            <Workflow size={16} className="text-amber-300" />
            <span className="text-sm font-semibold text-white">UC4 Automic Asistanı</span>
            <span className="rounded bg-slate-700/60 px-1.5 py-0.5 text-[10px] text-slate-300">salt okunur</span>
          </div>
          <div className="ml-auto">
            <SystemPicker systems={systems.data ?? []} value={selected.id} onChange={setSystem} />
          </div>
        </NlTopBar>
        <div ref={listRef} className="flex-1 overflow-y-auto px-4 py-4 min-h-0">
          <div className={nlChatColumnClass}>
            {messages.length === 0 && !pendingUser && (
              <NlEmptyState
                icon={<Workflow size={26} className="text-white" />}
                title="Automic çalışmalarını sorgulayın"
                description="Hatalı işler, aktif çalışmalar, süre sapmaları ve hata nedenleri hakkında soru sorun. Asistan yalnızca okuma yapar; Automic'te hiçbir işlem başlatmaz."
                suggestions={SUGGESTIONS}
                onSelectSuggestion={q => send(q)}
              />
            )}
            {messages.map(m => (
              m.role === 'user'
                ? <UserBubble key={m.id} text={m.content} />
                : <AssistantBubble key={m.id} msg={m} systemId={selected.id} onFollowUp={q => send(q)} disabled={loading} />
            ))}
            {pendingUser && <UserBubble text={pendingUser} />}
            {loading && (
              <div className="mb-4 space-y-2">
                {progress.length > 0
                  ? <ProgressLine steps={progress} compact={!!streaming} />
                  : tools.length > 0 && <ToolSteps steps={tools} />}
                {liveComponents.length > 0 && (
                  <div className={nlAssistantBubbleClass}><AutomicComponents components={liveComponents} /></div>
                )}
                {streaming ? (
                  <div className={nlAssistantBubbleClass}>
                    <AutomicMarkdown text={streaming} streaming />
                  </div>
                ) : progress.length === 0 ? (
                  <NlTypingRow label={phase === 'answering' ? 'Yanıt yazılıyor…' : phase === 'fallback_tools' ? 'Veriler doğrudan okunuyor…' : 'Automic verileri sorgulanıyor…'} />
                ) : null}
              </div>
            )}
          </div>
        </div>
        <NlChatInput
          value={input}
          onChange={setInput}
          onSubmit={() => send()}
          onAbort={() => abortRef.current?.abort()}
          loading={loading}
          placeholder="Automic hakkında sorun… (örn. bugün hata veren SAP job'ları)"
        />
      </NlChatPanel>
    </NlChatRoot>
  )
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="mb-4 flex justify-end">
      <div className={nlUserBubbleClass}><p className="whitespace-pre-wrap">{text}</p></div>
    </div>
  )
}

/** Cevap alanının üstünde kısa ilerleme satırı. Cevap akmaya başlayınca sadeleşir (yalnız özet). */
function ProgressLine({ steps, compact }: { steps: ProgressStep[]; compact: boolean }) {
  const last = steps[steps.length - 1]
  const isActive = (i: number) => i === steps.length - 1 && !compact
  if (compact) {
    const found = steps.filter(s => s.step === 'found')
    const total = found.reduce((a, s) => a + (s.count ?? 0), 0)
    return (
      <div className="flex items-center gap-1.5 text-[11px] text-slate-500" data-testid="automic-progress-compact">
        <Check size={11} className="text-green-400/70" />
        <span>{found.length > 0 ? `${found.length} sorgu · ${total.toLocaleString('tr-TR')} kayıt` : 'Veriler okundu'}</span>
      </div>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]" data-testid="automic-progress"
      role="status" aria-live="polite" aria-label={last?.text}>
      {steps.map((s, i) => (
        <span key={`${s.step}-${i}`} className={`inline-flex items-center gap-1 ${isActive(i) ? 'text-slate-100' : 'text-slate-400'}`}>
          {isActive(i)
            ? <Wrench size={11} className="animate-pulse text-blue-300" />
            : <Check size={11} className="text-green-400/80" />}
          {s.text}{isActive(i) ? '…' : ''}
          {i < steps.length - 1 && <ArrowRight size={9} className="ml-1 text-slate-600" />}
        </span>
      ))}
    </div>
  )
}

function ToolSteps({ steps }: { steps: ToolStep[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {steps.map((s, i) => (
        <span key={i} className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] ${s.done
          ? 'border-green-500/30 bg-green-500/10 text-green-300' : 'border-slate-600 bg-slate-800 text-slate-300'}`}>
          {s.done ? <Check size={11} /> : <Wrench size={11} className="animate-pulse" />}
          {TOOL_LABELS[s.tool] ?? s.label ?? s.tool}{s.fallback ? ' (doğrudan)' : ''}
        </span>
      ))}
    </div>
  )
}

function AssistantBubble({ msg, systemId, onFollowUp, disabled }: {
  msg: Msg
  systemId: number
  onFollowUp: (q: string) => void
  disabled: boolean
}) {
  const meta = msg.meta?.automic ?? null
  const comps = msg.meta?.components ?? []
  const sid = Number(meta?.scope?.system_id ?? systemId) || systemId
  const ents = (meta?.entities ?? []).filter(e =>
    (e.kind === 'execution' && e.run_id && e.client != null) || (e.kind === 'object' && e.object_name))
  return (
    <div className="mb-5 space-y-2">
      {comps.length > 0 && <div className={nlAssistantBubbleClass}><AutomicComponents components={comps} /></div>}
      <div className={nlAssistantBubbleClass}>
        <AutomicMarkdown text={msg.content} severity={meta?.severity ?? 'info'} />
        {ents.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5 border-t border-white/[0.06] pt-2">
            {ents.slice(0, 12).map((e, i) => (
              <Link key={i}
                to={e.kind === 'execution' ? executionPath(sid, Number(e.client), Number(e.run_id)) : objectPath(sid, String(e.object_name))}
                className="inline-flex items-center gap-1 rounded-md border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-[11px] text-blue-200 hover:bg-blue-500/20">
                {e.kind === 'execution' ? `RunID ${e.run_id}` : e.object_name}<ArrowRight size={10} />
              </Link>
            ))}
          </div>
        )}
        <AnswerFooter scope={meta?.scope} confidence={meta?.confidence} tools={msg.meta?.tools_used} />
      </div>
      {meta?.follow_ups && meta.follow_ups.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {meta.follow_ups.map(f => (
            <button key={f} type="button" disabled={disabled} onClick={() => onFollowUp(f)}
              className="rounded-full border border-slate-600/60 bg-slate-800/70 px-3 py-1 text-xs text-slate-300 hover:border-blue-500/40 hover:text-white disabled:opacity-50">
              {f}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
