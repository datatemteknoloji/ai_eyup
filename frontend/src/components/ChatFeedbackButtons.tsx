/**
 * Asistan mesajı altında 👍 / 👎 (+ isteğe bağlı düzeltme).
 * POST /api/v1/chat/feedback → platform-scoped QA cache.
 */
import { useState } from 'react'
import { ThumbsUp, ThumbsDown } from 'lucide-react'
import { API_BASE_URL } from '../config/api'

export type ChatFeedbackPlatform =
  | 'linux'
  | 'windows'
  | 'unified'
  | 'virt'
  | 'openshift'
  | 'exadata'

type Props = {
  platform: ChatFeedbackPlatform
  question: string
  answer: string
  serverIds?: number[]
  sessionId?: number | null
  messageId?: number
}

export default function ChatFeedbackButtons({
  platform,
  question,
  answer,
  serverIds,
  sessionId,
  messageId,
}: Props) {
  const [vote, setVote] = useState<'up' | 'down' | null>(null)
  const [busy, setBusy] = useState(false)
  const [showCorrect, setShowCorrect] = useState(false)
  const [correction, setCorrection] = useState('')
  const [hint, setHint] = useState('')

  if (!question?.trim() || !answer?.trim() || answer.length < 20) return null

  const send = async (v: 'up' | 'down', correctionText?: string) => {
    if (busy || vote) return
    setBusy(true)
    setHint('')
    try {
      const res = await fetch(`${API_BASE_URL}/chat/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          platform,
          question,
          answer,
          server_ids: serverIds?.length ? serverIds : undefined,
          session_id: sessionId ?? undefined,
          message_id: messageId,
          vote: v,
          correction_text: correctionText || undefined,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err?.detail || res.statusText)
      }
      setVote(v)
      setHint(v === 'up' ? 'Teşekkürler — cevap güçlendirildi' : 'Kaydedildi — bu cevap tekrar önerilmeyecek')
      setShowCorrect(false)
    } catch (e: any) {
      setHint(e?.message || 'Gönderilemedi')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-2 flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          disabled={busy || !!vote}
          onClick={() => send('up')}
          className={`text-xs px-2 py-1 rounded border flex items-center gap-1 transition-colors ${
            vote === 'up'
              ? 'bg-emerald-700/50 border-emerald-500/50 text-emerald-100'
              : 'bg-white/[0.04] border-white/[0.08] text-slate-400 hover:text-emerald-300 hover:border-emerald-500/40'
          } disabled:opacity-50`}
          title="İyi cevap"
        >
          <ThumbsUp size={12} />
        </button>
        <button
          type="button"
          disabled={busy || !!vote}
          onClick={() => send('down')}
          className={`text-xs px-2 py-1 rounded border flex items-center gap-1 transition-colors ${
            vote === 'down'
              ? 'bg-rose-800/40 border-rose-500/40 text-rose-100'
              : 'bg-white/[0.04] border-white/[0.08] text-slate-400 hover:text-rose-300 hover:border-rose-500/40'
          } disabled:opacity-50`}
          title="Kötü cevap"
        >
          <ThumbsDown size={12} />
        </button>
        <button
          type="button"
          disabled={busy || vote === 'up'}
          onClick={() => setShowCorrect((s) => !s)}
          className="text-[11px] px-2 py-1 rounded text-slate-500 hover:text-slate-300 border border-transparent hover:border-white/[0.08]"
        >
          Düzelt
        </button>
        {hint && <span className="text-[10px] text-slate-500">{hint}</span>}
      </div>
      {showCorrect && !vote && (
        <div className="flex flex-col gap-1.5">
          <textarea
            value={correction}
            onChange={(e) => setCorrection(e.target.value)}
            rows={3}
            placeholder="Doğru cevabı yazın…"
            className="w-full text-xs bg-cyber-deep border border-white/[0.08] rounded-lg px-2 py-1.5 text-slate-200 placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-500/50"
          />
          <button
            type="button"
            disabled={busy || correction.trim().length < 10}
            onClick={() => send('up', correction.trim())}
            className="self-start text-xs px-2.5 py-1 rounded bg-blue-600/80 hover:bg-blue-500 text-white disabled:opacity-40"
          >
            Düzeltmeyi kaydet
          </button>
        </div>
      )}
    </div>
  )
}

/** listedeki assistant mesajından hemen önceki user sorusunu bul */
export function priorUserQuestion(
  messages: { id: number; role: string; content: string }[],
  assistantMsgId: number,
): string {
  const idx = messages.findIndex((m) => m.id === assistantMsgId)
  if (idx <= 0) return ''
  for (let i = idx - 1; i >= 0; i--) {
    if (messages[i].role === 'user') return messages[i].content || ''
  }
  return ''
}
