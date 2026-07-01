/**
 * Modül Yönetimi — Admin
 * Kullanıcılara platform modülü atama/kaldırma.
 * Admin kullanıcılar tüm modüllere otomatik erişir.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Server, Shield, Cloud, Brain, Bot, FileUp, Wrench,
  CheckCircle2, Save, Users, Package, AlertTriangle,
  ChevronDown, ChevronUp, RefreshCw,
} from 'lucide-react'
import { API_BASE_URL } from '../config/api'

// ── Types ─────────────────────────────────────────────────────────────────────

interface ModuleInfo {
  id: string; name: string; description: string
  icon: string; color: string; sort_order: number; is_active: boolean
}

interface UserModuleSummary {
  user_id: number; username: string; full_name: string | null
  role: string; is_active: boolean; modules: string[]
}

// ── Icon map ──────────────────────────────────────────────────────────────────

const MODULE_ICONS: Record<string, React.ReactNode> = {
  Server:  <Server size={16} />,
  Shield:  <Shield size={16} />,
  Cloud:   <Cloud size={16} />,
  Brain:   <Brain size={16} />,
  Bot:     <Bot size={16} />,
  FileUp:  <FileUp size={16} />,
  Wrench:  <Wrench size={16} />,
  Package: <Package size={16} />,
}

const MODULE_COLOR: Record<string, string> = {
  green:  'text-green-400 bg-green-500/10 border-green-500/30',
  blue:   'text-blue-400 bg-blue-500/10 border-blue-500/30',
  indigo: 'text-indigo-400 bg-indigo-500/10 border-indigo-500/30',
  purple: 'text-purple-400 bg-purple-500/10 border-purple-500/30',
  cyan:   'text-cyan-400 bg-cyan-500/10 border-cyan-500/30',
  orange: 'text-orange-400 bg-orange-500/10 border-orange-500/30',
  teal:   'text-teal-400 bg-teal-500/10 border-teal-500/30',
}

const ROLE_BADGE: Record<string, string> = {
  admin:    'bg-red-500/20 text-red-300 border-red-500/40',
  operator: 'bg-blue-500/20 text-blue-300 border-blue-500/40',
  viewer:   'bg-slate-700/40 text-slate-400 border-slate-600/40',
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function fetchJSON<T>(url: string): Promise<T> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

async function putJSON(url: string, body: unknown) {
  const r = await fetch(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

// ── Module toggle cell ────────────────────────────────────────────────────────

function ModuleCell({
  enabled, isAdmin, pending, onChange
}: {
  enabled: boolean; isAdmin: boolean; pending: boolean; onChange: () => void
}) {
  if (isAdmin) {
    return (
      <div className="flex justify-center">
        <span title="Admin — tüm modüller">
          <CheckCircle2 size={18} className="text-slate-500" />
        </span>
      </div>
    )
  }
  return (
    <div className="flex justify-center">
      <button
        onClick={onChange}
        disabled={pending}
        className={`w-9 h-5 rounded-full relative transition-colors duration-200 focus:outline-none disabled:opacity-60 ${
          enabled ? 'bg-cyan-500' : 'bg-slate-700'
        }`}
      >
        <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform duration-200 ${
          enabled ? 'left-[18px]' : 'left-0.5'
        }`} />
      </button>
    </div>
  )
}

// ── User row ──────────────────────────────────────────────────────────────────

function UserModuleRow({
  user, modules, onSave
}: {
  user: UserModuleSummary
  modules: ModuleInfo[]
  onSave: (userId: number, moduleIds: string[]) => Promise<void>
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set(user.modules))
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [expanded, setExpanded] = useState(false)

  const isDirty = JSON.stringify([...selected].sort()) !== JSON.stringify([...user.modules].sort())

  const toggle = (mid: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(mid)) next.delete(mid)
      else next.add(mid)
      return next
    })
    setSaved(false)
  }

  const save = async () => {
    setSaving(true)
    try {
      await onSave(user.user_id, [...selected])
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={`border rounded-2xl overflow-hidden transition-all ${
      user.role === 'admin' ? 'border-slate-700/40 bg-slate-900/30' : 'border-slate-700/60 bg-slate-900/50'
    }`}>
      {/* Header row */}
      <div className="flex items-center gap-4 px-5 py-3">
        {/* User info */}
        <div className="flex items-center gap-3 flex-1 min-w-0">
          <div className="w-8 h-8 rounded-full bg-slate-700 flex items-center justify-center text-sm font-bold text-white shrink-0">
            {(user.full_name || user.username)[0].toUpperCase()}
          </div>
          <div className="min-w-0">
            <div className="font-medium text-white text-sm truncate">
              {user.full_name || user.username}
            </div>
            <div className="text-xs text-slate-500">@{user.username}</div>
          </div>
          <span className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold shrink-0 ${ROLE_BADGE[user.role] ?? ROLE_BADGE.operator}`}>
            {user.role}
          </span>
        </div>

        {/* Module toggles (inline, compact) */}
        <div className="flex items-center gap-3 flex-wrap">
          {modules.map(m => (
            <div key={m.id} className="flex items-center gap-1.5 text-xs" title={m.name}>
              <span className={`p-1 rounded-lg border ${MODULE_COLOR[m.color] ?? MODULE_COLOR.blue}`}>
                {MODULE_ICONS[m.icon] ?? <Package size={16} />}
              </span>
              <ModuleCell
                enabled={selected.has(m.id)}
                isAdmin={user.role === 'admin'}
                pending={saving}
                onChange={() => toggle(m.id)}
              />
            </div>
          ))}
        </div>

        {/* Save + expand */}
        <div className="flex items-center gap-2 shrink-0">
          {isDirty && !user.role.includes('admin') && (
            <button onClick={save} disabled={saving}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-medium transition-colors disabled:opacity-60">
              {saving ? <RefreshCw size={12} className="animate-spin" /> : <Save size={12} />}
              {saving ? 'Kaydediliyor' : 'Kaydet'}
            </button>
          )}
          {saved && (
            <span className="flex items-center gap-1 text-xs text-green-400">
              <CheckCircle2 size={12} /> Kaydedildi
            </span>
          )}
          {user.role === 'admin' && (
            <span className="text-xs text-slate-600 italic">Tam erişim</span>
          )}
          <button onClick={() => setExpanded(v => !v)} className="text-slate-600 hover:text-slate-300 transition-colors">
            {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-slate-700/50 px-5 py-4">
          <div className="grid grid-cols-2 gap-3">
            {modules.map(m => (
              <div key={m.id} className={`flex items-center gap-3 p-3 rounded-xl border ${
                selected.has(m.id) || user.role === 'admin'
                  ? `${MODULE_COLOR[m.color] ?? MODULE_COLOR.blue} border-opacity-50`
                  : 'bg-slate-800/30 border-slate-700/40'
              }`}>
                <span className={MODULE_COLOR[m.color] ? `text-${m.color}-400` : 'text-slate-400'}>
                  {MODULE_ICONS[m.icon] ?? <Package size={16} />}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-white">{m.name}</div>
                  <div className="text-xs text-slate-500 truncate">{m.description}</div>
                </div>
                {user.role !== 'admin' ? (
                  <button onClick={() => toggle(m.id)} disabled={saving}
                    className={`w-9 h-5 rounded-full relative transition-colors disabled:opacity-60 shrink-0 ${
                      selected.has(m.id) ? 'bg-cyan-500' : 'bg-slate-700'
                    }`}>
                    <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${
                      selected.has(m.id) ? 'left-[18px]' : 'left-0.5'
                    }`} />
                  </button>
                ) : (
                  <CheckCircle2 size={16} className="text-slate-500 shrink-0" />
                )}
              </div>
            ))}
          </div>
          {isDirty && user.role !== 'admin' && (
            <div className="flex items-center justify-between mt-4 pt-3 border-t border-slate-700/50">
              <span className="text-xs text-amber-400 flex items-center gap-1.5">
                <AlertTriangle size={12} /> Kaydedilmemiş değişiklikler var
              </span>
              <div className="flex gap-2">
                <button onClick={() => { setSelected(new Set(user.modules)); setSaved(false) }}
                  className="text-xs px-3 py-1.5 rounded-xl border border-slate-600 text-slate-400 hover:bg-slate-700 transition-colors">
                  İptal
                </button>
                <button onClick={save} disabled={saving}
                  className="flex items-center gap-1.5 text-xs px-4 py-1.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-medium transition-colors disabled:opacity-60">
                  {saving ? <RefreshCw size={12} className="animate-spin" /> : <Save size={12} />}
                  Kaydet
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function ModuleManager() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')

  const { data: modules, isLoading: modsLoading } = useQuery<ModuleInfo[]>({
    queryKey: ['modules-list'],
    queryFn: () => fetchJSON(`${API_BASE_URL}/modules/`),
    staleTime: 60_000,
  })

  const { data: userMods, isLoading: usersLoading } = useQuery<UserModuleSummary[]>({
    queryKey: ['modules-users'],
    queryFn: () => fetchJSON(`${API_BASE_URL}/modules/users`),
    staleTime: 30_000,
  })

  const saveMutation = useMutation({
    mutationFn: ({ userId, moduleIds }: { userId: number; moduleIds: string[] }) =>
      putJSON(`${API_BASE_URL}/modules/users/${userId}`, { module_ids: moduleIds }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['modules-users'] }),
  })

  const filteredUsers = (userMods ?? []).filter(u =>
    !search ||
    u.username.toLowerCase().includes(search.toLowerCase()) ||
    (u.full_name ?? '').toLowerCase().includes(search.toLowerCase())
  )

  const isLoading = modsLoading || usersLoading

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Package size={20} className="text-cyan-400" />
            Modül Yönetimi
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Kullanıcılara platform modülü erişimi tanımlayın. Admin rolü tüm modüllere otomatik erişir.
          </p>
        </div>
      </div>

      {/* Module legend */}
      {modules && (
        <div className="grid grid-cols-4 gap-3">
          {modules.map(m => (
            <div key={m.id}
              className={`flex items-center gap-3 p-3 rounded-xl border ${MODULE_COLOR[m.color] ?? MODULE_COLOR.blue}`}>
              {MODULE_ICONS[m.icon] ?? <Package size={16} />}
              <div className="min-w-0">
                <div className="text-sm font-medium text-white">{m.name}</div>
                <div className="text-xs text-slate-500 truncate">{m.description}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* User filter */}
      <div className="flex items-center gap-3">
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Kullanıcı ara…"
          className="bg-slate-800 border border-slate-700 text-white text-sm rounded-xl px-4 py-2 w-64 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 placeholder-slate-600"
        />
        <div className="flex items-center gap-1.5 text-xs text-slate-500">
          <Users size={13} /> {filteredUsers.length} kullanıcı
        </div>
      </div>

      {/* User list */}
      {isLoading ? (
        <div className="text-center py-16 text-slate-500">Yükleniyor…</div>
      ) : (
        <div className="space-y-3">
          {/* Column headers */}
          {modules && filteredUsers.length > 0 && (
            <div className="flex items-center gap-4 px-5 py-2 text-xs text-slate-600 font-medium">
              <div className="flex-1">Kullanıcı</div>
              <div className="flex items-center gap-3 flex-wrap">
                {modules.map(m => (
                  <div key={m.id} className="flex flex-col items-center gap-0.5 w-[60px]" title={m.name}>
                    <span className="text-slate-500 text-[10px] text-center leading-tight truncate w-full text-center">
                      {m.name.split(' ')[0]}
                    </span>
                  </div>
                ))}
              </div>
              <div className="w-24 shrink-0" />
            </div>
          )}

          {filteredUsers.map(u => (
            <UserModuleRow
              key={u.user_id}
              user={u}
              modules={modules ?? []}
              onSave={(userId, moduleIds) => saveMutation.mutateAsync({ userId, moduleIds })}
            />
          ))}

          {filteredUsers.length === 0 && (
            <div className="text-center py-12 text-slate-600 text-sm">
              {search ? 'Arama kriterine uyan kullanıcı yok.' : 'Kullanıcı bulunamadı.'}
            </div>
          )}
        </div>
      )}

      {/* Info box */}
      <div className="bg-slate-800/40 border border-slate-700/50 rounded-2xl p-4 flex items-start gap-3">
        <AlertTriangle size={16} className="text-amber-400 shrink-0 mt-0.5" />
        <div className="text-sm text-slate-400 space-y-1">
          <p>
            <span className="text-white font-medium">Admin</span> rolündeki kullanıcılar modül atamalarından bağımsız olarak tüm modüllere erişir.
          </p>
          <p>
            Değişiklikler kullanıcı sayfayı yenilediğinde veya tekrar giriş yaptığında aktif olur.
          </p>
        </div>
      </div>
    </div>
  )
}
