import React, { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'

interface Server {
  id: number
  name: string
  hostname?: string
  ip_address: string
  status: string
  ai_ready: boolean
}

interface AWXTemplate {
  id: number
  name: string
  description: string
}

const Ansible: React.FC = () => {
  const [selectedServerIds, setSelectedServerIds] = useState<number[]>([])
  const [serverSearch, setServerSearch] = useState('')
  const [adhocMode, setAdhocMode] = useState<'command' | 'playbook'>('command')
  const [adhocModule, setAdhocModule] = useState('shell')
  const [adhocArgs, setAdhocArgs] = useState('')
  const [adhocBecome, setAdhocBecome] = useState(false)
  const [playbookYaml, setPlaybookYaml] = useState('')
  const [selectedTemplate, setSelectedTemplate] = useState<number | null>(null)
  const [extraVars, setExtraVars] = useState('')
  const [jobId, setJobId] = useState<number | null>(null)
  const [adhocResult, setAdhocResult] = useState<any>(null)

  // Sunucu listesi (ai_ready && ONLINE && IP adresi olanlar - SSH yapılabilenler)
  const { data: allServers = [] } = useQuery<Server[]>({
    queryKey: ['servers'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/servers/`)
      if (!res.ok) throw new Error('Sunucular alınamadı')
      return res.json()
    }
  })

  // Sadece SSH yapılabilen sunucuları filtrele: ai_ready + ONLINE + IP adresi var
  // WARNING = TCP erişilebilir ama SSH auth başarısız, bu yüzden dahil edilmez
  const allSshServers = allServers.filter(s => 
    s.ai_ready && 
    s.status === 'ONLINE' && 
    s.ip_address && 
    s.ip_address.trim() !== ''
  )

  // Search filtresi uygula
  const servers = allSshServers.filter(s => {
    if (!serverSearch) return true
    const search = serverSearch.toLowerCase()
    return (
      s.name.toLowerCase().includes(search) ||
      s.ip_address?.toLowerCase().includes(search) ||
      s.hostname?.toLowerCase().includes(search)
    )
  })

  // AWX job template listesi
  const { data: templates = [] } = useQuery<AWXTemplate[]>({
    queryKey: ['awx-templates'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/ansible/awx/templates`)
      if (!res.ok) return []
      const data = await res.json()
      return data.templates || []
    },
    retry: false
  })

  // Ad-hoc komut veya playbook çalıştırma
  const runAdHoc = useMutation({
    mutationFn: async () => {
      if (adhocMode === 'playbook') {
        // Playbook modu
        const res = await fetch(`${API_BASE_URL}/ansible/playbook`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            server_ids: selectedServerIds,
            playbook_content: playbookYaml
          })
        })
        if (!res.ok) throw new Error('Playbook çalıştırılamadı')
        return res.json()
      } else {
        // Komut modu
        const res = await fetch(`${API_BASE_URL}/ansible/adhoc`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            server_ids: selectedServerIds,
            module: adhocModule,
            args: adhocArgs,
            become: adhocBecome
          })
        })
        if (!res.ok) throw new Error('Ad-hoc komut başarısız')
        return res.json()
      }
    },
    onSuccess: (data) => {
      setAdhocResult(data)
    },
    onError: (err: Error) => {
      alert(`Hata: ${err.message}`)
    }
  })

  // AWX job başlatma
  const launchAWXJob = useMutation({
    mutationFn: async () => {
      const extra = extraVars ? JSON.parse(extraVars) : undefined
      const res = await fetch(`${API_BASE_URL}/ansible/awx/launch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          template_id: selectedTemplate,
          server_ids: selectedServerIds.length > 0 ? selectedServerIds : undefined,
          extra_vars: extra
        })
      })
      if (!res.ok) throw new Error('AWX job başlatılamadı')
      return res.json()
    },
    onSuccess: (data) => {
      setJobId(data.job_id)
      alert(`✅ AWX Job #${data.job_id} başlatıldı`)
    }
  })

  // Job durumu sorgulama
  const { data: jobStatus } = useQuery({
    queryKey: ['awx-job', jobId],
    queryFn: async () => {
      if (!jobId) return null
      const res = await fetch(`${API_BASE_URL}/ansible/awx/job/${jobId}`)
      const data = await res.json()
      return data.job
    },
    enabled: !!jobId,
    refetchInterval: (query) => {
      // pending/running ise 3sn'de bir yenile
      if (query.state.data?.status === 'pending' || query.state.data?.status === 'running') return 3000
      return false
    }
  })

  const toggleServer = (id: number) => {
    setSelectedServerIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    )
  }

  const selectAll = () => {
    setSelectedServerIds(servers.map(s => s.id))
  }

  const clearSelection = () => {
    setSelectedServerIds([])
  }

  return (
    <div className="space-y-6">
      {/* Başlık */}
      <div>
        <h1 className="text-2xl font-bold text-white">Ansible & AWX</h1>
        <p className="text-slate-400">Toplu komut çalıştırma ve playbook yönetimi</p>
      </div>

      {/* Sunucu Seçimi */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white">
            SSH Yapılabilen Sunucular ({selectedServerIds.length}/{allSshServers.length})
          </h2>
          <div className="flex gap-2">
            <button onClick={selectAll} className="px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-sm">
              Tümünü Seç
            </button>
            <button onClick={clearSelection} className="px-3 py-1 bg-slate-700 hover:bg-slate-600 text-white rounded text-sm">
              Temizle
            </button>
          </div>
        </div>
        
        {/* Search Bar */}
        {allSshServers.length > 0 && (
          <div className="mb-4">
            <input
              type="text"
              value={serverSearch}
              onChange={(e) => setServerSearch(e.target.value)}
              placeholder="🔍 Sunucu ara (isim, IP, hostname)..."
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            {serverSearch && (
              <p className="text-xs text-slate-400 mt-1">
                {servers.length} / {allSshServers.length} sunucu gösteriliyor
              </p>
            )}
          </div>
        )}
        
        {servers.length === 0 ? (
          serverSearch ? (
            <p className="text-slate-400 text-sm text-center py-4">
              "{serverSearch}" araması için sonuç bulunamadı.
            </p>
          ) : (
            <p className="text-slate-400 text-sm text-center py-4">
              Hiç uygun sunucu yok. Sunucular için: ai_ready=true, status=ONLINE ve IP adresi gerekli.
              <br />
              Ayarlar → Global Credential ile SSH bilgisi ekleyin ve Hypervisor sync ile IP adreslerini güncelleyin.
            </p>
          )
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2 max-h-60 overflow-y-auto">
            {servers.map(s => (
            <label key={s.id} className="flex items-center gap-2 p-2 rounded hover:bg-slate-700 cursor-pointer">
              <input
                type="checkbox"
                checked={selectedServerIds.includes(s.id)}
                onChange={() => toggleServer(s.id)}
                className="w-4 h-4"
              />
              <span className="text-white text-sm">{s.name}</span>
              <span className={`text-xs ${s.status === 'ONLINE' ? 'text-green-400' : 'text-slate-500'}`}>
                ({s.status})
              </span>
            </label>
            ))}
          </div>
        )}
      </div>

      {/* Ad-Hoc Komut */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white">Ad-Hoc Ansible</h2>
          <div className="flex gap-2 bg-slate-900 rounded-lg p-1">
            <button
              onClick={() => setAdhocMode('command')}
              className={`px-4 py-1.5 rounded text-sm font-medium transition-all ${
                adhocMode === 'command' 
                  ? 'bg-blue-600 text-white' 
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              📝 Komut
            </button>
            <button
              onClick={() => setAdhocMode('playbook')}
              className={`px-4 py-1.5 rounded text-sm font-medium transition-all ${
                adhocMode === 'playbook' 
                  ? 'bg-blue-600 text-white' 
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              📄 YAML Playbook
            </button>
          </div>
        </div>

        {adhocMode === 'command' ? (
          // Komut Modu
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm text-slate-400 mb-1">Modül</label>
                <select
                  value={adhocModule}
                  onChange={(e) => setAdhocModule(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-white"
                >
                  <option value="shell">shell</option>
                  <option value="command">command</option>
                  <option value="yum">yum</option>
                  <option value="apt">apt</option>
                  <option value="service">service</option>
                  <option value="copy">copy</option>
                </select>
              </div>
              <div className="md:col-span-2">
                <label className="block text-sm text-slate-400 mb-1">Argümanlar</label>
                <input
                  type="text"
                  value={adhocArgs}
                  onChange={(e) => setAdhocArgs(e.target.value)}
                  placeholder='örn: "uptime" veya "name=vim state=present"'
                  className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-white"
                />
              </div>
            </div>
            <label className="flex items-center gap-2 text-white">
              <input
                type="checkbox"
                checked={adhocBecome}
                onChange={(e) => setAdhocBecome(e.target.checked)}
                className="w-4 h-4"
              />
              <span className="text-sm">Sudo ile çalıştır (become)</span>
            </label>
            <button
              onClick={() => runAdHoc.mutate()}
              disabled={selectedServerIds.length === 0 || !adhocArgs || runAdHoc.isPending}
              className="px-4 py-2 bg-green-600 hover:bg-green-500 text-white rounded disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {runAdHoc.isPending ? '⏳ Çalıştırılıyor...' : '▶️ Komutu Çalıştır'}
            </button>
          </div>
        ) : (
          // Playbook Modu
          <div className="space-y-4">
            <div>
              <label className="block text-sm text-slate-400 mb-1">
                Ansible Playbook (YAML)
              </label>
              <textarea
                value={playbookYaml}
                onChange={(e) => setPlaybookYaml(e.target.value)}
                placeholder={`---
- name: Örnek Playbook
  hosts: all
  become: yes
  tasks:
    - name: Paket yükle
      yum:
        name: vim
        state: present
    
    - name: Servis başlat
      service:
        name: sshd
        state: started
        enabled: yes`}
                className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-white font-mono text-sm h-64"
              />
              <p className="text-xs text-slate-500 mt-1">
                💡 YAML formatında Ansible playbook yazın. "hosts: all" seçili sunuculara uygulanır.
              </p>
            </div>
            <button
              onClick={() => runAdHoc.mutate()}
              disabled={selectedServerIds.length === 0 || !playbookYaml.trim() || runAdHoc.isPending}
              className="px-4 py-2 bg-green-600 hover:bg-green-500 text-white rounded disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {runAdHoc.isPending ? '⏳ Playbook Çalıştırılıyor...' : '▶️ Playbook\'u Çalıştır'}
            </button>
          </div>
        )}

        {/* Ad-hoc Output */}
        {adhocResult && (
          <div className="mt-4 space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="text-md font-semibold text-white">Komut Çıktıları</h3>
              <button
                onClick={() => setAdhocResult(null)}
                className="text-slate-400 hover:text-white text-sm"
              >
                ✕ Kapat
              </button>
            </div>
            
            {/* Özet */}
            <div className="bg-slate-900 rounded p-3 text-sm">
              <div className="flex gap-4">
                <span className="text-green-400">
                  ✅ Başarılı: {adhocResult.results ? Object.keys(adhocResult.results).filter(k => adhocResult.results[k].rc === 0).length : 0}
                </span>
                {adhocResult.failed && adhocResult.failed.length > 0 && (
                  <span className="text-red-400">
                    ❌ Hata: {adhocResult.failed.length}
                  </span>
                )}
              </div>
            </div>

            {/* Sunucu başına çıktılar */}
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {adhocResult.results && Object.entries(adhocResult.results).map(([server, result]: [string, any]) => (
                <div key={server} className="bg-slate-900 rounded p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`text-sm font-semibold ${result.rc === 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {result.rc === 0 ? '✅' : '❌'} {server}
                    </span>
                  </div>
                  <pre className="text-xs text-slate-300 whitespace-pre-wrap font-mono bg-black/30 p-2 rounded">
                    {result.stdout || result.stderr || 'Çıktı yok'}
                  </pre>
                </div>
              ))}
            </div>

            {/* Raw stdout/stderr (debug için) */}
            {adhocResult.stdout && (
              <details className="bg-slate-900 rounded p-3">
                <summary className="text-sm text-slate-400 cursor-pointer">📋 Ham Çıktı (Raw Output)</summary>
                <pre className="text-xs text-slate-300 whitespace-pre-wrap font-mono mt-2 bg-black/30 p-2 rounded">
                  {adhocResult.stdout}
                </pre>
              </details>
            )}
          </div>
        )}
      </div>

      {/* AWX Job Template */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">AWX Playbook (Job Template)</h2>
        {templates.length === 0 ? (
          <p className="text-slate-400 text-sm">AWX yapılandırılmamış veya job template yok. (AWX_URL, AWX_USERNAME, AWX_PASSWORD env)</p>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="block text-sm text-slate-400 mb-1">Job Template Seç</label>
              <select
                value={selectedTemplate || ''}
                onChange={(e) => setSelectedTemplate(Number(e.target.value))}
                className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-white"
              >
                <option value="">-- Seçin --</option>
                {templates.map(t => (
                  <option key={t.id} value={t.id}>
                    {t.name} {t.description && `- ${t.description}`}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm text-slate-400 mb-1">Extra Vars (JSON, opsiyonel)</label>
              <textarea
                value={extraVars}
                onChange={(e) => setExtraVars(e.target.value)}
                placeholder='{"key": "value"}'
                className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-white font-mono text-sm"
                rows={3}
              />
            </div>
            <button
              onClick={() => launchAWXJob.mutate()}
              disabled={!selectedTemplate || launchAWXJob.isPending}
              className="px-4 py-2 bg-purple-600 hover:bg-purple-500 text-white rounded disabled:opacity-50"
            >
              {launchAWXJob.isPending ? '⏳ Başlatılıyor...' : '🚀 Job Başlat'}
            </button>
          </div>
        )}
      </div>

      {/* Job Status */}
      {jobId && jobStatus && (
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Job #{jobId} Durumu</h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-400">Status:</span>
              <span className={`font-semibold ${
                jobStatus.status === 'successful' ? 'text-green-400' :
                jobStatus.status === 'failed' ? 'text-red-400' :
                jobStatus.status === 'running' ? 'text-blue-400' : 'text-yellow-400'
              }`}>
                {jobStatus.status?.toUpperCase()}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Name:</span>
              <span className="text-white">{jobStatus.name}</span>
            </div>
            {jobStatus.elapsed && (
              <div className="flex justify-between">
                <span className="text-slate-400">Elapsed:</span>
                <span className="text-white">{jobStatus.elapsed}s</span>
              </div>
            )}
          </div>
          <div className="mt-4 flex gap-2">
            <button
              onClick={() => window.open(`${API_BASE_URL}/ansible/awx/job/${jobId}/stdout`, '_blank')}
              className="px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-sm"
            >
              📄 Çıktıyı Gör
            </button>
            <button
              onClick={() => setJobId(null)}
              className="px-3 py-1 bg-slate-700 hover:bg-slate-600 text-white rounded text-sm"
            >
              Kapat
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default Ansible
