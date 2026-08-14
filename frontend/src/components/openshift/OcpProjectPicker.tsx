import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, Search, X } from 'lucide-react'
import { useT } from '../../i18n/LocaleProvider'
import type { OcpProject } from './ocpTypes'

type Props = {
  projects: OcpProject[]
  value: string
  onChange: (name: string) => void
  onQuery?: (q: string) => void
  disabled?: boolean
}

export default function OcpProjectPicker({ projects, value, onChange, onQuery, disabled }: Props) {
  const t = useT()
  const boxRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [hi, setHi] = useState(0)

  const selected = projects.find((p) => p.name === value)
  const selectedLabel = selected ? (selected.display_name || selected.name) : value

  const filtered = useMemo(() => {
    const qq = query.trim().toLowerCase()
    const user = projects.filter((p) => !p.is_system)
    const sys = projects.filter((p) => p.is_system)
    const match = (p: OcpProject) =>
      !qq
      || p.name.toLowerCase().includes(qq)
      || (p.display_name || '').toLowerCase().includes(qq)
    return { user: user.filter(match), sys: sys.filter(match) }
  }, [projects, query])

  const flat = useMemo(
    () => [...filtered.user, ...filtered.sys],
    [filtered.user, filtered.sys],
  )

  useEffect(() => {
    const id = window.setTimeout(() => onQuery?.(query), 300)
    return () => window.clearTimeout(id)
  }, [query, onQuery])

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  useEffect(() => {
    setHi(0)
  }, [query, open])

  const pick = (name: string) => {
    onChange(name)
    setQuery('')
    setOpen(false)
  }

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setOpen(true)
      setHi((i) => Math.min(i + 1, Math.max(0, flat.length - 1)))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHi((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (open && flat[hi]) pick(flat[hi].name)
      else setOpen(true)
    } else if (e.key === 'Escape') {
      setOpen(false)
      setQuery('')
    }
  }

  return (
    <div ref={boxRef} className="relative w-72">
      <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
      <input
        ref={inputRef}
        disabled={disabled}
        value={open ? query : (value ? selectedLabel : '')}
        placeholder={open ? t('ocp_search_project') : t('ocp_pick_project')}
        onChange={(e) => {
          setQuery(e.target.value)
          setOpen(true)
        }}
        onFocus={() => {
          setOpen(true)
          setQuery('')
        }}
        onKeyDown={onKey}
        autoComplete="off"
        spellCheck={false}
        title={t('ocp_project_title')}
        className="w-full rounded-lg border border-white/[0.08] bg-cyber-deep/80 text-sm text-slate-200 py-1.5 pl-8 pr-14 placeholder:text-slate-500 focus:outline-none focus:border-rose-500/40"
      />
      <div className="absolute right-1 top-1/2 -translate-y-1/2 flex items-center">
        {value && (
          <button
            type="button"
            className="p-1 rounded text-slate-500 hover:text-slate-200"
            title={t('close')}
            onClick={() => {
              onChange('')
              setQuery('')
              setOpen(false)
            }}
          >
            <X size={12} />
          </button>
        )}
        <button
          type="button"
          className="p-1 rounded text-slate-500 hover:text-slate-200"
          onClick={() => {
            setOpen((v) => !v)
            if (!open) inputRef.current?.focus()
          }}
        >
          <ChevronDown size={14} />
        </button>
      </div>

      {open && (
        <div className="absolute z-40 mt-1 w-full max-h-72 overflow-y-auto rounded-lg border border-white/[0.1] bg-cyber-card shadow-xl py-1">
          {flat.length === 0 ? (
            <div className="px-3 py-2 text-xs text-slate-500">{t('ocp_no_match_proj')}</div>
          ) : (
            <>
              {filtered.user.length > 0 && (
                <div className="px-2.5 py-1 text-[10px] uppercase tracking-wide text-slate-500">{t('ocp_user_projects')}</div>
              )}
              {filtered.user.map((p, i) => (
                <Row
                  key={p.name}
                  p={p}
                  active={p.name === value}
                  highlight={i === hi}
                  onPick={pick}
                />
              ))}
              {filtered.sys.length > 0 && (
                <div className="px-2.5 py-1 mt-1 text-[10px] uppercase tracking-wide text-slate-500">{t('ocp_system')}</div>
              )}
              {filtered.sys.map((p, i) => (
                <Row
                  key={p.name}
                  p={p}
                  active={p.name === value}
                  highlight={filtered.user.length + i === hi}
                  onPick={pick}
                />
              ))}
            </>
          )}
        </div>
      )}
    </div>
  )
}

function Row({
  p, active, highlight, onPick,
}: {
  p: OcpProject
  active: boolean
  highlight: boolean
  onPick: (name: string) => void
}) {
  const title = p.display_name || p.name
  return (
    <button
      type="button"
      onMouseDown={(e) => e.preventDefault()}
      onClick={() => onPick(p.name)}
      className={`w-full text-left px-3 py-1.5 text-sm truncate ${
        highlight ? 'bg-white/[0.08]' : ''
      } ${active ? 'text-amber-300' : 'text-slate-200'} hover:bg-white/[0.06]`}
    >
      <span className="font-medium">{title}</span>
      {title !== p.name && <span className="text-slate-500 text-xs ml-1.5 font-mono">{p.name}</span>}
    </button>
  )
}
