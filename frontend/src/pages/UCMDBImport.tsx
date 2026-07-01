import React, { useCallback, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  Upload, FileText, CheckCircle, AlertTriangle,
  ChevronRight, RefreshCw, Table2, Download,
} from 'lucide-react'
import { API_BASE_URL } from '../config/api'

const UCMDB_API = `${API_BASE_URL}/ucmdb`

// ── Types ─────────────────────────────────────────────────────────────────────

interface FieldOption { value: string; label: string }

interface PreviewResult {
  upload_id: string
  filename: string
  total_rows: number
  columns: string[]
  suggested_mapping: Record<string, string | null>
  sample_rows: Record<string, string>[]
}

interface ImportResult {
  dry_run: boolean
  total_rows: number
  created: number
  updated: number
  skipped: number
  errors: string[]
  preview: any[]
  filename?: string
}

type Step = 'upload' | 'mapping' | 'confirm' | 'done'

// ── Step indicator ────────────────────────────────────────────────────────────

const Steps: React.FC<{ current: Step }> = ({ current }) => {
  const steps: { id: Step; label: string }[] = [
    { id: 'upload',  label: '1. Dosya Yükle' },
    { id: 'mapping', label: '2. Alan Eşleştir' },
    { id: 'confirm', label: '3. Önizle & İmport' },
    { id: 'done',    label: '4. Tamamlandı' },
  ]
  const idx = (s: Step) => steps.findIndex(x => x.id === s)
  const cur = idx(current)

  return (
    <div className="flex items-center gap-0 mb-8">
      {steps.map((s, i) => (
        <React.Fragment key={s.id}>
          <div className="flex items-center gap-2">
            <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-colors ${
              i < cur ? 'bg-green-500 text-white' :
              i === cur ? 'bg-blue-600 text-white ring-2 ring-blue-400/40' :
              'bg-slate-700 text-slate-500'
            }`}>
              {i < cur ? <CheckCircle size={14} /> : i + 1}
            </div>
            <span className={`text-sm font-medium ${i === cur ? 'text-white' : i < cur ? 'text-green-400' : 'text-slate-500'}`}>
              {s.label}
            </span>
          </div>
          {i < steps.length - 1 && (
            <div className={`flex-1 h-px mx-3 ${i < cur ? 'bg-green-500/40' : 'bg-slate-700'}`} />
          )}
        </React.Fragment>
      ))}
    </div>
  )
}

// ── Drop zone ─────────────────────────────────────────────────────────────────

const DropZone: React.FC<{ onFile: (f: File) => void; loading: boolean }> = ({ onFile, loading }) => {
  const [drag, setDrag] = useState(false)

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDrag(false)
    const f = e.dataTransfer.files[0]
    if (f) onFile(f)
  }, [onFile])

  return (
    <label
      onDragOver={e => { e.preventDefault(); setDrag(true) }}
      onDragLeave={() => setDrag(false)}
      onDrop={handleDrop}
      className={`flex flex-col items-center justify-center gap-4 border-2 border-dashed rounded-2xl p-12 cursor-pointer transition-all ${
        drag ? 'border-blue-500 bg-blue-500/8' : 'border-slate-600 bg-slate-800/50 hover:border-slate-500 hover:bg-slate-800'
      }`}
    >
      <input type="file" className="hidden" accept=".csv,.xlsx,.xls"
        onChange={e => { const f = e.target.files?.[0]; if (f) onFile(f) }} />
      {loading ? (
        <div className="w-10 h-10 border-2 border-slate-600 border-t-blue-500 rounded-full animate-spin" />
      ) : (
        <Upload size={40} className="text-slate-500" />
      )}
      <div className="text-center">
        <p className="text-white font-medium">
          {loading ? 'Dosya okunuyor...' : 'CSV veya Excel dosyasını buraya sürükleyin'}
        </p>
        <p className="text-slate-500 text-sm mt-1">veya tıklayarak seçin · .csv · .xlsx · .xls · Maks. 20 MB</p>
      </div>
      <div className="flex gap-3 text-xs text-slate-500">
        <span className="flex items-center gap-1"><FileText size={12} /> UCMDB CI Export</span>
        <span className="flex items-center gap-1"><Table2 size={12} /> Rapor CSV</span>
      </div>
    </label>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

const UCMDBImport: React.FC = () => {
  const [step, setStep] = useState<Step>('upload')
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [uploadId, setUploadId] = useState<string | null>(null)
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [updateExisting, setUpdateExisting] = useState(true)
  const [importResult, setImportResult] = useState<ImportResult | null>(null)

  // Field options from backend
  const { data: fieldOpts } = useQuery<{ fields: FieldOption[] }>({
    queryKey: ['ucmdb-field-options'],
    queryFn: async () => {
      const r = await fetch(`${UCMDB_API}/field-options`)
      return r.json()
    },
    staleTime: Infinity,
  })
  const fields: FieldOption[] = fieldOpts?.fields || []

  // Upload mutation
  const uploadMut = useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      const r = await fetch(`${UCMDB_API}/preview`, { method: 'POST', body: fd })
      if (!r.ok) { const e = await r.json(); throw new Error(e.detail || 'Yükleme hatası') }
      return r.json() as Promise<PreviewResult>
    },
    onSuccess: (data) => {
      setPreview(data)
      setUploadId(data.upload_id || null)
      // Initialize mapping with suggestions (null → __skip__)
      const m: Record<string, string> = {}
      for (const [col, sug] of Object.entries(data.suggested_mapping)) {
        m[col] = sug || '__skip__'
      }
      setMapping(m)
      setStep('mapping')
    },
  })

  // Dry-run mutation
  const dryRunMut = useMutation({
    mutationFn: async () => {
      const r = await fetch(`${UCMDB_API}/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ upload_id: uploadId, mapping, update_existing: updateExisting, dry_run: true }),
      })
      return r.json() as Promise<ImportResult>
    },
    onSuccess: (data) => { setImportResult(data); setStep('confirm') },
  })

  // Real import mutation
  const importMut = useMutation({
    mutationFn: async () => {
      const r = await fetch(`${UCMDB_API}/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ upload_id: uploadId, mapping, update_existing: updateExisting, dry_run: false }),
      })
      return r.json() as Promise<ImportResult>
    },
    onSuccess: (data) => { setImportResult(data); setStep('done') },
  })

  const reset = () => {
    setStep('upload'); setPreview(null); setMapping({}); setUploadId(null)
    setImportResult(null); uploadMut.reset(); dryRunMut.reset(); importMut.reset()
  }

  const mappedCount = Object.values(mapping).filter(v => v && v !== '__skip__').length

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-white">UCMDB Import</h1>
        <p className="text-slate-400 text-sm mt-0.5">
          OpenText UCMDB'den alınan CSV/Excel export dosyasını sunucu envanterine aktar — fiziksel sunucular, VM'ler, Unix/Windows/AIX
        </p>
      </div>

      <Steps current={step} />

      {/* ── Step 1: Upload ── */}
      {step === 'upload' && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 space-y-6">
          <DropZone onFile={f => uploadMut.mutate(f)} loading={uploadMut.isPending} />

          {uploadMut.isError && (
            <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-xl text-sm text-red-300">
              <AlertTriangle size={14} className="inline mr-2" />
              {(uploadMut.error as Error)?.message}
            </div>
          )}

          {/* How-to hint */}
          <div className="bg-slate-700/40 rounded-xl p-4 text-sm text-slate-400 space-y-2">
            <p className="font-medium text-slate-300">UCMDB'den nasıl export alınır?</p>
            <ol className="list-decimal list-inside space-y-1 text-xs">
              <li>UCMDB Web UI → <strong className="text-slate-300">Managers → Modeling → IT Universe Manager</strong></li>
              <li>Sol panelden CI Type seçin (örn: <em>Host</em>, <em>Unix</em>, <em>Windows</em>)</li>
              <li>Üst menü → <strong className="text-slate-300">Actions → Export to Excel/CSV</strong></li>
              <li>Ya da <strong className="text-slate-300">Reports → Create Report</strong> → CSV/Excel export</li>
            </ol>
            <p className="text-xs text-slate-500 mt-2">
              Önerilen kolonlar: Name, Primary IP Address, OS Name, OS Version, CPU Count, Memory Size, Environment
            </p>
          </div>
        </div>
      )}

      {/* ── Step 2: Mapping ── */}
      {step === 'mapping' && preview && (
        <div className="space-y-4">
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-white font-semibold">Alan Eşleştirme</h3>
                <p className="text-slate-400 text-xs mt-0.5">
                  {preview.filename} · {preview.total_rows.toLocaleString()} satır · {preview.columns.length} kolon
                </p>
              </div>
              <span className="text-xs text-blue-400 bg-blue-500/10 border border-blue-500/20 rounded-full px-3 py-1">
                {mappedCount} / {preview.columns.length} eşleşti
              </span>
            </div>

            <div className="space-y-2 max-h-[420px] overflow-y-auto pr-1">
              {preview.columns.map(col => {
                const sample = preview.sample_rows
                  .map(r => r[col])
                  .filter(Boolean)
                  .slice(0, 3)
                  .join(' · ')
                const isMapped = mapping[col] && mapping[col] !== '__skip__'

                return (
                  <div key={col} className={`flex items-center gap-3 rounded-lg p-3 transition-colors ${isMapped ? 'bg-blue-500/5 border border-blue-500/15' : 'bg-slate-700/30 border border-transparent'}`}>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-white truncate">{col}</div>
                      {sample && <div className="text-xs text-slate-500 truncate mt-0.5">{sample}</div>}
                    </div>
                    <ChevronRight size={14} className="text-slate-600 flex-shrink-0" />
                    <select
                      value={mapping[col] || '__skip__'}
                      onChange={e => setMapping(m => ({ ...m, [col]: e.target.value }))}
                      className={`w-52 bg-slate-700 border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${isMapped ? 'border-blue-500/40 text-white' : 'border-slate-600 text-slate-400'}`}
                    >
                      {fields.map(f => (
                        <option key={f.value} value={f.value}>{f.label}</option>
                      ))}
                    </select>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Sample data preview */}
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
            <h4 className="text-sm font-semibold text-slate-300 mb-3">Örnek Veriler (ilk 5 satır)</h4>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-700">
                    {preview.columns.slice(0, 8).map(c => (
                      <th key={c} className="px-2 py-1.5 text-left text-slate-400 font-medium truncate max-w-[120px]">{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.sample_rows.slice(0, 5).map((row, i) => (
                    <tr key={i} className="border-b border-slate-700/50 hover:bg-slate-700/20">
                      {preview.columns.slice(0, 8).map(c => (
                        <td key={c} className="px-2 py-1.5 text-slate-300 truncate max-w-[120px]" title={row[c]}>{row[c] || '—'}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="flex items-center justify-between">
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={updateExisting} onChange={e => setUpdateExisting(e.target.checked)}
                className="w-4 h-4 rounded text-blue-600" />
              <span className="text-sm text-slate-300">Mevcut sunucuları güncelle (IP/hostname eşleşirse)</span>
            </label>
            <div className="flex gap-3">
              <button onClick={reset} className="px-4 py-2 text-sm text-slate-400 hover:text-white bg-slate-700 hover:bg-slate-600 rounded-lg transition-colors">
                Başa Dön
              </button>
              <button
                onClick={() => dryRunMut.mutate()}
                disabled={dryRunMut.isPending || mappedCount === 0}
                className="flex items-center gap-2 px-5 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
              >
                {dryRunMut.isPending ? <><RefreshCw size={14} className="animate-spin" /> Önizleniyor...</> : <>Önizle <ChevronRight size={14} /></>}
              </button>
            </div>
          </div>

          {dryRunMut.isError && (
            <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-sm text-red-300">
              {(dryRunMut.error as Error)?.message}
            </div>
          )}
        </div>
      )}

      {/* ── Step 3: Confirm ── */}
      {step === 'confirm' && importResult && (
        <div className="space-y-4">
          {/* Summary cards */}
          <div className="grid grid-cols-4 gap-3">
            {[
              { label: 'Toplam Satır', value: importResult.total_rows, color: 'text-white' },
              { label: 'Yeni Eklenecek', value: importResult.created, color: 'text-green-400' },
              { label: 'Güncellenecek', value: importResult.updated, color: 'text-blue-400' },
              { label: 'Atlanacak', value: importResult.skipped, color: 'text-slate-400' },
            ].map(c => (
              <div key={c.label} className="bg-slate-800 border border-slate-700 rounded-xl p-4 text-center">
                <div className={`text-2xl font-bold ${c.color}`}>{c.value}</div>
                <div className="text-slate-400 text-xs mt-0.5">{c.label}</div>
              </div>
            ))}
          </div>

          {/* Errors */}
          {importResult.errors.length > 0 && (
            <div className="bg-amber-500/8 border border-amber-500/25 rounded-xl p-4">
              <p className="text-amber-300 font-medium text-sm mb-2">
                <AlertTriangle size={13} className="inline mr-1" />
                {importResult.errors.length} satırda hata var (import yine de devam eder):
              </p>
              <div className="space-y-0.5 max-h-32 overflow-y-auto">
                {importResult.errors.map((e, i) => (
                  <p key={i} className="text-xs text-amber-400/80 font-mono">{e}</p>
                ))}
              </div>
            </div>
          )}

          {/* Preview table */}
          {importResult.preview.length > 0 && (
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
              <h4 className="text-sm font-semibold text-slate-300 mb-3">Import Edilecek Örnekler</h4>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-slate-700">
                      {['Ad', 'IP', 'Hostname', 'Tür', 'OS', 'Tier', 'CPU', 'RAM'].map(h => (
                        <th key={h} className="px-2 py-1.5 text-left text-slate-400 font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {importResult.preview.map((row, i) => (
                      <tr key={i} className="border-b border-slate-700/50">
                        <td className="px-2 py-1.5 text-white font-medium">{row.name || '—'}</td>
                        <td className="px-2 py-1.5 text-slate-300 font-mono">{row.ip_address || '—'}</td>
                        <td className="px-2 py-1.5 text-slate-400">{row.hostname || '—'}</td>
                        <td className="px-2 py-1.5">
                          <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                            row.category === 'Fiziksel' ? 'bg-orange-500/15 text-orange-400' :
                            row.category === 'Sanal'    ? 'bg-blue-500/15 text-blue-400' :
                            'bg-slate-600 text-slate-400'
                          }`}>{row.category || '—'}</span>
                        </td>
                        <td className="px-2 py-1.5 text-slate-300">{row.os_type || '—'}</td>
                        <td className="px-2 py-1.5">
                          <span className={`text-xs px-1.5 py-0.5 rounded ${
                            row.tier === 'critical' ? 'bg-red-500/20 text-red-400' :
                            row.tier === 'high' ? 'bg-orange-500/20 text-orange-400' :
                            row.tier === 'medium' ? 'bg-yellow-500/20 text-yellow-400' :
                            'bg-slate-600 text-slate-400'
                          }`}>{row.tier || '—'}</span>
                        </td>
                        <td className="px-2 py-1.5 text-slate-400">{row.cpu_cores || '—'}</td>
                        <td className="px-2 py-1.5 text-slate-400">{row.memory_gb ? `${row.memory_gb} GB` : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="flex justify-between">
            <button onClick={() => setStep('mapping')} className="px-4 py-2 text-sm text-slate-400 hover:text-white bg-slate-700 hover:bg-slate-600 rounded-lg transition-colors">
              ← Geri
            </button>
            <button
              onClick={() => importMut.mutate()}
              disabled={importMut.isPending || importResult.created + importResult.updated === 0}
              className="flex items-center gap-2 px-6 py-2.5 bg-gradient-to-r from-green-600 to-green-700 hover:from-green-500 hover:to-green-600 disabled:opacity-50 text-white font-medium text-sm rounded-lg transition-all"
            >
              {importMut.isPending
                ? <><RefreshCw size={14} className="animate-spin" /> Import ediliyor...</>
                : <><Download size={14} /> {importResult.created + importResult.updated} Sunucuyu Import Et</>}
            </button>
          </div>
        </div>
      )}

      {/* ── Step 4: Done ── */}
      {step === 'done' && importResult && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-8 text-center space-y-5">
          <div className="w-16 h-16 bg-green-500/15 rounded-full flex items-center justify-center mx-auto">
            <CheckCircle size={32} className="text-green-400" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-white">Import Tamamlandı</h2>
            <p className="text-slate-400 text-sm mt-1">{importResult.filename || 'UCMDB verisi'} başarıyla aktarıldı</p>
          </div>
          <div className="flex justify-center gap-6 text-sm">
            <div><span className="text-2xl font-bold text-green-400">{importResult.created}</span><div className="text-slate-400 text-xs">Yeni Sunucu</div></div>
            <div><span className="text-2xl font-bold text-blue-400">{importResult.updated}</span><div className="text-slate-400 text-xs">Güncellendi</div></div>
            <div><span className="text-2xl font-bold text-slate-400">{importResult.skipped}</span><div className="text-slate-400 text-xs">Atlandı</div></div>
          </div>
          {importResult.errors.length > 0 && (
            <p className="text-amber-400 text-sm">{importResult.errors.length} satırda hata oluştu</p>
          )}
          <div className="flex justify-center gap-3 pt-2">
            <button onClick={reset} className="px-5 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm rounded-lg transition-colors">
              Yeni Import
            </button>
            <a href="/servers" className="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition-colors inline-block">
              Sunuculara Git →
            </a>
          </div>
        </div>
      )}
    </div>
  )
}

export default UCMDBImport
