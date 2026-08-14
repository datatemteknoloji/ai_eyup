/**
 * Kullanıcı Yönetimi — Admin
 * Matris görünümü: kullanıcılar satır, modüller sütun.
 * Toggle anında kaydeder (TanStack Query optimistic update).
 * Ayrı Modül Yönetimi sayfası yoktur — her şey burada.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  UserPlus, Pencil, Trash2, KeyRound, Check, X, AlertTriangle,
  ShieldCheck, Eye, Search, RefreshCw, CheckCircle2, UserX, UserCheck,
  Package, Server, Shield, Cloud, Brain, Bot, FileUp, Wrench, Database,
} from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { useAuth } from '../auth/AuthContext'
import { useT, readStoredLocale } from '../i18n/LocaleProvider'
import { dictionaries, type TranslationKey } from '../i18n/messages'

// ── Types ─────────────────────────────────────────────────────────────────────

interface UserItem {
  id: number; username: string; email: string | null; full_name: string | null
  role: 'admin' | 'operator' | 'viewer'; is_active: boolean
  auth_source?: 'local' | 'ad' | 'sso'
  last_login: string | null; created_at: string | null
}
interface ModuleInfo {
  id: string; name: string; description: string
  icon: string; color: string; sort_order: number; is_active: boolean
}
interface UserModuleSummary {
  user_id: number; username: string; full_name: string | null
  role: string; is_active: boolean; modules: string[]
}

// ── Sabitler ──────────────────────────────────────────────────────────────────

const ROLE_BADGE: Record<string, string> = {
  admin:    'bg-red-500/20 text-red-300 border-red-500/40',
  operator: 'bg-blue-500/20 text-blue-300 border-blue-500/40',
  viewer:   'bg-slate-700/40 text-slate-400 border-slate-600/40',
}
const ROLE_ICON: Record<string, React.ReactNode> = {
  admin: <ShieldCheck size={11} />, operator: <UserCheck size={11} />, viewer: <Eye size={11} />,
}
const ROLE_LABEL: Record<string, string> = { admin: 'Admin', operator: 'Operator', viewer: 'Viewer' }

const MODULE_ICONS: Record<string, React.ReactNode> = {
  Server: <Server size={14} />, Shield: <Shield size={14} />, Cloud: <Cloud size={14} />,
  Brain: <Brain size={14} />, Bot: <Bot size={14} />, FileUp: <FileUp size={14} />,
  Wrench: <Wrench size={14} />, Package: <Package size={14} />, Database: <Database size={14} />,
}
const MOD_COLOR_TEXT: Record<string, string> = {
  green: 'text-green-400', blue: 'text-blue-400', indigo: 'text-indigo-400',
  purple: 'text-sky-400', cyan: 'text-cyan-400', orange: 'text-orange-400', teal: 'text-teal-400',
}
const MOD_COLOR_DOT: Record<string, string> = {
  green: 'bg-green-400', blue: 'bg-blue-400', indigo: 'bg-indigo-400',
  purple: 'bg-sky-400', cyan: 'bg-cyan-400', orange: 'bg-orange-400', teal: 'bg-teal-400',
}

// ── API ───────────────────────────────────────────────────────────────────────

async function apiFetch(method: string, path: string, body?: unknown) {
  const r = await fetch(`${API_BASE_URL}${path}`, {
    method, headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: r.statusText }))
    throw new Error(e.detail ?? dictionaries[readStoredLocale()].usr_req_fail)
  }
  return r.json()
}

function relTime(iso: string | null, t: (key: TranslationKey, vars?: Record<string, string | number>) => string) {
  if (!iso) return '—'
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (m < 1) return t('just_now'); if (m < 60) return t('usr_mins', { n: m })
  const h = Math.floor(m / 60); if (h < 24) return t('usr_hours', { n: h })
  return t('usr_days', { n: Math.floor(h / 24) })
}

// ── Avatar ────────────────────────────────────────────────────────────────────

function Avatar({ user }: { user: UserItem }) {
  const c: Record<string, string> = {
    admin: 'bg-red-500/30 text-red-200', operator: 'bg-blue-500/30 text-blue-200',
    viewer: 'bg-slate-600 text-slate-300',
  }
  return (
    <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-sm font-bold shrink-0 ${c[user.role] ?? c.viewer}`}>
      {((user.full_name || user.username)[0] ?? '?').toUpperCase()}
    </div>
  )
}

// ── Kullanıcı / Modül Formu (Ekle + Düzenle) ─────────────────────────────────

function UserModal({ user, modules, currentModuleIds, onClose, onSaved }: {
  user?: UserItem; modules: ModuleInfo[]; currentModuleIds?: string[]
  onClose: () => void; onSaved: () => void
}) {
  const t = useT()
  const isEdit = !!user
  const [form, setForm] = useState({
    username: user?.username ?? '', full_name: user?.full_name ?? '',
    email: user?.email ?? '', role: user?.role ?? 'operator',
    password: '', is_active: user?.is_active ?? true,
  })
  const [selectedMods, setSelectedMods] = useState<Set<string>>(new Set(currentModuleIds ?? []))
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const set = (k: string, v: string | boolean) => setForm(f => ({ ...f, [k]: v }))
  const toggleMod = (id: string) =>
    setSelectedMods(p => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n })

  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setError(null); setSaving(true)
    try {
      let uid: number
      if (isEdit) {
        await apiFetch('PATCH', `/auth/users/${user!.id}`, {
          full_name: form.full_name || null, email: form.email || null,
          role: form.role, is_active: form.is_active,
        })
        uid = user!.id
      } else {
        if (!form.username.trim()) throw new Error(t('usr_user_req'))
        if (!form.password.trim()) throw new Error(t('usr_pw_req'))
        const created = await apiFetch('POST', '/auth/users', {
          username: form.username.trim(), full_name: form.full_name || null,
          email: form.email || null, role: form.role, password: form.password,
        })
        uid = created.id
      }
      if (form.role !== 'admin') {
        await apiFetch('PUT', `/modules/users/${uid}`, { module_ids: [...selectedMods] })
      }
      onSaved(); onClose()
    } catch (e: any) { setError(e.message) }
    finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-lg shadow-2xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700/60 flex-none">
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <UserPlus size={16} className="text-cyan-400" />
            {isEdit ? t('usr_edit') : t('usr_new')}
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-white"><X size={18} /></button>
        </div>
        <form onSubmit={submit} className="flex-1 overflow-y-auto">
          <div className="p-6 space-y-4">
            {!isEdit && (
              <div>
                <label className="text-xs font-medium text-slate-400 mb-1.5 block">{t('username_star')}</label>
                <input value={form.username} onChange={e => set('username', e.target.value)}
                  placeholder="jdoe" required autoFocus
                  className="w-full bg-slate-800 border border-slate-600 text-white text-sm rounded-xl px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 placeholder-slate-600" />
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-slate-400 mb-1.5 block">{t('usr_fullname')}</label>
                <input value={form.full_name} onChange={e => set('full_name', e.target.value)} placeholder="John Doe"
                  className="w-full bg-slate-800 border border-slate-600 text-white text-sm rounded-xl px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 placeholder-slate-600" />
              </div>
              <div>
                <label className="text-xs font-medium text-slate-400 mb-1.5 block">{t('usr_email')}</label>
                <input value={form.email} onChange={e => set('email', e.target.value)} type="email" placeholder="jdoe@example.com"
                  className="w-full bg-slate-800 border border-slate-600 text-white text-sm rounded-xl px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 placeholder-slate-600" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-slate-400 mb-1.5 block">{t('usr_role')}</label>
                <select value={form.role} onChange={e => set('role', e.target.value)}
                  className="w-full bg-slate-800 border border-slate-600 text-white text-sm rounded-xl px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-cyan-500/50">
                  <option value="operator">Operator</option>
                  <option value="viewer">Viewer</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
              {!isEdit ? (
                <div>
                  <label className="text-xs font-medium text-slate-400 mb-1.5 block">{t('password_star')}</label>
                  <input value={form.password} onChange={e => set('password', e.target.value)}
                    type="password" placeholder={t('usr_pw_short')} required
                    className="w-full bg-slate-800 border border-slate-600 text-white text-sm rounded-xl px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-cyan-500/50" />
                </div>
              ) : (
                <div className="flex items-end pb-0.5">
                  <div className="flex items-center justify-between w-full py-2.5">
                    <span className="text-sm text-slate-300">{t('active_label')}</span>
                    <button type="button" onClick={() => set('is_active', !form.is_active)}
                      className={`w-10 h-5 rounded-full relative transition-colors ${form.is_active ? 'bg-cyan-500' : 'bg-slate-700'}`}>
                      <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${form.is_active ? 'left-[22px]' : 'left-0.5'}`} />
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Modül erişimleri */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs font-medium text-slate-400 uppercase tracking-wider">{t('usr_mods')}</label>
                {form.role !== 'admin' && (
                  <span className="text-[11px] text-slate-600">{t('usr_sel_n', { n: selectedMods.size, total: modules.length })}</span>
                )}
              </div>
              {form.role === 'admin' ? (
                <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl px-4 py-3 text-xs text-slate-500 flex items-center gap-2">
                  <ShieldCheck size={13} className="text-red-400 shrink-0" />
                  {t('usr_admin_all')}
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-2">
                  {modules.map(m => {
                    const active = selectedMods.has(m.id)
                    return (
                      <button key={m.id} type="button" onClick={() => toggleMod(m.id)}
                        className={`flex items-center gap-2.5 px-3 py-2.5 rounded-xl border text-left transition-all ${
                          active
                            ? 'border-cyan-500/40 bg-cyan-500/10'
                            : 'bg-slate-800/40 border-slate-700/40 text-slate-500 hover:border-slate-600'
                        }`}>
                        <span className={active ? (MOD_COLOR_TEXT[m.color] ?? 'text-cyan-400') : 'text-slate-600'}>
                          {MODULE_ICONS[m.icon] ?? <Package size={14} />}
                        </span>
                        <span className={`text-xs font-medium flex-1 truncate ${active ? 'text-white' : 'text-slate-500'}`}>
                          {m.name}
                        </span>
                        <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${active ? (MOD_COLOR_DOT[m.color] ?? 'bg-cyan-400') : 'bg-slate-700'}`} />
                      </button>
                    )
                  })}
                </div>
              )}
            </div>

            {error && (
              <div className="flex items-center gap-2 bg-red-900/20 border border-red-700/40 rounded-xl px-4 py-3 text-sm text-red-300">
                <AlertTriangle size={14} className="shrink-0" /> {error}
              </div>
            )}
          </div>
          <div className="flex gap-3 px-6 pb-6">
            <button type="button" onClick={onClose}
              className="flex-1 py-2.5 rounded-xl border border-slate-600 text-slate-400 hover:bg-slate-800 text-sm transition-colors">
              {t('cancel')}
            </button>
            <button type="submit" disabled={saving}
              className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-medium text-sm disabled:opacity-60 transition-colors">
              {saving ? <RefreshCw size={14} className="animate-spin" /> : <Check size={14} />}
              {saving ? t('saving') : isEdit ? t('update_action') : t('create')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Şifre Sıfırla Modal ───────────────────────────────────────────────────────

function ResetPasswordModal({ user, onClose }: { user: UserItem; onClose: () => void }) {
  const t = useT()
  const [pw, setPw] = useState(''); const [pw2, setPw2] = useState('')
  const [saving, setSaving] = useState(false); const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (pw.length < 4) { setError(t('usr_pw_short')); return }
    if (pw !== pw2) { setError(t('pw_mismatch')); return }
    setSaving(true); setError(null)
    try { await apiFetch('POST', `/auth/users/${user.id}/password`, { new_password: pw }); setDone(true) }
    catch (e: any) { setError(e.message) }
    finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-sm shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700/60">
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <KeyRound size={16} className="text-amber-400" /> {t('usr_reset_title', { user: user.username })}
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-white"><X size={18} /></button>
        </div>
        {done ? (
          <div className="p-6 text-center space-y-3">
            <CheckCircle2 size={36} className="text-green-400 mx-auto" />
            <p className="text-white font-medium">{t('pw_updated')}</p>
            <button onClick={onClose} className="w-full py-2.5 rounded-xl bg-slate-700 hover:bg-slate-600 text-white text-sm">{t('close')}</button>
          </div>
        ) : (
          <form onSubmit={submit} className="p-6 space-y-4">
            <input value={pw} onChange={e => setPw(e.target.value)} type="password" placeholder={t('usr_new_pw')} required autoFocus
              className="w-full bg-slate-800 border border-slate-600 text-white text-sm rounded-xl px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-cyan-500/50" />
            <input value={pw2} onChange={e => setPw2(e.target.value)} type="password" placeholder={t('usr_repeat')} required
              className="w-full bg-slate-800 border border-slate-600 text-white text-sm rounded-xl px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-cyan-500/50" />
            {error && <p className="text-sm text-red-400 flex items-center gap-1.5"><AlertTriangle size={13} /> {error}</p>}
            <div className="flex gap-3">
              <button type="button" onClick={onClose} className="flex-1 py-2.5 rounded-xl border border-slate-600 text-slate-400 hover:bg-slate-800 text-sm">{t('cancel')}</button>
              <button type="submit" disabled={saving}
                className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl bg-amber-600 hover:bg-amber-500 text-white font-medium text-sm disabled:opacity-60">
                {saving ? <RefreshCw size={13} className="animate-spin" /> : <KeyRound size={13} />}
                {saving ? '…' : t('usr_reset')}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

// ── Silme Onayı ───────────────────────────────────────────────────────────────

function DeleteConfirm({ user, onClose, onDeleted }: {
  user: UserItem; onClose: () => void; onDeleted: () => void
}) {
  const t = useT()
  const [loading, setLoading] = useState(false); const [error, setError] = useState<string | null>(null)
  const confirm = async () => {
    setLoading(true); setError(null)
    try { await apiFetch('DELETE', `/auth/users/${user.id}`); onDeleted(); onClose() }
    catch (e: any) { setError(e.message) }
    finally { setLoading(false) }
  }
  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-red-700/50 rounded-2xl w-full max-w-sm shadow-2xl p-6 space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-red-500/20 flex items-center justify-center shrink-0">
            <Trash2 size={18} className="text-red-400" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-white">{t('usr_del_title', { user: user.username })}</h2>
            <p className="text-xs text-slate-500">{t('usr_irreversible')}</p>
          </div>
        </div>
        {error && <p className="text-sm text-red-400 flex items-center gap-1.5"><AlertTriangle size={13} /> {error}</p>}
        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 py-2.5 rounded-xl border border-slate-600 text-slate-400 hover:bg-slate-800 text-sm">{t('cancel')}</button>
          <button onClick={confirm} disabled={loading}
            className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl bg-red-600 hover:bg-red-500 text-white font-medium text-sm disabled:opacity-60">
            {loading ? <RefreshCw size={13} className="animate-spin" /> : <Trash2 size={13} />}
            {loading ? '…' : t('usr_yes_del')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Ana Sayfa ─────────────────────────────────────────────────────────────────

export default function UserManager() {
  const t = useT()
  const { user: me } = useAuth()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [modal, setModal] = useState<'add' | 'edit' | 'password' | 'delete' | null>(null)
  const [target, setTarget] = useState<UserItem | null>(null)

  // ── Sorgular ────────────────────────────────────────────────────────────────

  const { data: usersData, isLoading: usersLoading } = useQuery<{ users: UserItem[] }>({
    queryKey: ['users-list'],
    queryFn: () => apiFetch('GET', '/auth/users'),
    staleTime: 30_000,
  })

  const { data: modules = [] } = useQuery<ModuleInfo[]>({
    queryKey: ['modules-list'],
    queryFn: () => apiFetch('GET', '/modules/'),
    staleTime: 60_000,
  })

  const { data: userMods = [], isLoading: modsLoading } = useQuery<UserModuleSummary[]>({
    queryKey: ['modules-users'],
    queryFn: () => apiFetch('GET', '/modules/users'),
    staleTime: 30_000,
  })

  // ── Modül toggle — optimistic update ────────────────────────────────────────

  const toggleMutation = useMutation({
    mutationFn: ({ userId, moduleIds }: { userId: number; moduleIds: string[] }) =>
      apiFetch('PUT', `/modules/users/${userId}`, { module_ids: moduleIds }),

    onMutate: async ({ userId, moduleIds }) => {
      // Aktif sorguları iptal et — yarış koşulundan kaçın
      await qc.cancelQueries({ queryKey: ['modules-users'] })
      const prev = qc.getQueryData<UserModuleSummary[]>(['modules-users'])
      // Cache'i optimistik güncelle
      qc.setQueryData<UserModuleSummary[]>(['modules-users'], old =>
        old?.map(u => u.user_id === userId ? { ...u, modules: moduleIds } : u) ?? []
      )
      return { prev }
    },
    onError: (_e, _v, ctx) => {
      // Hata durumunda geri al
      if (ctx?.prev) qc.setQueryData(['modules-users'], ctx.prev)
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['modules-users'] })
    },
  })

  const handleToggle = (user: UserItem, moduleId: string) => {
    if (user.role === 'admin' || toggleMutation.isPending) return
    const current = userMods.find(u => u.user_id === user.id)?.modules ?? []
    const next = current.includes(moduleId)
      ? current.filter(id => id !== moduleId)
      : [...current, moduleId]
    toggleMutation.mutate({ userId: user.id, moduleIds: next })
  }

  // ── Yenile ──────────────────────────────────────────────────────────────────

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ['users-list'] })
    qc.invalidateQueries({ queryKey: ['modules-users'] })
  }

  const open = (m: typeof modal, u?: UserItem) => { setTarget(u ?? null); setModal(m) }

  // ── Filtrele ─────────────────────────────────────────────────────────────────

  const filteredUsers = (usersData?.users ?? []).filter(u => {
    if (!search) return true
    const q = search.toLowerCase()
    return u.username.toLowerCase().includes(q) ||
      (u.full_name ?? '').toLowerCase().includes(q) ||
      (u.email ?? '').toLowerCase().includes(q)
  })

  const modMap = new Map<number, string[]>()
  userMods.forEach(u => modMap.set(u.user_id, u.modules))

  const counts = { admin: 0, operator: 0, viewer: 0, inactive: 0 }
  ;(usersData?.users ?? []).forEach(u => {
    if (!u.is_active) counts.inactive++
    else counts[u.role as keyof typeof counts]++
  })

  const isLoading = usersLoading || modsLoading

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div className="p-6 space-y-5">

      {/* Başlık */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">{t('usr_title')}</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {t('usr_sub')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={async () => {
              try {
                const r = await apiFetch('POST', '/identity/sync-ad')
                alert(t('usr_ad_ok', { matched: r.matched, created: r.created, updated: r.updated }))
                invalidateAll()
              } catch (e: any) {
                alert(e.message || t('usr_ad_fail'))
              }
            }}
            className="flex items-center gap-2 px-3 py-2.5 rounded-xl border border-violet-500/40 text-violet-200 hover:bg-violet-500/10 font-medium text-sm transition-colors"
            title={t('usr_ad_title')}
          >
            <RefreshCw size={14} /> {t('usr_ad_sync')}
          </button>
          <button onClick={() => open('add')}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-medium text-sm transition-colors">
            <UserPlus size={15} /> {t('usr_new')}
          </button>
        </div>
      </div>

      {/* İstatistikler */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: 'Admin',    count: counts.admin,    color: 'text-red-400',   bg: 'bg-red-500/10 border-red-500/30' },
          { label: 'Operator', count: counts.operator, color: 'text-blue-400',  bg: 'bg-blue-500/10 border-blue-500/30' },
          { label: 'Viewer',   count: counts.viewer,   color: 'text-slate-300', bg: 'bg-slate-700/40 border-slate-600/40' },
          { label: t('inactive_label'),    count: counts.inactive, color: 'text-slate-500', bg: 'bg-slate-800/60 border-slate-700/40' },
        ].map(s => (
          <div key={s.label} className={`border rounded-xl px-4 py-3 ${s.bg}`}>
            <div className={`text-2xl font-bold ${s.color}`}>{s.count}</div>
            <div className="text-xs text-slate-500 mt-0.5">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Arama + Yenile */}
      <div className="flex items-center gap-3">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder={t('usr_search')}
            className="bg-slate-800 border border-slate-700 text-white text-sm rounded-xl pl-9 pr-4 py-2 w-52 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 placeholder-slate-600" />
        </div>
        <button onClick={invalidateAll} title={t('refresh_action')}
          className="ml-auto p-2 rounded-xl border border-slate-700 text-slate-500 hover:text-slate-300 hover:border-slate-600 transition-colors">
          <RefreshCw size={14} className={modsLoading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Matris Tablosu */}
      {isLoading ? (
        <div className="text-center py-16 text-slate-500">{t('loading')}</div>
      ) : (
        <div className="bg-slate-900/60 border border-slate-700/60 rounded-2xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr className="border-b border-slate-700/60 bg-slate-800/40">
                  <th className="text-left px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider min-w-[200px]">
                    {t('usr_col_user')}
                  </th>
                  {modules.map(m => (
                    <th key={m.id} className="px-3 py-3 text-center min-w-[72px]">
                      <div className="flex flex-col items-center gap-1.5">
                        <span className={MOD_COLOR_TEXT[m.color] ?? 'text-slate-400'}>
                          {MODULE_ICONS[m.icon] ?? <Package size={14} />}
                        </span>
                        <span className="text-[10px] text-slate-500 leading-tight max-w-[60px] text-center break-words">
                          {m.name.replace('Yönetimi', '').replace('Level 1', 'L1').trim()}
                        </span>
                      </div>
                    </th>
                  ))}
                  <th className="px-4 py-3 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider min-w-[100px]">
                    {t('actions')}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {filteredUsers.length === 0 ? (
                  <tr>
                    <td colSpan={modules.length + 2} className="text-center py-12 text-slate-600 text-sm">
                      {search ? t('usr_no_results') : t('usr_none')}
                    </td>
                  </tr>
                ) : filteredUsers.map(u => {
                  const mods = new Set(modMap.get(u.id) ?? [])
                  const isAdmin = u.role === 'admin'

                  return (
                    <tr key={u.id}
                      className={`transition-colors hover:bg-slate-800/30 ${!u.is_active ? 'opacity-50' : ''}`}>

                      {/* Kullanıcı bilgisi */}
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-3">
                          <Avatar user={u} />
                          <div className="min-w-0">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              <span className="text-sm font-medium text-white truncate">
                                {u.full_name || u.username}
                              </span>
                              {u.id === me?.id && (
                                <span className="text-[9px] text-cyan-400 border border-cyan-500/40 bg-cyan-500/10 px-1 py-0.5 rounded-full">{t('you_badge')}</span>
                              )}
                            </div>
                            <div className="flex items-center gap-1.5 mt-0.5">
                              <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${ROLE_BADGE[u.role]}`}>
                                {ROLE_ICON[u.role]} {ROLE_LABEL[u.role]}
                              </span>
                              {(u.auth_source || 'local') !== 'local' && (
                                <span className="text-[9px] text-violet-300 border border-violet-500/40 bg-violet-500/10 px-1 py-0.5 rounded-full uppercase">
                                  {u.auth_source}
                                </span>
                              )}
                              <span className="text-[10px] text-slate-600">@{u.username}</span>
                              {u.is_active
                                ? <span className="text-[10px] text-slate-600">{relTime(u.last_login, t)}</span>
                                : <UserX size={10} className="text-slate-600" />}
                            </div>
                          </div>
                        </div>
                      </td>

                      {/* Modül toggle'ları */}
                      {modules.map(m => {
                        const active = isAdmin || mods.has(m.id)
                        const isPending = toggleMutation.isPending &&
                          toggleMutation.variables?.userId === u.id

                        return (
                          <td key={m.id} className="px-3 py-3">
                            <div className="flex justify-center">
                              {isAdmin ? (
                                <span title={t('usr_admin_full')}>
                                  <CheckCircle2 size={15} className="text-slate-600" />
                                </span>
                              ) : (
                                <button
                                  onClick={() => handleToggle(u, m.id)}
                                  disabled={isPending}
                                  title={active ? t('usr_mod_off', { name: m.name }) : t('usr_mod_on', { name: m.name })}
                                  className={`w-9 h-5 rounded-full relative transition-colors duration-150 focus:outline-none disabled:opacity-60 ${
                                    active ? 'bg-cyan-500' : 'bg-slate-700 hover:bg-slate-600'
                                  }`}
                                >
                                  {isPending ? (
                                    <span className="absolute inset-0 flex items-center justify-center">
                                      <RefreshCw size={10} className="text-white animate-spin" />
                                    </span>
                                  ) : (
                                    <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform duration-150 ${active ? 'left-[18px]' : 'left-0.5'}`} />
                                  )}
                                </button>
                              )}
                            </div>
                          </td>
                        )
                      })}

                      {/* İşlemler */}
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-0.5 justify-end">
                          <button onClick={() => open('edit', u)} title={t('edit')}
                            className="p-1.5 rounded-lg text-slate-500 hover:text-white hover:bg-slate-700 transition-colors">
                            <Pencil size={13} />
                          </button>
                          {(u.auth_source || 'local') === 'local' && (
                            <button onClick={() => open('password', u)} title={t('usr_pw_reset')}
                              className="p-1.5 rounded-lg text-slate-500 hover:text-amber-400 hover:bg-slate-700 transition-colors">
                              <KeyRound size={13} />
                            </button>
                          )}
                          {u.id !== me?.id && (
                            <button onClick={() => open('delete', u)} title={t('delete')}
                              className="p-1.5 rounded-lg text-slate-500 hover:text-red-400 hover:bg-slate-700 transition-colors">
                              <Trash2 size={13} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Modül legend altında */}
          <div className="px-5 py-3 border-t border-slate-700/40 flex items-center gap-4 flex-wrap">
            {modules.map(m => (
              <div key={m.id} className="flex items-center gap-1.5 text-xs text-slate-600">
                <span className={MOD_COLOR_TEXT[m.color] ?? 'text-slate-400'}>
                  {MODULE_ICONS[m.icon] ?? <Package size={11} />}
                </span>
                {m.name}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Modaller */}
      {modal === 'add' && (
        <UserModal modules={modules} onClose={() => setModal(null)} onSaved={invalidateAll} />
      )}
      {modal === 'edit' && target && (
        <UserModal
          user={target}
          modules={modules}
          currentModuleIds={modMap.get(target.id) ?? []}
          onClose={() => setModal(null)}
          onSaved={invalidateAll}
        />
      )}
      {modal === 'password' && target && (
        <ResetPasswordModal user={target} onClose={() => setModal(null)} />
      )}
      {modal === 'delete' && target && (
        <DeleteConfirm user={target} onClose={() => setModal(null)} onDeleted={invalidateAll} />
      )}
    </div>
  )
}
