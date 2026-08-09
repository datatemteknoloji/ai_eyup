/**
 * Sanallaştırma (HypervisorChat) NL asistan UI kalıpları —
 * Linux / Windows / Unified / OpenShift / Exadata sohbetlerinde ortak kullanılır.
 */
import React, { useRef } from 'react'
import {
  History, Plus, Trash2, Search, Loader2, Send, Lightbulb,
} from 'lucide-react'

export type NlChatSession = {
  id: number
  title: string
  created_at: string
  updated_at?: string | null
  message_count: number
}

export function formatNlSessionDate(iso: string) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 86400000) return d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })
  if (diff < 604800000) return d.toLocaleDateString('tr-TR', { weekday: 'short' })
  return d.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' })
}

export function NlChatRoot({
  embedded,
  children,
}: {
  embedded?: boolean
  children: React.ReactNode
}) {
  return (
    <div
      className={`flex bg-slate-900 min-h-0 overflow-hidden ${
        embedded ? 'h-full' : '-m-5 h-[calc(100vh-3.5rem)]'
      }`}
    >
      {children}
    </div>
  )
}

export function NlHistorySidebar({
  sessions,
  selectedId,
  search = '',
  onSearchChange,
  onSelect,
  onNew,
  onDelete,
  onClearAll,
  loading,
}: {
  sessions: NlChatSession[]
  selectedId: number | null
  search?: string
  onSearchChange?: (v: string) => void
  onSelect: (id: number) => void
  onNew: () => void
  onDelete: (id: number) => void
  onClearAll: () => void
  loading?: boolean
}) {
  return (
    <div className="nl-history-sidebar w-64 flex-shrink-0 border-r border-slate-700/50 bg-slate-900/80 flex flex-col min-h-0">
      <div className="p-3 border-b border-slate-700/50 space-y-2 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs font-medium text-[var(--text-secondary)]">
            <History size={14} />
            Geçmiş
          </div>
          <div className="flex gap-1">
            <button
              type="button"
              onClick={onNew}
              className="p-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors"
              title="Yeni sohbet"
            >
              <Plus size={14} />
            </button>
            {sessions.length > 0 && (
              <button
                type="button"
                onClick={onClearAll}
                className="p-1.5 rounded-lg bg-slate-800 hover:bg-red-900/40 text-slate-400 hover:text-red-400 transition-colors"
                title="Tümünü sil"
              >
                <Trash2 size={14} />
              </button>
            )}
          </div>
        </div>
        {onSearchChange && (
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              value={search}
              onChange={e => onSearchChange(e.target.value)}
              placeholder="Sohbetlerde ara..."
              className="w-full bg-slate-800 border border-slate-700/50 rounded-lg pl-8 pr-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500/50"
            />
          </div>
        )}
      </div>
      <div className="flex-1 overflow-y-auto p-2 min-h-0">
        {loading ? (
          <div className="flex justify-center py-8">
            <Loader2 size={20} className="text-slate-500 animate-spin" />
          </div>
        ) : sessions.length === 0 ? (
          <div className="text-center py-8 px-2">
            <p className="text-xs text-slate-500">
              {search ? 'Arama sonucu yok' : 'Henüz sohbet yok'}
            </p>
            {!search && (
              <button type="button" onClick={onNew} className="mt-2 text-xs text-blue-400 hover:text-blue-300">
                + Yeni sohbet başlat
              </button>
            )}
          </div>
        ) : (
          sessions.map(session => (
            <div
              key={session.id}
              data-active={selectedId === session.id ? 'true' : 'false'}
              onClick={() => onSelect(session.id)}
              className={`nl-history-item group flex items-start gap-2 px-2.5 py-2 rounded-lg cursor-pointer mb-1 transition-colors ${
                selectedId === session.id
                  ? 'bg-blue-600/20 border border-blue-500/30'
                  : 'hover:bg-slate-800/80 border border-transparent'
              }`}
            >
              <div className="flex-1 min-w-0">
                <p className="nl-history-title text-xs font-medium text-slate-200 truncate">{session.title}</p>
                <p className="nl-history-meta text-[10px] text-slate-500 mt-0.5">
                  {session.message_count} mesaj · {formatNlSessionDate(session.updated_at || session.created_at)}
                </p>
              </div>
              <button
                type="button"
                onClick={e => { e.stopPropagation(); onDelete(session.id) }}
                className="opacity-0 group-hover:opacity-100 p-1 text-slate-500 hover:text-red-400 transition-opacity flex-shrink-0"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export function NlChatPanel({ children }: { children: React.ReactNode }) {
  return <div className="flex-1 flex flex-col min-w-0 min-h-0">{children}</div>
}

export function NlTopBar({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex-shrink-0 px-4 py-3 border-b border-slate-700/50 bg-slate-900/80">
      <div className="flex items-center gap-3 flex-wrap">{children}</div>
    </div>
  )
}

export function NlModelSelect({
  value,
  onChange,
  models,
  storageKey,
}: {
  value: string
  onChange: (v: string) => void
  models: { name: string; parameter_size?: string }[]
  storageKey?: string
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-slate-400 text-sm font-medium">Model:</span>
      <select
        value={value}
        onChange={e => {
          onChange(e.target.value)
          if (storageKey) localStorage.setItem(storageKey, e.target.value)
        }}
        className="px-4 py-2 bg-slate-800 border border-slate-600 rounded-xl text-white text-sm font-medium hover:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-400 cursor-pointer min-w-[180px]"
        style={{ appearance: 'auto' }}
      >
        {models.map(m => (
          <option key={m.name} value={m.name} className="bg-slate-900 text-white">
            {m.name} {m.parameter_size ? `(${m.parameter_size})` : ''}
          </option>
        ))}
      </select>
    </div>
  )
}

export function NlEmptyState({
  icon,
  title = 'Altyapınızı Sorgulayın',
  description,
  suggestions,
  onSelectSuggestion,
}: {
  icon: React.ReactNode
  title?: string
  description: string
  suggestions?: string[]
  onSelectSuggestion?: (q: string) => void
}) {
  return (
    <div className="max-w-2xl mx-auto mt-6 space-y-6">
      <div className="text-center space-y-2">
        <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-blue-600 to-indigo-700 flex items-center justify-center mx-auto shadow-xl shadow-blue-500/20">
          {icon}
        </div>
        <h2 className="text-lg font-semibold text-white">{title}</h2>
        <p className="text-slate-400 text-sm max-w-md mx-auto">{description}</p>
      </div>
      {suggestions && suggestions.length > 0 && onSelectSuggestion && (
        <div>
          <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
            <Lightbulb size={12} />
            <span>Örnek sorular</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {suggestions.slice(0, 8).map(s => (
              <button
                key={s}
                type="button"
                onClick={() => onSelectSuggestion(s)}
                className="text-xs px-3 py-1.5 rounded-full bg-slate-700/70 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-600/50 hover:border-blue-500/40 transition-all"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export function NlChatInput({
  value,
  onChange,
  onSubmit,
  onAbort,
  loading,
  placeholder = 'Sorunuzu yazın… (Enter ile gönder)',
  hint = 'Enter ile gönder · Shift+Enter yeni satır',
  extra,
}: {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  onAbort?: () => void
  loading?: boolean
  placeholder?: string
  hint?: string
  extra?: React.ReactNode
}) {
  const ref = useRef<HTMLTextAreaElement>(null)

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (!loading) onSubmit()
    }
  }

  return (
    <div className="px-4 pb-4 max-w-3xl mx-auto w-full flex-shrink-0">
      {extra}
      <div className="flex items-end gap-2 bg-slate-800 border border-slate-700/50 rounded-2xl px-4 py-3 focus-within:border-blue-500/50 transition-colors">
        <textarea
          ref={ref}
          value={value}
          onChange={e => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={loading ? 'AI düşünüyor...' : placeholder}
          rows={1}
          disabled={!!loading && !onAbort}
          className="flex-1 bg-transparent text-white placeholder-slate-500 text-sm resize-none focus:outline-none leading-relaxed disabled:opacity-70"
          style={{ maxHeight: '120px', overflowY: 'auto' }}
        />
        {loading && onAbort ? (
          <button
            type="button"
            onClick={onAbort}
            className="h-8 px-3 rounded-xl bg-rose-600 hover:bg-rose-500 text-white text-xs font-medium transition-all flex-shrink-0"
          >
            Durdur
          </button>
        ) : (
          <button
            type="button"
            onClick={onSubmit}
            disabled={!value.trim() || loading}
            className="w-8 h-8 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:opacity-50 flex items-center justify-center transition-all flex-shrink-0"
          >
            {loading ? (
              <Loader2 size={15} className="text-white animate-spin" />
            ) : (
              <Send size={15} className="text-white" />
            )}
          </button>
        )}
      </div>
      <p className="text-center text-[10px] text-slate-600 mt-1.5">{hint}</p>
    </div>
  )
}

/** Virt tarzı kullanıcı / asistan balon kabuğu */
export const nlUserBubbleClass =
  'min-w-0 max-w-[min(85%,48rem)] rounded-2xl rounded-tr-sm px-4 py-3 text-sm leading-relaxed overflow-hidden bg-blue-600 text-white'

export const nlAssistantBubbleClass =
  'min-w-0 max-w-[min(85%,48rem)] rounded-2xl rounded-tl-sm px-4 py-3 text-sm leading-relaxed overflow-hidden bg-slate-800 text-slate-100 border border-slate-700/50'

export function NlTypingRow({ label = 'Altyapı analiz ediliyor...' }: { label?: string }) {
  return (
    <div className="flex justify-start mb-4">
      <div className="bg-slate-800 border border-slate-700/50 rounded-2xl rounded-tl-sm px-4 py-3">
        <div className="flex items-center gap-1.5">
          <Loader2 size={14} className="text-blue-400 animate-spin" />
          <span className="text-xs text-slate-400">{label}</span>
        </div>
      </div>
    </div>
  )
}
