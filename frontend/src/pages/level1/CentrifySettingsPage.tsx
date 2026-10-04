/**
 * Centrify / Delinea — Entegrasyon Bağlantı Ayarları
 *
 * Yalnızca WinRM bağlantı yapılandırması. Zone yönetimi Level 1 → Centrify sayfasında.
 */
import React, { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  KeyRound, RefreshCw, Settings, Loader2, CheckCircle2, XCircle,
  ArrowRight,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { API_BASE_URL } from '../../config/api'
import { useT } from '../../i18n/LocaleProvider'

const api = (path: string) => `${API_BASE_URL}/centrify-mgmt${path}`

interface Config {
  id: number
  label: string
  winrm_host: string
  winrm_port: number
  winrm_https: boolean
  service_account: string
  sync_interval_minutes: number
  sync_enabled: boolean
  enabled: boolean
}

export default function CentrifySettingsPage() {
  const t = useT()
  const qc = useQueryClient()
  const [form, setForm] = useState({
    winrm_host: '', winrm_port: '5985', service_account: 'service_centrify',
    password: '', label: 'Varsayılan',
  })
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testResult, setTestResult] = useState<any>(null)
  const token = localStorage.getItem('auth_token') || localStorage.getItem('token')

  const { data: config, isLoading } = useQuery<Config | null>({
    queryKey: ['centrify-config'],
    queryFn: async () => {
      const res = await fetch(api('/config'), {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) return null
      return res.json()
    },
  })

  const testConnection = async () => {
    setTesting(true); setTestResult(null)
    try {
      const res = await fetch(api('/config/test-connection'), {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...form, winrm_port: parseInt(form.winrm_port),
          winrm_https: false, sync_interval_minutes: 30,
        }),
      })
      setTestResult(await res.json())
    } catch {
      setTestResult({ connected: false, error: 'Bağlantı hatası' })
    }
    setTesting(false)
  }

  const saveConfig = async () => {
    setSaving(true)
    try {
      await fetch(api('/config'), {
        method: 'PUT',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...form, winrm_port: parseInt(form.winrm_port),
          winrm_https: false, sync_interval_minutes: 30,
        }),
      })
      qc.invalidateQueries({ queryKey: ['centrify-config'] })
    } catch { /* ignore */ }
    setSaving(false)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-slate-500">
        <Loader2 size={20} className="animate-spin mr-2" /> {t('loading')}
      </div>
    )
  }

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-6">
      {/* Başlık */}
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-purple-500/20 flex items-center justify-center">
            <KeyRound size={20} className="text-purple-400" />
          </div>
          {t('cz_int_title')}
        </h1>
        <p className="text-sm text-slate-400 mt-1">{t('cz_int_sub')}</p>
      </div>

      {/* Mevcut bağlantı durumu */}
      {config && (
        <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <CheckCircle2 size={20} className="text-green-400" />
            <div>
              <div className="text-sm font-medium text-green-300">{t('cz_int_connected')}</div>
              <div className="text-xs text-green-400/70">
                {config.winrm_host}:{config.winrm_port} — {config.service_account}
              </div>
            </div>
          </div>
          <Link
            to="/level1/centrify"
            className="flex items-center gap-1 text-xs px-3 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg"
          >
            Zone Yönetimi <ArrowRight size={14} />
          </Link>
        </div>
      )}

      {/* Form */}
      <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-6 space-y-4">
        <div>
          <label className="block text-xs text-slate-400 mb-1">{t('cz_int_host')}</label>
          <input
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            placeholder="192.168.1.100"
            value={form.winrm_host}
            onChange={e => setForm({ ...form, winrm_host: e.target.value })}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-slate-400 mb-1">{t('cz_int_port')}</label>
            <input
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
              value={form.winrm_port}
              onChange={e => setForm({ ...form, winrm_port: e.target.value })}
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">{t('cz_int_user')}</label>
            <input
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
              value={form.service_account}
              onChange={e => setForm({ ...form, service_account: e.target.value })}
            />
          </div>
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">{t('cz_int_pass')}</label>
          <input
            type="password"
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            placeholder="••••••••"
            value={form.password}
            onChange={e => setForm({ ...form, password: e.target.value })}
          />
        </div>

        {/* Test sonucu */}
        {testResult && (
          <div className={`rounded-lg p-3 text-sm ${testResult.connected ? 'bg-green-500/10 border border-green-500/30' : 'bg-red-500/10 border border-red-500/30'}`}>
            <div className="flex items-center gap-2">
              {testResult.connected
                ? <CheckCircle2 size={16} className="text-green-400" />
                : <XCircle size={16} className="text-red-400" />}
              <span className={testResult.connected ? 'text-green-300' : 'text-red-300'}>
                {testResult.connected ? t('cz_int_connected') : t('cz_int_failed')}
              </span>
              {testResult.latency_ms > 0 && (
                <span className="text-xs text-slate-500 ml-auto">{testResult.latency_ms}ms</span>
              )}
            </div>
            {testResult.adedit_found && (
              <p className="text-xs text-slate-400 mt-1">ADEdit: {testResult.adedit_version}</p>
            )}
            {testResult.error && <p className="text-xs text-red-400 mt-1">{testResult.error}</p>}
          </div>
        )}

        {/* Butonlar */}
        <div className="flex gap-3 pt-2">
          <button
            onClick={testConnection}
            disabled={testing || !form.winrm_host || !form.password}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-sm text-slate-200 rounded-lg transition-colors"
          >
            {testing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            {testing ? t('cz_int_testing') : t('cz_int_test')}
          </button>
          <button
            onClick={saveConfig}
            disabled={saving || !form.winrm_host || !form.password}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-sm text-white rounded-lg transition-colors"
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Settings size={14} />}
            {saving ? t('cz_int_saving') : t('cz_int_save')}
          </button>
        </div>
      </div>
    </div>
  )
}
