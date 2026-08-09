/**
 * Chat / Bilgi Bankası — gerçeği sabitle (POST /knowledge/correct).
 * Yalnızca admin; operator/viewer butonu görmez.
 */
import { useEffect, useState } from 'react'
import { Pin } from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { useAuth } from '../auth/AuthContext'

export type PinServerOption = { id: number; name: string }

type Props = {
  serverIds?: number[]
  serverOptions?: PinServerOption[]
  compact?: boolean
  className?: string
}

export default function ChatPinFact({
  serverIds,
  serverOptions,
  compact = true,
  className = '',
}: Props) {
  const { user } = useAuth()
  const isAdmin = Boolean(user?.is_admin || user?.role === 'admin')

  const [open, setOpen] = useState(false)
  const [fetchedOptions, setFetchedOptions] = useState<PinServerOption[]>([])
  const [serverId, setServerId] = useState<number | ''>(() =>
    serverIds?.length ? serverIds[0] : '',
  )
  const [key, setKey] = useState('')
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [hint, setHint] = useState('')

  useEffect(() => {
    if (!isAdmin || !open || (serverOptions && serverOptions.length > 0)) return
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetch(`${API_BASE_URL}/servers/?page=1&page_size=200`)
        if (r.ok) {
          const data = await r.json()
          const items = data?.items || []
          if (Array.isArray(items) && items.length && !cancelled) {
            setFetchedOptions(
              items.map((s: any) => ({ id: s.id, name: s.name || `#${s.id}` })),
            )
            return
          }
        }
        const r2 = await fetch(`${API_BASE_URL}/knowledge/summary`)
        if (!r2.ok) return
        const data = await r2.json()
        const opts = (data?.servers || []).map((s: any) => ({
          id: s.server_id,
          name: s.server_name || `#${s.server_id}`,
        }))
        if (!cancelled) setFetchedOptions(opts)
      } catch {
        /* ignore */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [open, serverOptions, isAdmin])

  if (!isAdmin) return null

  const options: PinServerOption[] = (() => {
    if (serverOptions?.length) return serverOptions
    if (fetchedOptions.length) return fetchedOptions
    if (serverIds?.length) {
      return serverIds.map((id) => ({ id, name: `Sunucu #${id}` }))
    }
    return []
  })()

  const effectiveServer =
    serverId !== ''
      ? Number(serverId)
      : options.length === 1
        ? options[0].id
        : serverIds?.[0]

  const submit = async () => {
    if (busy) return
    const sid = effectiveServer
    const k = key.trim()
    const v = value.trim()
    if (!sid || !k || !v) {
      setHint('Sunucu, anahtar ve değer gerekli')
      return
    }
    if (k.length > 200 || v.length > 2000) {
      setHint('Anahtar/değer çok uzun')
      return
    }
    setBusy(true)
    setHint('')
    try {
      const res = await fetch(`${API_BASE_URL}/knowledge/correct`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          server_id: sid,
          key: k,
          value: v,
          category: 'correction',
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(
          typeof err?.detail === 'string'
            ? err.detail
            : err?.detail?.[0]?.msg || res.statusText,
        )
      }
      setHint('Sabitlendi — bilgi bankası + RAG güncellenecek')
      setKey('')
      setValue('')
      setOpen(false)
    } catch (e: any) {
      setHint(e?.message || 'Kaydedilemedi')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={
          compact
            ? 'text-[11px] px-2 py-1 rounded text-slate-500 hover:text-amber-300 border border-transparent hover:border-white/[0.08] inline-flex items-center gap-1 self-start'
            : 'text-xs px-2.5 py-1.5 rounded-lg bg-white/[0.04] border border-white/[0.08] text-slate-300 hover:text-amber-200 inline-flex items-center gap-1.5'
        }
        title="Yalnızca admin — sunucu için kalıcı bilgi sabitle"
      >
        <Pin size={12} /> Gerçeği sabitle
      </button>
      {hint && !open && <span className="text-[10px] text-slate-500">{hint}</span>}
      {open && (
        <div className="flex flex-col gap-1.5 p-2 rounded-lg border border-amber-500/20 bg-cyber-deep/80">
          <div className="text-[10px] text-amber-200/80">
            Admin işlemi — asistan bunu kalıcı gerçek sayar; canlı veri çelişirse canlı kazanır.
          </div>
          <select
            value={effectiveServer ?? ''}
            onChange={(e) => setServerId(e.target.value ? Number(e.target.value) : '')}
            className="text-xs bg-cyber-deep border border-white/[0.08] rounded-lg px-2 py-1.5 text-slate-200"
          >
            <option value="">Sunucu seçin</option>
            {options.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          {!options.length && (
            <div className="text-[10px] text-slate-500">
              Sunucu listesi yok — önce envanter/AI-ready sunucu ekleyin.
            </div>
          )}
          <input
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="Anahtar (örn. os.hostname)"
            maxLength={200}
            className="text-xs bg-cyber-deep border border-white/[0.08] rounded-lg px-2 py-1.5 text-slate-200 placeholder:text-slate-600"
          />
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Doğru değer"
            maxLength={2000}
            className="text-xs bg-cyber-deep border border-white/[0.08] rounded-lg px-2 py-1.5 text-slate-200 placeholder:text-slate-600"
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={busy || !key.trim() || !value.trim() || !effectiveServer}
              onClick={submit}
              className="text-xs px-2.5 py-1 rounded bg-amber-600/80 hover:bg-amber-500 text-white disabled:opacity-40"
            >
              {busy ? '…' : 'Sabitle'}
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-[11px] text-slate-500 hover:text-slate-300"
            >
              İptal
            </button>
            {hint && <span className="text-[10px] text-slate-500">{hint}</span>}
          </div>
        </div>
      )}
    </div>
  )
}
