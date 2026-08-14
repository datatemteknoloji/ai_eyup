/**
 * Admin-only küme yönetimi: Yeni küme / Token güncelle / Bağlantıyı sil.
 * Atlas OpenShiftPanel “Yönet” menüsünün ainew uyarlaması.
 */
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, KeyRound, Plus, Settings2, Trash2, X, Check, RefreshCw } from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import { inventoryHeaders } from '../../lib/inventoryApi'
import { useAuth } from '../../auth/AuthContext'
import type { OcpCluster } from './ocpTypes'
import { useT } from '../../i18n/LocaleProvider'

type Props = {
  cluster: OcpCluster | undefined
  onCreated?: (id: number) => void
  onDeleted?: () => void
}

type FormState = {
  name: string
  api_url: string
  token: string
  username: string
  password: string
  verify_ssl: boolean
}

const emptyForm = (): FormState => ({
  name: '', api_url: '', token: '', username: '', password: '', verify_ssl: false,
})

export default function OcpClusterManageMenu({ cluster, onCreated, onDeleted }: Props) {
  const t = useT()
  const { user } = useAuth()
  const isAdmin = Boolean(user?.is_admin || user?.role === 'admin')
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [modal, setModal] = useState<'create' | 'token' | null>(null)
  const [form, setForm] = useState<FormState>(emptyForm)
  const [authMethod, setAuthMethod] = useState<'token' | 'credentials'>('token')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const invalidate = () => {
    ;['openshift-clusters', 'openshift-health-board', 'openshift-overview'].forEach((k) =>
      qc.invalidateQueries({ queryKey: [k] }),
    )
  }

  const createMut = useMutation({
    mutationFn: async (payload: Record<string, unknown>) => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters`, {
        method: 'POST',
        headers: inventoryHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(payload),
      })
      const data = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(data.detail || t('ocp_cluster_added_fail'))
      return data
    },
    onSuccess: async (created) => {
      invalidate()
      if (created?.id) {
        await fetch(
          `${API_BASE_URL}/openshift/clusters/${created.id}/sync?background=true`,
          { method: 'POST', headers: inventoryHeaders() },
        )
        onCreated?.(created.id)
      }
      setModal(null)
      setForm(emptyForm())
    },
  })

  const updateMut = useMutation({
    mutationFn: async (payload: Record<string, unknown>) => {
      if (!cluster?.id) throw new Error(t('ocp_no_cluster_sel'))
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${cluster.id}`, {
        method: 'PUT',
        headers: inventoryHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(payload),
      })
      const data = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(data.detail || t('ocp_updated_fail'))
      return data
    },
    onSuccess: () => {
      invalidate()
      setModal(null)
      setForm(emptyForm())
      setMsg({ ok: true, text: t('ocp_update_ok') })
      setTimeout(() => setMsg(null), 2500)
    },
  })

  const deleteMut = useMutation({
    mutationFn: async () => {
      if (!cluster?.id) throw new Error(t('ocp_no_cluster_sel'))
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${cluster.id}`, {
        method: 'DELETE',
        headers: inventoryHeaders(),
      })
      if (!r.ok) {
        const data = await r.json().catch(() => ({}))
        throw new Error(data.detail || t('ocp_delete_failed'))
      }
    },
    onSuccess: () => {
      invalidate()
      onDeleted?.()
      setOpen(false)
    },
  })

  if (!isAdmin) {
    return (
      <a
        href="/integrations/openshift"
        className="text-xs px-2.5 py-1.5 rounded-lg border border-white/[0.08] text-slate-300 hover:bg-white/[0.04] inline-flex items-center gap-1.5"
      >
        <Settings2 size={12} /> {t('nav_integrations')}
      </a>
    )
  }

  const openCreate = () => {
    setForm(emptyForm())
    setAuthMethod('token')
    setMsg(null)
    setModal('create')
    setOpen(false)
  }

  const openToken = () => {
    if (!cluster) return
    setForm({
      name: cluster.name,
      api_url: cluster.api_url,
      token: '',
      username: '',
      password: '',
      verify_ssl: Boolean((cluster as any).verify_ssl),
    })
    setAuthMethod((cluster as any).auth_method === 'credentials' ? 'credentials' : 'token')
    setMsg(null)
    setModal('token')
    setOpen(false)
  }

  const submitCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setMsg(null)
    try {
      const payload: Record<string, unknown> = {
        name: form.name.trim(),
        api_url: form.api_url.trim(),
        verify_ssl: form.verify_ssl,
      }
      if (authMethod === 'token') payload.token = form.token.trim()
      else {
        payload.username = form.username.trim()
        payload.password = form.password
      }
      await createMut.mutateAsync(payload)
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : t('error_generic') })
    } finally {
      setBusy(false)
    }
  }

  const submitToken = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setMsg(null)
    try {
      const payload: Record<string, unknown> = {
        name: form.name.trim() || undefined,
        api_url: form.api_url.trim() || undefined,
        verify_ssl: form.verify_ssl,
      }
      if (authMethod === 'token') {
        if (form.token.trim()) payload.token = form.token.trim()
      } else if (form.username && form.password) {
        payload.username = form.username.trim()
        payload.password = form.password
      }
      await updateMut.mutateAsync(payload)
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : t('error_generic') })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="relative" ref={rootRef}>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="text-xs px-2.5 py-1.5 rounded-lg border border-white/[0.08] text-slate-300 hover:bg-white/[0.04] inline-flex items-center gap-1.5"
        >
          <Settings2 size={12} /> {t('ocp_manage')} <ChevronDown size={12} className={open ? 'rotate-180' : ''} />
        </button>
        {open && (
          <div className="absolute right-0 mt-1 w-52 rounded-lg border border-white/[0.08] bg-cyber-card shadow-xl z-40 py-1 text-xs">
            <button
              type="button"
              onClick={openCreate}
              className="w-full px-3 py-2 text-left text-slate-200 hover:bg-white/[0.06] inline-flex items-center gap-2"
            >
              <Plus size={12} className="text-rose-400" /> {t('ocp_new_cluster')}
            </button>
            <button
              type="button"
              disabled={!cluster}
              onClick={openToken}
              className="w-full px-3 py-2 text-left text-slate-200 hover:bg-white/[0.06] inline-flex items-center gap-2 disabled:opacity-40"
            >
              <KeyRound size={12} className="text-cyan-400" /> {t('ocp_update_token')}
            </button>
            <button
              type="button"
              disabled={!cluster || deleteMut.isPending}
              onClick={() => {
                if (!cluster) return
                if (!window.confirm(t('ocp_delete_cluster_confirm', { name: cluster.name }))) return
                deleteMut.mutate()
              }}
              className="w-full px-3 py-2 text-left text-red-300 hover:bg-red-500/10 inline-flex items-center gap-2 disabled:opacity-40"
            >
              <Trash2 size={12} /> {t('ocp_delete_link')}
            </button>
          </div>
        )}
      </div>

      {msg && !modal && (
        <span className={`text-[11px] ${msg.ok ? 'text-emerald-400' : 'text-red-400'}`}>{msg.text}</span>
      )}

      {modal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-cyber-card rounded-2xl border border-white/[0.06] w-full max-w-md shadow-2xl">
            <div className="px-5 py-3.5 border-b border-white/[0.06] flex items-center justify-between">
              <h2 className="text-sm font-semibold text-white">
                {modal === 'create' ? t('ocp_new_ocp') : t('ocp_update_conn')}
              </h2>
              <button type="button" onClick={() => setModal(null)} className="text-slate-400 hover:text-white">
                <X size={18} />
              </button>
            </div>
            <form onSubmit={modal === 'create' ? submitCreate : submitToken} className="p-5 space-y-3">
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">{t('name')}</label>
                <input
                  required={modal === 'create'}
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white"
                />
              </div>
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">{t('ocp_api_url')}</label>
                <input
                  required={modal === 'create'}
                  value={form.api_url}
                  onChange={(e) => setForm({ ...form, api_url: e.target.value })}
                  placeholder="https://api.cluster:6443"
                  className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white font-mono"
                />
              </div>
              <div className="grid grid-cols-2 gap-1 p-1 bg-cyber-deep border border-white/[0.06] rounded-lg">
                <button
                  type="button"
                  onClick={() => setAuthMethod('token')}
                  className={`py-1.5 rounded-md text-xs ${authMethod === 'token' ? 'bg-rose-600 text-white' : 'text-slate-400'}`}
                >
                  Bearer Token
                </button>
                <button
                  type="button"
                  onClick={() => setAuthMethod('credentials')}
                  className={`py-1.5 rounded-md text-xs ${authMethod === 'credentials' ? 'bg-rose-600 text-white' : 'text-slate-400'}`}
                >
                  {t('ocp_user_pass_short')}
                </button>
              </div>
              {authMethod === 'token' ? (
                <div>
                  <label className="block text-[11px] text-slate-400 mb-1">
                    Bearer Token {modal === 'token' && <span className="text-slate-600">{t('ocp_token_keep')}</span>}
                  </label>
                  <textarea
                    required={modal === 'create'}
                    rows={3}
                    value={form.token}
                    onChange={(e) => setForm({ ...form, token: e.target.value })}
                    className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white font-mono"
                  />
                </div>
              ) : (
                <>
                  <input
                    required={modal === 'create'}
                    placeholder={t('ocp_username')}
                    value={form.username}
                    onChange={(e) => setForm({ ...form, username: e.target.value })}
                    className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white"
                  />
                  <input
                    required={modal === 'create'}
                    type="password"
                    placeholder={t('ocp_password_ph')}
                    value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })}
                    className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white"
                  />
                </>
              )}
              <label className="flex items-center gap-2 text-[11px] text-slate-400">
                <input
                  type="checkbox"
                  checked={form.verify_ssl}
                  onChange={(e) => setForm({ ...form, verify_ssl: e.target.checked })}
                />
                {t('ocp_ssl_verify')}
              </label>
              {msg && (
                <div className={`text-xs flex items-center gap-1.5 ${msg.ok ? 'text-emerald-400' : 'text-red-400'}`}>
                  {msg.ok ? <Check size={12} /> : <X size={12} />} {msg.text}
                </div>
              )}
              <div className="flex gap-2 pt-1">
                <button type="button" onClick={() => setModal(null)} className="flex-1 py-2 rounded-lg bg-white/[0.07] text-sm text-white">
                  {t('cancel')}
                </button>
                <button
                  type="submit"
                  disabled={busy}
                  className="flex-1 py-2 rounded-lg bg-rose-600 text-sm text-white font-medium disabled:opacity-50 inline-flex items-center justify-center gap-1.5"
                >
                  {busy && <RefreshCw size={12} className="animate-spin" />}
                  {modal === 'create' ? t('add') : t('save')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  )
}
