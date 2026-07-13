import React, { useMemo, useState, useRef, useCallback, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'

// ─── Types ────────────────────────────────────────────────────────────────────
interface Server {
  id: number; name: string; hostname: string; ip_address: string
  status: string; ai_ready?: boolean; os_type?: string
}
interface McpTool {
  name: string; description?: string; category?: string; icon?: string
  schema?: { type?: string; properties?: Record<string, any>; required?: string[] }
}
interface ServerResult {
  server_id: number; server_name: string; host: string
  ok: boolean; result?: any; error?: string; elapsed_ms: number
  tool_name?: string
}

// ─── Output parsers (same as before, abbreviated) ─────────────────────────────
const stripAnsi = (s: string) => s.replace(/\x1B\[[0-?]*[ -/]*[@-~]/g, '')
const trimLines = (s: string) => (s || '').split('\n').map(l => l.trimEnd()).join('\n').trim()

function parseDf(s: string) {
  return s.split('\n').filter(l => l && !/^Filesystem/.test(l)).flatMap(line => {
    const c = line.trim().split(/\s+/)
    if (c.length < 6) return []
    return [{ fs: c[0], size: c[1], used: c[2], avail: c[3], pct: parseInt(c[4]) || 0, mount: c[5] }]
  })
}
function parseFree(s: string) {
  return s.split('\n').flatMap(line => {
    const m = line.match(/^(Mem|Swap):\s+(\S+)\s+(\S+)\s+(\S+)/)
    if (!m) return []
    const pv = (v: string) => { const n = parseFloat(v); const u = v.slice(-1).toUpperCase(); return isNaN(n) ? 0 : n * ({ K: 1, M: 1024, G: 1048576, T: 1073741824 }[u] || 1) }
    const tot = pv(m[2]), used = pv(m[3])
    return [{ label: m[1], total: m[2], used: m[3], free: m[4], pct: tot > 0 ? Math.round(used / tot * 100) : 0 }]
  })
}
function parseTop(s: string) {
  const idx = s.split('\n').findIndex(l => /PID\s+USER/.test(l))
  if (idx < 0) return []
  return s.split('\n').slice(idx + 1, idx + 18).flatMap(line => {
    const c = line.trim().split(/\s+/); if (c.length < 12) return []
    return [{ pid: c[0], user: c[1], cpu: c[8], mem: c[9], cmd: c[11] }]
  })
}
function parsePsAux(s: string) {
  return s.split('\n').filter(l => l && !/^USER/.test(l)).slice(0, 28).flatMap(line => {
    const c = line.trim().split(/\s+/); if (c.length < 11) return []
    return [{ pid: c[1], user: c[0], cpu: c[2], mem: c[3], cmd: c.slice(10).join(' ').slice(0, 55) }]
  })
}
function parseSs(s: string) {
  return s.split('\n').filter(l => l && !/^Netid\s+State/.test(l) && !/^Proto/.test(l)).slice(0, 35).flatMap(line => {
    const c = line.trim().split(/\s+/); if (c.length < 5) return []
    return [{ proto: c[0], local: c[4] || c[3], process: c.slice(6).join(' ').replace(/users:\(\(/, '').replace(/\)\)/, '').replace(/,fd=\d+,uid=\d+/g, '') || '-' }]
  })
}
function parseDmesg(s: string) {
  return s.split('\n').filter(Boolean).slice(0, 50).map(line => {
    const lvl = /error|fail|critical/i.test(line) ? 'error' : /warn/i.test(line) ? 'warn' : 'info'
    const m = line.match(/^\[?\s*([\d.]+)\]?\s*(.*)$/)
    return m ? { lvl, t: m[1], msg: m[2] } : { lvl, t: '', msg: line }
  })
}
function parseLast(s: string) {
  return s.split('\n').filter(l => l && !/^wtmp|^btmp/.test(l)).slice(0, 20).flatMap(line => {
    const c = line.trim().split(/\s+/)
    if (c.length < 4 || c[0] === 'reboot') return []
    return [{ user: c[0], term: c[1], host: c[2], time: c.slice(3, 7).join(' '), active: c.includes('still') }]
  })
}
function parseServices(s: string) {
  return s.split('\n').filter(l => l.includes('.service')).slice(0, 30).map(line => {
    const c = line.trim().split(/\s+/)
    return { name: (c[0] || '').replace('.service', ''), active: c[2] || '-', sub: c[3] || '-', desc: c.slice(4).join(' ').slice(0, 48) }
  })
}

// ─── Bar component ────────────────────────────────────────────────────────────
const Pct: React.FC<{ v: number }> = ({ v }) => {
  const c = v >= 90 ? 'bg-red-500' : v >= 75 ? 'bg-orange-400' : v >= 50 ? 'bg-yellow-400' : 'bg-emerald-400'
  const tc = v >= 90 ? 'text-red-300' : v >= 75 ? 'text-orange-300' : v >= 50 ? 'text-yellow-300' : 'text-slate-300'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-white/[0.07] rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${c}`} style={{ width: `${Math.min(v, 100)}%` }} />
      </div>
      <span className={`text-xs font-mono w-8 text-right ${tc}`}>{v}%</span>
    </div>
  )
}

// ─── Smart renderers ──────────────────────────────────────────────────────────
const Term: React.FC<{ text: string }> = ({ text }) => (
  <pre className="text-xs text-emerald-300/90 font-mono whitespace-pre-wrap leading-[1.6] break-all">
    {trimLines(stripAnsi(text))}
  </pre>
)

const Disk: React.FC<{ s: string }> = ({ s }) => {
  const rows = parseDf(s); if (!rows.length) return <Term text={s} />
  return (
    <div className="space-y-2">
      {rows.map((r, i) => (
        <div key={i} className="bg-cyber-deep/50 rounded-lg p-2.5 space-y-1">
          <div className="flex justify-between text-xs">
            <span className="text-cyan-300 font-mono truncate max-w-[160px]" title={r.fs}>{r.fs} <span className="text-slate-500 text-[10px]">{r.mount}</span></span>
            <span className="text-slate-400 font-mono">{r.used}/{r.size}</span>
          </div>
          <Pct v={r.pct} />
        </div>
      ))}
    </div>
  )
}

const Mem: React.FC<{ s: string }> = ({ s }) => {
  const rows = parseFree(s); if (!rows.length) return <Term text={s} />
  return (
    <div className="space-y-2">
      {rows.map((r, i) => (
        <div key={i} className="bg-cyber-deep/50 rounded-lg p-2.5 space-y-1">
          <div className="flex justify-between text-xs">
            <span className="text-blue-300 font-semibold">{r.label === 'Mem' ? 'RAM' : 'Swap'}</span>
            <span className="text-slate-400 font-mono">{r.used}/{r.total}</span>
          </div>
          <Pct v={r.pct} />
        </div>
      ))}
    </div>
  )
}

const ProcTable: React.FC<{ rows: { pid: string; user: string; cpu: string; mem: string; cmd: string }[] }> = ({ rows }) => (
  <table className="w-full text-xs">
    <thead className="text-[10px] text-slate-500 uppercase">
      <tr className="border-b border-white/[0.04]"><th className="text-left py-1 pr-2">PID</th><th className="text-left py-1 pr-2">User</th><th className="text-right py-1 pr-2">CPU%</th><th className="text-right py-1 pr-2">MEM%</th><th className="text-left py-1">Komut</th></tr>
    </thead>
    <tbody className="divide-y divide-white/[0.05]/20">
      {rows.map((r, i) => {
        const cpu = parseFloat(r.cpu)
        return (
          <tr key={i} className="hover:bg-white/[0.03]">
            <td className="py-0.5 pr-2 text-slate-500 font-mono">{r.pid}</td>
            <td className="py-0.5 pr-2 text-cyan-300">{r.user}</td>
            <td className="py-0.5 pr-2 text-right font-mono"><span className={cpu > 50 ? 'text-red-300' : cpu > 10 ? 'text-yellow-300' : 'text-slate-300'}>{r.cpu}</span></td>
            <td className="py-0.5 pr-2 text-right font-mono text-slate-400">{r.mem}</td>
            <td className="py-0.5 text-emerald-300 font-mono truncate max-w-[180px]" title={r.cmd}>{r.cmd}</td>
          </tr>
        )
      })}
    </tbody>
  </table>
)

const Ports: React.FC<{ s: string }> = ({ s }) => {
  const rows = parseSs(s); if (!rows.length) return <Term text={s} />
  return (
    <table className="w-full text-xs">
      <thead className="text-[10px] text-slate-500 uppercase"><tr className="border-b border-white/[0.04]"><th className="text-left py-1 pr-2">Proto</th><th className="text-left py-1 pr-2">Yerel</th><th className="text-left py-1">Süreç</th></tr></thead>
      <tbody className="divide-y divide-white/[0.05]/20">
        {rows.map((r, i) => (
          <tr key={i} className="hover:bg-white/[0.03]">
            <td className="py-0.5 pr-2"><span className={`px-1 rounded text-[10px] font-mono ${r.proto.startsWith('tcp') ? 'bg-blue-500/20 text-blue-300' : 'bg-orange-500/20 text-orange-300'}`}>{r.proto.toUpperCase()}</span></td>
            <td className="py-0.5 pr-2 font-mono text-cyan-300 text-[11px]">{r.local}</td>
            <td className="py-0.5 font-mono text-emerald-300 text-[11px] truncate max-w-[180px]">{r.process}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

const Dmesg: React.FC<{ s: string }> = ({ s }) => {
  const rows = parseDmesg(s); if (!rows.length) return <Term text={s} />
  return (
    <div className="space-y-0.5 font-mono text-xs">
      {rows.map((r, i) => (
        <div key={i} className={`flex gap-2 px-2 py-0.5 rounded ${r.lvl === 'error' ? 'bg-red-500/10 text-red-300' : r.lvl === 'warn' ? 'bg-yellow-500/10 text-yellow-300' : 'text-slate-400'}`}>
          <span className="text-slate-600 shrink-0 w-12 truncate text-[10px]">{r.t}</span>
          <span className="shrink-0">{r.lvl === 'error' ? '✕' : r.lvl === 'warn' ? '⚠' : '·'}</span>
          <span className="break-all">{r.msg}</span>
        </div>
      ))}
    </div>
  )
}

const Logins: React.FC<{ s: string }> = ({ s }) => {
  const rows = parseLast(s); if (!rows.length) return <Term text={s} />
  return (
    <table className="w-full text-xs">
      <thead className="text-[10px] text-slate-500 uppercase"><tr className="border-b border-white/[0.04]"><th className="text-left py-1 pr-2">Kullanıcı</th><th className="text-left py-1 pr-2">Terminal</th><th className="text-left py-1 pr-2">Kaynak</th><th className="text-left py-1 pr-2">Zaman</th><th className="text-left py-1">Durum</th></tr></thead>
      <tbody className="divide-y divide-white/[0.05]/20">
        {rows.map((r, i) => (
          <tr key={i} className="hover:bg-white/[0.03]">
            <td className="py-0.5 pr-2 text-cyan-300 font-medium">{r.user}</td>
            <td className="py-0.5 pr-2 font-mono text-slate-500">{r.term}</td>
            <td className="py-0.5 pr-2 font-mono text-slate-500">{r.host}</td>
            <td className="py-0.5 pr-2 text-slate-400">{r.time}</td>
            <td className="py-0.5"><span className={`px-1.5 rounded-full text-[10px] ${r.active ? 'bg-green-500/20 text-green-300' : 'bg-white/[0.07] text-slate-400'}`}>{r.active ? '● aktif' : 'çıktı'}</span></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

const Services: React.FC<{ s: string }> = ({ s }) => {
  const rows = parseServices(s); if (!rows.length) return <Term text={s} />
  return (
    <table className="w-full text-xs">
      <thead className="text-[10px] text-slate-500 uppercase"><tr className="border-b border-white/[0.04]"><th className="text-left py-1 pr-2">Servis</th><th className="text-left py-1 pr-2">Durum</th><th className="text-left py-1">Açıklama</th></tr></thead>
      <tbody className="divide-y divide-white/[0.05]/20">
        {rows.map((r, i) => (
          <tr key={i} className="hover:bg-white/[0.03]">
            <td className="py-0.5 pr-2 text-cyan-300 font-mono truncate max-w-[140px]">{r.name}</td>
            <td className="py-0.5 pr-2"><span className={`px-1.5 rounded-full text-[10px] ${r.active === 'active' ? 'bg-green-500/20 text-green-300' : 'bg-red-500/20 text-red-300'}`}>{r.active}</span></td>
            <td className="py-0.5 text-slate-400 truncate max-w-[180px]">{r.desc}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

const OsInfo: React.FC<{ s: string }> = ({ s }) => {
  const info: Record<string, string> = {}
  s.split('\n').forEach(l => { const [k, ...v] = l.split('='); if (k && v.length) info[k.trim()] = v.join('=').replace(/^"|"$/g, '').trim() })
  const km = s.match(/---KERNEL---\n(.+)/); if (km) info['Kernel'] = km[1].trim()
  const hm = s.match(/---HOSTNAME---\n(.+)/); if (hm) info['Hostname'] = hm[1].trim()
  const cm = s.match(/Model name[:\s]+(.+)/); if (cm) info['CPU'] = cm[1].trim()
  const wanted = ['PRETTY_NAME', 'NAME', 'VERSION', 'Kernel', 'Hostname', 'CPU', 'ID', 'VERSION_ID']
  const rows = wanted.filter(k => info[k])
  return (
    <div className="space-y-1">
      {rows.map(k => (
        <div key={k} className="flex gap-3 bg-cyber-deep/50 rounded px-3 py-1.5">
          <span className="text-xs text-slate-500 w-28 shrink-0">{k}</span>
          <span className="text-xs text-emerald-300 font-mono break-all">{info[k]}</span>
        </div>
      ))}
    </div>
  )
}

const UptimeCard: React.FC<{ s: string }> = ({ s }) => {
  const line = s.split('\n')[0]
  const lm = s.match(/load average[s]?:\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/)
  const um = line.match(/up\s+([\d\s\w,]+?),\s+\d+ user/)
  return (
    <div className="space-y-3">
      <div className="bg-cyber-deep/50 rounded-lg p-3"><div className="text-xs text-slate-500 mb-1">Uptime</div><div className="text-lg font-mono text-cyan-300">{um?.[1]?.trim() || line}</div></div>
      {lm && (
        <div className="grid grid-cols-3 gap-2">
          {['1dk', '5dk', '15dk'].map((lb, i) => {
            const v = parseFloat(lm[i + 1])
            return <div key={i} className="bg-cyber-deep/50 rounded-lg p-2 text-center"><div className="text-[10px] text-slate-500">Yük {lb}</div><div className={`text-xl font-bold ${v > 2 ? 'text-red-300' : v > 1 ? 'text-yellow-300' : 'text-emerald-300'}`}>{lm[i + 1]}</div></div>
          })}
        </div>
      )}
    </div>
  )
}

const McpOut: React.FC<{ r: any }> = ({ r }) => {
  const content = r?.content ?? r?.result?.content
  if (Array.isArray(content)) {
    const text = content.filter((c: any) => c?.type === 'text').map((c: any) => c.text).join('\n')
    return <Term text={text || JSON.stringify(r, null, 2)} />
  }
  const text = r?.stdout || r?.result?.stdout || r?.text
  return <Term text={typeof text === 'string' ? text : JSON.stringify(r, null, 2)} />
}

function SmartOutput({ toolName, result }: { toolName: string; result: ServerResult }) {
  if (!result.ok) return <div className="flex gap-2 text-red-300 bg-red-500/10 rounded p-3 text-xs"><span>✕</span><span>{result.error}</span></div>
  const stdout = result.result?.stdout ?? ''
  if (toolName === 'builtin.disk') return <Disk s={stdout} />
  if (toolName === 'builtin.memory') return <Mem s={stdout} />
  if (toolName === 'builtin.cpu_top') { const r = parseTop(stdout); return r.length ? <ProcTable rows={r} /> : <Term text={stdout} /> }
  if (toolName === 'builtin.processes') { const r = parsePsAux(stdout); return r.length ? <ProcTable rows={r} /> : <Term text={stdout} /> }
  if (toolName === 'builtin.network_ports') return <Ports s={stdout} />
  if (toolName === 'builtin.dmesg_errors') return <Dmesg s={stdout} />
  if (toolName === 'builtin.last_logins') return <Logins s={stdout} />
  if (toolName === 'builtin.services') return <Services s={stdout} />
  if (toolName === 'builtin.os_info') return <OsInfo s={stdout} />
  if (toolName === 'builtin.uptime') return <UptimeCard s={stdout} />
  if (toolName.startsWith('builtin.')) return <Term text={stdout} />
  return <McpOut r={result.result} />
}

// ─── Args form ────────────────────────────────────────────────────────────────
const ArgsForm: React.FC<{ tool: McpTool; args: Record<string, string>; onChange: (k: string, v: string) => void }> = ({ tool, args, onChange }) => {
  const props = tool.schema?.properties
  if (!props || Object.keys(props).length === 0) return null
  const req = tool.schema?.required || []
  return (
    <div className="mt-2 grid grid-cols-2 gap-2">
      {Object.entries(props).map(([k, def]: [string, any]) => (
        <div key={k}>
          <label className="text-[10px] text-slate-500 mb-0.5 block">{k}{req.includes(k) && <span className="text-red-400">*</span>}</label>
          <input type={def.type === 'integer' || def.type === 'number' ? 'number' : 'text'}
            value={args[k] ?? ''} onChange={e => onChange(k, e.target.value)}
            placeholder={def.description || k}
            className="w-full bg-cyber-deep border border-white/[0.06] rounded px-2 py-1 text-xs text-white font-mono focus:border-blue-500 outline-none" />
        </div>
      ))}
    </div>
  )
}

// ─── Category config ──────────────────────────────────────────────────────────
const CAT: Record<string, { label: string; color: string }> = {
  system:   { label: 'Sistem',   color: 'text-cyan-400' },
  storage:  { label: 'Depolama', color: 'text-amber-400' },
  process:  { label: 'Süreçler', color: 'text-blue-400' },
  network:  { label: 'Ağ',       color: 'text-blue-400' },
  security: { label: 'Güvenlik', color: 'text-rose-400' },
  mcp:      { label: 'MCP',      color: 'text-emerald-400' },
}

// ─── AI Chat panel ────────────────────────────────────────────────────────────
const AiPanel: React.FC<{ results: ServerResult[]; toolName: string }> = ({ results, toolName }) => {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [analyzing, setAnalyzing] = useState(false)
  const [open, setOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const answerRef = useRef<HTMLDivElement>(null)

  const analyze = useCallback(async (q?: string) => {
    setAnalyzing(true)
    setAnswer('')
    setOpen(true)
    const payload = {
      results: results.map(r => ({ ...r, tool_name: toolName })),
      question: q || question || undefined,
    }
    try {
      const resp = await fetch(`${API_BASE_URL}/mcp/analyze`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!resp.ok || !resp.body) { setAnswer('AI analizi başarısız'); setAnalyzing(false); return }
      const reader = resp.body.getReader()
      const dec = new TextDecoder()
      let buf = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const parts = buf.split('\n')
        buf = parts.pop() || ''
        for (const part of parts) {
          const line = part.replace(/^data:\s*/, '').trim()
          if (!line) continue
          try {
            const j = JSON.parse(line)
            if (j.response) setAnswer(prev => prev + j.response)
            if (j.error) setAnswer(prev => prev + '\n[Hata: ' + j.error + ']')
          } catch { /* ignore */ }
        }
      }
    } catch (e) {
      setAnswer('Bağlantı hatası: ' + String(e))
    } finally {
      setAnalyzing(false)
    }
  }, [results, toolName, question])

  // Auto-scroll
  useEffect(() => {
    if (answerRef.current) answerRef.current.scrollTop = answerRef.current.scrollHeight
  }, [answer])

  return (
    <div className="bg-cyber-card/70 border border-white/[0.06] rounded-xl overflow-hidden">
      <button onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium text-white hover:bg-white/[0.03] transition-colors">
        <span className="flex items-center gap-2">
          <span className="text-[10px] font-bold text-blue-400 bg-blue-500/15 border border-blue-500/30 px-1 rounded">AI</span>
          <span>AI Analiz</span>
          {analyzing && <span className="w-3 h-3 border-2 border-blue-400/40 border-t-blue-400 rounded-full animate-spin" />}
          {!open && answer && <span className="text-[10px] text-emerald-400 border border-emerald-500/30 rounded px-1.5 py-0.5">yanıt hazır</span>}
        </span>
        <span className="text-slate-400 text-xs">{open ? '▲ Kapat' : '▼ Aç'}</span>
      </button>

      {open && (
        <div className="border-t border-white/[0.06]/60">
          {/* Quick prompts */}
          <div className="flex gap-1.5 flex-wrap px-4 pt-3 pb-1">
            {[
              'Genel durum analizi yap, sorunları listele',
              'Dikkat gerektiren kritik değerler var mı?',
              'Sunucular arası farklılıkları karşılaştır',
              'Performans iyileştirme önerisi ver',
            ].map(q => (
              <button key={q} onClick={() => { setQuestion(q); analyze(q) }}
                className="text-[10px] px-2 py-1 rounded-lg border border-white/[0.06] text-slate-400 hover:border-blue-500/50 hover:text-blue-300 transition-colors">
                {q}
              </button>
            ))}
          </div>

          {/* Custom question */}
          <div className="flex gap-2 px-4 pb-3 pt-1">
            <input ref={inputRef} value={question} onChange={e => setQuestion(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !analyzing && analyze()}
              placeholder="Soru sor... (ör. 'Disk %90 üstündeki sunucular hangileri?')"
              className="flex-1 bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-1.5 text-xs text-white placeholder-slate-600 focus:border-blue-500 outline-none" />
            <button onClick={() => analyze()} disabled={analyzing}
              className="px-3 py-1.5 rounded-lg bg-gradient-to-r from-blue-600 to-blue-600 hover:from-blue-500 hover:to-blue-500 disabled:opacity-40 text-white text-xs font-medium transition-all">
              {analyzing ? '...' : 'Analiz Et'}
            </button>
          </div>

          {/* Answer */}
          {(answer || analyzing) && (
            <div ref={answerRef} className="mx-4 mb-4 bg-slate-950/60 border border-white/[0.06]/50 rounded-xl p-4 max-h-72 overflow-y-auto">
              {answer ? (
                <div className="text-sm text-slate-200 whitespace-pre-wrap leading-relaxed">
                  {answer.split('\n').map((line, i) => {
                    const isWarn = /^⚠/.test(line), isOk = /^✓/.test(line), isTip = /^💡/.test(line)
                    return (
                      <div key={i} className={`${isWarn ? 'text-yellow-300' : isOk ? 'text-emerald-300' : isTip ? 'text-cyan-300' : ''}`}>
                        {line || <br />}
                      </div>
                    )
                  })}
                  {analyzing && <span className="inline-block w-2 h-4 bg-blue-400 animate-pulse ml-0.5" />}
                </div>
              ) : (
                <div className="flex items-center gap-2 text-slate-500 text-xs">
                  <span className="w-3 h-3 border-2 border-slate-600 border-t-blue-400 rounded-full animate-spin" />
                  Analiz ediliyor...
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────
const McpTools: React.FC = () => {
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [selectedTool, setSelectedTool] = useState<McpTool | null>(null)
  const [args, setArgs] = useState<Record<string, string>>({})
  const [results, setResults] = useState<ServerResult[]>([])
  const [activeTab, setActiveTab] = useState<number | null>(null)
  const [rawMode, setRawMode] = useState(false)
  const [error, setError] = useState('')
  const [running, setRunning] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [toolName, setToolName] = useState('')
  const timerRef = useRef<ReturnType<typeof setInterval>>()

  const { data: servers = [], isLoading: serversLoading } = useQuery<Server[]>({
    queryKey: ['mcp-servers'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/servers/ai-ready/list`)
      if (r.ok) { const d = await r.json(); if (Array.isArray(d) && d.length) return d }
      const r2 = await fetch(`${API_BASE_URL}/servers/`)
      if (!r2.ok) throw new Error('Sunucu listesi alınamadı')
      return r2.json()
    }
  })

  const { data: toolsData, isLoading: toolsLoading, refetch: refetchTools } = useQuery({
    queryKey: ['mcp-tools-v2'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/mcp/tools`)
      const b = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(b?.detail || 'MCP araç listesi alınamadı')
      return { tools: (b?.tools || []) as McpTool[], warning: b?.warning || null }
    }
  })

  const tools: McpTool[] = toolsData?.tools || []
  const toolGroups = useMemo(() => {
    const g: Record<string, McpTool[]> = {}
    tools.forEach(t => { const c = t.category || 'mcp'; g[c] = [...(g[c] || []), t] })
    return g
  }, [tools])

  const aiReadyIds = useMemo(() => new Set(servers.filter(s => s.ai_ready).map(s => s.id)), [servers])
  const toggleServer = (id: number) => setSelectedIds(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  const selectAll = () => setSelectedIds(new Set(servers.map(s => s.id)))
  const selectAiReady = () => setSelectedIds(new Set(aiReadyIds))
  const clearSel = () => setSelectedIds(new Set())
  const setArg = useCallback((k: string, v: string) => setArgs(p => ({ ...p, [k]: v })), [])

  const runTool = async () => {
    if (!selectedTool || selectedIds.size === 0) return
    setRunning(true); setError(''); setResults([]); setActiveTab(null); setElapsed(0)
    const t0 = Date.now()
    timerRef.current = setInterval(() => setElapsed(Date.now() - t0), 100)

    const parsedArgs: Record<string, any> = {}
    if (selectedTool.schema?.properties) {
      Object.entries(args).forEach(([k, v]) => {
        const def = selectedTool.schema!.properties![k]
        parsedArgs[k] = def?.type === 'integer' ? parseInt(v) : def?.type === 'number' ? parseFloat(v) : def?.type === 'boolean' ? v === 'true' : v
      })
    }

    try {
      const r = await fetch(`${API_BASE_URL}/mcp/run-multi`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool_name: selectedTool.name, server_ids: [...selectedIds], arguments: parsedArgs })
      })
      const body = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(body?.detail || 'Araç çalıştırılamadı')
      const res: ServerResult[] = body.results || []
      setResults(res)
      setToolName(body.tool_name || selectedTool.name)
      if (res.length > 0) setActiveTab(res[0].server_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Bilinmeyen hata')
    } finally {
      clearInterval(timerRef.current); setRunning(false); setElapsed(Date.now() - t0)
    }
  }

  const activeResult = results.find(r => r.server_id === activeTab)
  const successCount = results.filter(r => r.ok).length
  const failCount = results.length - successCount

  return (
    <div className="flex gap-3 overflow-hidden" style={{ height: 'calc(100vh - 112px)' }}>

      {/* ── Left panel ──────────────────────────────────────── */}
      <div className="w-64 flex flex-col gap-2 overflow-y-auto shrink-0">

        {/* Server selection */}
        <div className="bg-cyber-card/70 border border-white/[0.06] rounded-xl p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Sunucular</span>
            <div className="flex gap-1">
              <button onClick={selectAiReady} title="AI Ready seç" className="text-xs px-2 py-1 rounded border border-cyan-700/60 text-cyan-400 hover:bg-cyan-700/20">AI</button>
              <button onClick={selectAll} title="Tümünü seç" className="text-xs px-2 py-1 rounded border border-slate-600 text-slate-400 hover:bg-white/[0.06]/50">Tümü</button>
              <button onClick={clearSel} title="Seçimi temizle" className="text-xs px-2 py-1 rounded border border-slate-600 text-slate-400 hover:bg-white/[0.06]/50">✕</button>
            </div>
          </div>

          {serversLoading ? (
            <div className="text-xs text-slate-500 animate-pulse py-2">Yükleniyor...</div>
          ) : (
            <div className="space-y-0.5">
              {servers.map(s => {
                const sel = selectedIds.has(s.id)
                return (
                  <button key={s.id} onClick={() => toggleServer(s.id)}
                    className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-lg transition-all text-xs ${sel ? 'bg-blue-600/25 border border-blue-500/40' : 'border border-transparent hover:bg-white/[0.04]'}`}>
                    <div className={`w-3.5 h-3.5 rounded border flex items-center justify-center shrink-0 ${sel ? 'bg-blue-600 border-blue-500' : 'border-slate-600'}`}>
                      {sel && <span className="text-white text-[9px]">✓</span>}
                    </div>
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${s.status === 'online' ? 'bg-emerald-400' : 'bg-red-400'}`} />
                    <span className={`font-medium truncate ${sel ? 'text-white' : 'text-slate-300'}`}>{s.name}</span>
                    {s.ai_ready && <span className="text-[9px] text-cyan-400 shrink-0 ml-auto">AI</span>}
                  </button>
                )
              })}
            </div>
          )}

          {selectedIds.size > 0 && (
            <div className="mt-2 pt-2 border-t border-white/[0.05] text-[10px] text-slate-400 text-center">
              {selectedIds.size} sunucu seçili
            </div>
          )}
        </div>

        {/* Tool list */}
        <div className="bg-cyber-card/70 border border-white/[0.06] rounded-xl p-3 flex-1 overflow-y-auto">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Araçlar</span>
            <button onClick={() => void refetchTools()} className="text-[10px] text-slate-500 hover:text-slate-300 border border-white/[0.06] rounded px-1.5 py-0.5">↺</button>
          </div>
          {toolsLoading ? (
            <div className="text-xs text-slate-500 animate-pulse">Yükleniyor...</div>
          ) : (
            <div className="space-y-3">
              {Object.entries(toolGroups).map(([cat, catTools]) => (
                <div key={cat}>
                  <div className={`text-[9px] font-bold uppercase tracking-widest mb-1 ${CAT[cat]?.color || 'text-slate-400'}`}>{CAT[cat]?.label || cat}</div>
                  <div className="space-y-0.5">
                    {catTools.map(t => (
                      <button key={t.name} onClick={() => { setSelectedTool(t); setArgs({}); setResults([]); setError('') }}
                        className={`w-full text-left px-2 py-1.5 rounded-lg transition-all text-xs flex items-center gap-2 ${selectedTool?.name === t.name ? 'bg-blue-600/30 border border-blue-500/40 text-white' : 'border border-transparent hover:bg-white/[0.04] text-slate-300'}`}>
                        <span className="text-sm shrink-0">{t.icon || '●'}</span>
                        <div className="min-w-0">
                          <div className="font-mono text-[11px] truncate">{t.name.replace('builtin.', '')}</div>
                          {t.description && <div className="text-[9px] text-slate-500 leading-tight truncate">{t.description}</div>}
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
          {toolsData?.warning && <div className="mt-2 text-[9px] text-amber-400/70 border-t border-white/[0.05] pt-2">{toolsData.warning}</div>}
        </div>
      </div>

      {/* ── Right panel ─────────────────────────────────────── */}
      <div className="flex-1 flex flex-col gap-2 overflow-hidden min-w-0">

        {/* Control bar */}
        <div className="bg-cyber-card/70 border border-white/[0.06] rounded-xl p-3 shrink-0">
          {selectedTool ? (
            <div>
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-2 min-w-0">
                  <span className="text-2xl shrink-0">{selectedTool.icon}</span>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-white">{selectedTool.name.replace('builtin.', '')}</div>
                    <div className="text-[11px] text-slate-400">{selectedTool.description}</div>
                    {selectedIds.size > 0 ? (
                      <div className="text-[10px] text-cyan-400 mt-0.5">
                        {selectedIds.size} sunucuda çalışacak →{' '}
                        {servers.filter(s => selectedIds.has(s.id)).map(s => s.name).join(', ')}
                      </div>
                    ) : (
                      <div className="text-[10px] text-amber-400 mt-0.5">⚠ Sol panelden sunucu seçin</div>
                    )}
                  </div>
                </div>
                <button onClick={runTool} disabled={!selectedTool || selectedIds.size === 0 || running}
                  className="shrink-0 flex items-center gap-2 px-5 py-2 rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium transition-all shadow-lg shadow-blue-500/20">
                  {running
                    ? <><span className="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" /> {(elapsed / 1000).toFixed(1)}s</>
                    : `▶ Çalıştır${selectedIds.size > 1 ? ` (${selectedIds.size})` : ''}`
                  }
                </button>
              </div>
              <ArgsForm tool={selectedTool} args={args} onChange={setArg} />
            </div>
          ) : (
            <div className="text-xs text-slate-500 py-1">Sol panelden araç seçin</div>
          )}
        </div>

        {/* Error */}
        {error && <div className="bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-2.5 text-red-300 text-xs flex gap-2 shrink-0"><span>✕</span><span>{error}</span></div>}

        {/* Results */}
        {results.length > 0 && (
          <div className="flex-1 flex flex-col bg-cyber-card/70 border border-white/[0.06] rounded-xl overflow-hidden min-h-0">
            {/* Server tabs */}
            <div className="flex items-center gap-0.5 px-3 pt-2 pb-0 border-b border-white/[0.06] overflow-x-auto shrink-0">
              {results.map(r => (
                <button key={r.server_id} onClick={() => { setActiveTab(r.server_id); setRawMode(false) }}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-t-lg text-xs transition-all shrink-0 ${activeTab === r.server_id ? 'bg-cyber-deep/60 text-white border-x border-t border-white/[0.06]/60' : 'text-slate-400 hover:text-slate-200'}`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${r.ok ? 'bg-emerald-400' : 'bg-red-400'}`} />
                  <span className="font-medium">{r.server_name}</span>
                  <span className="text-[10px] text-slate-500">{r.elapsed_ms}ms</span>
                </button>
              ))}
              {/* Summary pill */}
              <div className="ml-auto shrink-0 flex items-center gap-1.5 text-[10px] pb-2 pr-1">
                {successCount > 0 && <span className="px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">✓ {successCount}</span>}
                {failCount > 0 && <span className="px-2 py-0.5 rounded-full bg-red-500/15 text-red-300 border border-red-500/30">✕ {failCount}</span>}
                <span className="text-slate-500">{(elapsed / 1000).toFixed(2)}s</span>
              </div>
            </div>

            {/* Active tab output header */}
            {activeResult && (
              <div className="flex items-center justify-between px-3 py-1.5 bg-cyber-deep/30 shrink-0">
                <div className="flex items-center gap-2 text-[10px] text-slate-500 font-mono">
                  <span>{activeResult.result?.command || toolName}</span>
                  <span className="text-slate-700">·</span>
                  <span className="text-cyan-400">{activeResult.host}</span>
                </div>
                <div className="flex gap-1">
                  <button onClick={() => setRawMode(false)} className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${!rawMode ? 'bg-blue-600/30 border-blue-500/40 text-blue-200' : 'border-white/[0.06] text-slate-500 hover:text-slate-300'}`}>Görsel</button>
                  <button onClick={() => setRawMode(true)} className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${rawMode ? 'bg-blue-600/30 border-blue-500/40 text-blue-200' : 'border-white/[0.06] text-slate-500 hover:text-slate-300'}`}>Ham</button>
                </div>
              </div>
            )}

            {/* Output body */}
            <div className="flex-1 overflow-y-auto p-4 bg-slate-950/40 min-h-0">
              {activeResult && (
                rawMode
                  ? <Term text={activeResult.result?.stdout || activeResult.error || JSON.stringify(activeResult.result, null, 2)} />
                  : <SmartOutput toolName={toolName} result={activeResult} />
              )}
            </div>
          </div>
        )}

        {/* AI Panel */}
        {results.length > 0 && <AiPanel results={results} toolName={toolName} />}

        {/* Empty state */}
        {results.length === 0 && !error && !running && (
          <div className="flex-1 flex flex-col items-center justify-center gap-4 text-center">
            <div className="w-16 h-16 bg-cyber-card/60 rounded-2xl flex items-center justify-center opacity-40"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg></div>
            <div className="space-y-1">
              <div className="text-sm text-slate-500">Sunucu(lar) ve araç seçip çalıştırın</div>
              <div className="text-xs text-slate-600">Çoklu sunucu seçimi destekleniyor · Paralel çalışır · AI analiz eder</div>
            </div>
          </div>
        )}

        {/* Running skeleton */}
        {running && results.length === 0 && (
          <div className="flex-1 flex flex-col items-center justify-center gap-4">
            <div className="flex items-center gap-3 text-slate-400">
              <span className="w-5 h-5 border-2 border-slate-600 border-t-blue-400 rounded-full animate-spin" />
              <span className="text-sm">{selectedIds.size} sunucuda {selectedTool?.name.replace('builtin.', '')} çalışıyor…</span>
            </div>
            <div className="flex gap-2">
              {servers.filter(s => selectedIds.has(s.id)).map(s => (
                <div key={s.id} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyber-card/50 border border-white/[0.06] text-xs text-slate-400 animate-pulse">
                  <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-ping" />
                  {s.name}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default McpTools
