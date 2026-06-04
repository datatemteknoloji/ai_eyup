import React, { useMemo, useState, useRef, useCallback } from 'react'
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
interface RunRecord {
  id: number; server: string; tool: string; icon: string
  ok: boolean; elapsed: number; result: any; ts: Date
}

// ─── Output parsers ───────────────────────────────────────────────────────────
function stripAnsi(s: string) { return s.replace(/\x1B\[[0-?]*[ -/]*[@-~]/g, '') }
function trimLines(s: string) { return (s || '').split('\n').map(l => l.trimEnd()).join('\n').trim() }

function parseDf(stdout: string): { fs: string; size: string; used: string; avail: string; pct: number; mount: string }[] {
  const lines = trimLines(stdout).split('\n').filter(l => l && !l.startsWith('Filesystem'))
  return lines.flatMap(line => {
    const cols = line.trim().split(/\s+/)
    if (cols.length < 6) return []
    const pct = parseInt(cols[4]) || 0
    return [{ fs: cols[0], size: cols[1], used: cols[2], avail: cols[3], pct, mount: cols[5] }]
  })
}

function parseFree(stdout: string): { label: string; total: string; used: string; free: string; pct: number }[] {
  const lines = trimLines(stdout).split('\n')
  return lines.flatMap(line => {
    const m = line.match(/^(Mem|Swap):\s+(\S+)\s+(\S+)\s+(\S+)/)
    if (!m) return []
    // Parse sizes for pct (supports K/M/G/T suffixes from free -h or raw bytes from free)
    const parseVal = (v: string) => {
      const n = parseFloat(v)
      const s = v.slice(-1).toUpperCase()
      const mult: Record<string, number> = { K: 1, M: 1024, G: 1024 * 1024, T: 1024 * 1024 * 1024 }
      return isNaN(n) ? 0 : n * (mult[s] || 1)
    }
    const total = parseVal(m[2]), used = parseVal(m[3])
    const pct = total > 0 ? Math.round((used / total) * 100) : 0
    return [{ label: m[1], total: m[2], used: m[3], free: m[4], pct }]
  })
}

function parseTop(stdout: string): { pid: string; user: string; cpu: string; mem: string; vsz: string; rss: string; cmd: string }[] {
  const lines = trimLines(stdout).split('\n')
  const headerIdx = lines.findIndex(l => /PID\s+USER/.test(l))
  if (headerIdx < 0) return []
  return lines.slice(headerIdx + 1, headerIdx + 20).flatMap(line => {
    const cols = line.trim().split(/\s+/)
    if (cols.length < 12) return []
    return [{ pid: cols[0], user: cols[1], cpu: cols[8], mem: cols[9], vsz: cols[4], rss: cols[5], cmd: cols[11] }]
  })
}

function parsePsAux(stdout: string): { pid: string; user: string; cpu: string; mem: string; vsz: string; rss: string; cmd: string }[] {
  const lines = trimLines(stdout).split('\n').filter(l => l && !/^USER/.test(l))
  return lines.slice(0, 30).flatMap(line => {
    const cols = line.trim().split(/\s+/)
    if (cols.length < 11) return []
    return [{ pid: cols[1], user: cols[0], cpu: cols[2], mem: cols[3], vsz: cols[4], rss: cols[5], cmd: cols.slice(10).join(' ').slice(0, 60) }]
  })
}

function parseSs(stdout: string): { proto: string; local: string; peer: string; process: string }[] {
  const lines = trimLines(stdout).split('\n').filter(l => l && !/^Netid\s+State/.test(l) && !l.startsWith('Proto'))
  return lines.slice(0, 40).flatMap(line => {
    // ss -tulpen output: Netid State Recv-Q Send-Q Local Peer Process
    const cols = line.trim().split(/\s+/)
    if (cols.length < 5) return []
    const proto = cols[0]
    const local = cols[4] || cols[3]
    const peer = cols[5] || '-'
    const proc = cols.slice(6).join(' ').replace(/users:\(\(/, '').replace(/\)\)/, '').replace(/,fd=\d+,uid=\d+/g, '')
    return [{ proto, local, peer, process: proc || '-' }]
  })
}

function parseDmesg(stdout: string): { level: string; time: string; msg: string }[] {
  return trimLines(stdout).split('\n').filter(Boolean).slice(0, 60).map(line => {
    const warnMatch = /warn/i.test(line)
    const errMatch = /error|fail|critical/i.test(line)
    const level = errMatch ? 'error' : warnMatch ? 'warn' : 'info'
    const timeMatch = line.match(/^\[?\s*([\d.]+)\]?\s*(.*)$/)
    return timeMatch
      ? { level, time: timeMatch[1], msg: timeMatch[2] }
      : { level, time: '', msg: line }
  })
}

function parseLast(stdout: string): { user: string; term: string; host: string; time: string; status: string }[] {
  return trimLines(stdout).split('\n').filter(l => l && !l.startsWith('wtmp') && !l.startsWith('btmp')).slice(0, 25).flatMap(line => {
    const cols = line.trim().split(/\s+/)
    if (cols.length < 4 || cols[0] === 'reboot') return []
    return [{ user: cols[0], term: cols[1], host: cols[2], time: cols.slice(3, 7).join(' '), status: cols.includes('still') ? 'active' : 'ended' }]
  })
}

function parseServices(stdout: string): { name: string; load: string; active: string; sub: string; desc: string }[] {
  return trimLines(stdout).split('\n').filter(l => l.includes('.service')).slice(0, 35).map(line => {
    const cols = line.trim().split(/\s+/)
    return { name: cols[0]?.replace('.service', '') || '-', load: cols[1] || '-', active: cols[2] || '-', sub: cols[3] || '-', desc: cols.slice(4).join(' ').slice(0, 50) }
  })
}

function parseOsInfo(stdout: string): Record<string, string> {
  const info: Record<string, string> = {}
  trimLines(stdout).split('\n').forEach(line => {
    const [k, ...rest] = line.split('=')
    if (!k) return
    const v = rest.join('=').replace(/^["']|["']$/g, '')
    if (k.trim() === '---KERNEL---') return
    if (!k.startsWith('---') && v) info[k.trim()] = v.trim()
    if (line.startsWith('Linux') && !line.includes('=')) info['Kernel'] = line.trim()
  })
  // Extract from sections too
  const kernelMatch = stdout.match(/---KERNEL---\n(.+)/)
  if (kernelMatch) info['Kernel'] = kernelMatch[1].trim()
  const hostMatch = stdout.match(/---HOSTNAME---\n(.+)/)
  if (hostMatch) info['Hostname'] = hostMatch[1].trim()
  const cpuMatch = stdout.match(/Model name[:\s]+(.+)/)
  if (cpuMatch) info['CPU'] = cpuMatch[1].trim()
  return info
}

// ─── Renderers ────────────────────────────────────────────────────────────────
const BarFill: React.FC<{ pct: number }> = ({ pct }) => {
  const color = pct >= 90 ? 'bg-red-500' : pct >= 75 ? 'bg-orange-400' : pct >= 50 ? 'bg-yellow-400' : 'bg-emerald-400'
  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <span className={`text-xs font-mono w-8 text-right ${pct >= 90 ? 'text-red-300' : pct >= 75 ? 'text-orange-300' : pct >= 50 ? 'text-yellow-300' : 'text-slate-300'}`}>{pct}%</span>
    </div>
  )
}

const DiskRenderer: React.FC<{ stdout: string }> = ({ stdout }) => {
  const rows = parseDf(stdout)
  if (!rows.length) return <TerminalOut text={stdout} />
  return (
    <div className="space-y-2.5">
      {rows.map((r, i) => (
        <div key={i} className="bg-slate-900/60 rounded-lg p-3 space-y-1.5">
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-slate-500">💾</span>
              <span className="text-cyan-300 font-mono truncate max-w-[180px]" title={r.fs}>{r.fs}</span>
              <span className="text-slate-500 text-[10px] border border-slate-700 rounded px-1">{r.mount}</span>
            </div>
            <span className="text-slate-400 font-mono">{r.used} / {r.size}</span>
          </div>
          <BarFill pct={r.pct} />
          <div className="text-[10px] text-slate-600">Boş: {r.avail}</div>
        </div>
      ))}
    </div>
  )
}

const MemoryRenderer: React.FC<{ stdout: string }> = ({ stdout }) => {
  const rows = parseFree(stdout)
  if (!rows.length) return <TerminalOut text={stdout} />
  return (
    <div className="space-y-3">
      {rows.map((r, i) => (
        <div key={i} className="bg-slate-900/60 rounded-lg p-3 space-y-1.5">
          <div className="flex items-center justify-between text-xs">
            <span className="text-purple-300 font-semibold">{r.label === 'Mem' ? '🧠 RAM' : '💿 Swap'}</span>
            <span className="text-slate-400 font-mono">{r.used} / {r.total}</span>
          </div>
          <BarFill pct={r.pct} />
          <div className="text-[10px] text-slate-600">Boş: {r.free}</div>
        </div>
      ))}
      {/* vmstat summary */}
      {stdout.includes('---VMSTAT---') && (
        <div className="text-[10px] text-slate-500 font-mono border-t border-slate-700/50 pt-2 space-y-0.5">
          {stdout.split('---VMSTAT---')[1]?.trim().split('\n').slice(0, 8).map((l, i) => (
            <div key={i}>{l.trim()}</div>
          ))}
        </div>
      )}
    </div>
  )
}

const ProcessRenderer: React.FC<{ stdout: string; mode?: 'top' | 'ps' }> = ({ stdout, mode = 'ps' }) => {
  const rows = mode === 'top' ? parseTop(stdout) : parsePsAux(stdout)
  if (!rows.length) return <TerminalOut text={stdout} />
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-[10px] text-slate-500 uppercase">
          <tr className="border-b border-slate-700/50">
            <th className="text-left py-1.5 pr-3">PID</th>
            <th className="text-left py-1.5 pr-3">Kullanıcı</th>
            <th className="text-right py-1.5 pr-3">CPU%</th>
            <th className="text-right py-1.5 pr-3">MEM%</th>
            <th className="text-right py-1.5 pr-3">RSS</th>
            <th className="text-left py-1.5">Komut</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/30">
          {rows.map((r, i) => {
            const cpu = parseFloat(r.cpu)
            return (
              <tr key={i} className="hover:bg-slate-700/20">
                <td className="py-1 pr-3 text-slate-500 font-mono">{r.pid}</td>
                <td className="py-1 pr-3 text-cyan-300">{r.user}</td>
                <td className="py-1 pr-3 text-right font-mono">
                  <span className={cpu > 50 ? 'text-red-300' : cpu > 10 ? 'text-yellow-300' : 'text-slate-300'}>{r.cpu}</span>
                </td>
                <td className="py-1 pr-3 text-right font-mono text-slate-300">{r.mem}</td>
                <td className="py-1 pr-3 text-right font-mono text-slate-500">{r.rss}</td>
                <td className="py-1 text-emerald-300 font-mono truncate max-w-[200px]" title={r.cmd}>{r.cmd}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

const PortsRenderer: React.FC<{ stdout: string }> = ({ stdout }) => {
  const rows = parseSs(stdout)
  if (!rows.length) return <TerminalOut text={stdout} />
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-[10px] text-slate-500 uppercase">
          <tr className="border-b border-slate-700/50">
            <th className="text-left py-1.5 pr-3">Proto</th>
            <th className="text-left py-1.5 pr-3">Yerel</th>
            <th className="text-left py-1.5 pr-3">Uzak</th>
            <th className="text-left py-1.5">Süreç</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/30">
          {rows.map((r, i) => (
            <tr key={i} className="hover:bg-slate-700/20">
              <td className="py-1 pr-3">
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono ${r.proto.startsWith('tcp') ? 'bg-blue-500/20 text-blue-300' : 'bg-orange-500/20 text-orange-300'}`}>{r.proto.toUpperCase()}</span>
              </td>
              <td className="py-1 pr-3 font-mono text-cyan-300">{r.local}</td>
              <td className="py-1 pr-3 font-mono text-slate-500">{r.peer}</td>
              <td className="py-1 font-mono text-emerald-300 truncate max-w-[200px]">{r.process}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const DmesgRenderer: React.FC<{ stdout: string }> = ({ stdout }) => {
  const rows = parseDmesg(stdout)
  if (!rows.length) return <TerminalOut text={stdout} />
  return (
    <div className="space-y-0.5 font-mono text-xs">
      {rows.map((r, i) => (
        <div key={i} className={`flex gap-2 px-2 py-0.5 rounded ${r.level === 'error' ? 'bg-red-500/10 text-red-300' : r.level === 'warn' ? 'bg-yellow-500/10 text-yellow-300' : 'text-slate-400'}`}>
          <span className="text-slate-600 shrink-0 w-14 truncate">{r.time}</span>
          <span className="shrink-0">{r.level === 'error' ? '✕' : r.level === 'warn' ? '⚠' : '·'}</span>
          <span className="break-all">{r.msg}</span>
        </div>
      ))}
    </div>
  )
}

const LastLoginsRenderer: React.FC<{ stdout: string }> = ({ stdout }) => {
  const rows = parseLast(stdout)
  if (!rows.length) return <TerminalOut text={stdout} />
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-[10px] text-slate-500 uppercase">
          <tr className="border-b border-slate-700/50">
            <th className="text-left py-1.5 pr-3">Kullanıcı</th>
            <th className="text-left py-1.5 pr-3">Terminal</th>
            <th className="text-left py-1.5 pr-3">Kaynak</th>
            <th className="text-left py-1.5 pr-3">Zaman</th>
            <th className="text-left py-1.5">Durum</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/30">
          {rows.map((r, i) => (
            <tr key={i} className="hover:bg-slate-700/20">
              <td className="py-1 pr-3 text-cyan-300 font-medium">{r.user}</td>
              <td className="py-1 pr-3 font-mono text-slate-400">{r.term}</td>
              <td className="py-1 pr-3 font-mono text-slate-500">{r.host}</td>
              <td className="py-1 pr-3 text-slate-400">{r.time}</td>
              <td className="py-1">
                <span className={`px-1.5 py-0.5 rounded-full text-[10px] ${r.status === 'active' ? 'bg-green-500/20 text-green-300' : 'bg-slate-700 text-slate-400'}`}>{r.status === 'active' ? '● aktif' : 'çıktı'}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const ServicesRenderer: React.FC<{ stdout: string }> = ({ stdout }) => {
  const rows = parseServices(stdout)
  if (!rows.length) return <TerminalOut text={stdout} />
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-[10px] text-slate-500 uppercase">
          <tr className="border-b border-slate-700/50">
            <th className="text-left py-1.5 pr-3">Servis</th>
            <th className="text-left py-1.5 pr-3">Durum</th>
            <th className="text-left py-1.5 pr-3">Sub</th>
            <th className="text-left py-1.5">Açıklama</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/30">
          {rows.map((r, i) => (
            <tr key={i} className="hover:bg-slate-700/20">
              <td className="py-1 pr-3 text-cyan-300 font-mono truncate max-w-[160px]" title={r.name}>{r.name}</td>
              <td className="py-1 pr-3">
                <span className={`px-1.5 py-0.5 rounded-full text-[10px] ${r.active === 'active' ? 'bg-green-500/20 text-green-300' : 'bg-red-500/20 text-red-300'}`}>{r.active}</span>
              </td>
              <td className="py-1 pr-3 text-slate-500 text-[10px]">{r.sub}</td>
              <td className="py-1 text-slate-400 truncate max-w-[200px]">{r.desc}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const OsInfoRenderer: React.FC<{ stdout: string }> = ({ stdout }) => {
  const info = parseOsInfo(stdout)
  const important = ['PRETTY_NAME', 'NAME', 'VERSION', 'Kernel', 'Hostname', 'CPU', 'ID', 'VERSION_ID']
  const rows = important.filter(k => info[k]).map(k => ({ k, v: info[k] }))
  const extra = Object.entries(info).filter(([k]) => !important.includes(k) && !k.startsWith('---'))
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-1 gap-1.5">
        {rows.map(({ k, v }) => (
          <div key={k} className="flex gap-3 items-start bg-slate-900/60 rounded px-3 py-1.5">
            <span className="text-xs text-slate-500 w-28 shrink-0">{k}</span>
            <span className="text-xs text-emerald-300 font-mono break-all">{v}</span>
          </div>
        ))}
      </div>
      {extra.length > 0 && (
        <details className="mt-2">
          <summary className="text-[10px] text-slate-600 cursor-pointer">+ {extra.length} ek bilgi</summary>
          <div className="mt-1 space-y-0.5">
            {extra.map(([k, v]) => (
              <div key={k} className="flex gap-3 px-3 py-0.5">
                <span className="text-[10px] text-slate-600 w-28 shrink-0">{k}</span>
                <span className="text-[10px] text-slate-400 font-mono">{v}</span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}

const UptimeRenderer: React.FC<{ stdout: string }> = ({ stdout }) => {
  const line = trimLines(stdout).split('\n')[0]
  const loadMatch = stdout.match(/load average[s]?:\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/)
  const uptimeMatch = line.match(/up\s+([\d\s\w,]+?),\s+\d+ user/)
  const loads = loadMatch ? [loadMatch[1], loadMatch[2], loadMatch[3]] : []
  return (
    <div className="space-y-3">
      <div className="bg-slate-900/60 rounded-lg p-3">
        <div className="text-xs text-slate-500 mb-1">Uptime</div>
        <div className="text-lg font-mono text-cyan-300">{uptimeMatch?.[1]?.trim() || line}</div>
      </div>
      {loads.length > 0 && (
        <div className="grid grid-cols-3 gap-2">
          {['1dk', '5dk', '15dk'].map((lbl, i) => {
            const v = parseFloat(loads[i])
            return (
              <div key={i} className="bg-slate-900/60 rounded-lg p-2.5 text-center">
                <div className="text-xs text-slate-500 mb-0.5">Yük {lbl}</div>
                <div className={`text-xl font-bold ${v > 2 ? 'text-red-300' : v > 1 ? 'text-yellow-300' : 'text-emerald-300'}`}>{loads[i]}</div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

const TerminalOut: React.FC<{ text: string }> = ({ text }) => (
  <pre className="text-xs text-emerald-300/90 font-mono whitespace-pre-wrap leading-5 break-all">
    {trimLines(stripAnsi(text))}
  </pre>
)

// MCP tool content array renderer
const McpResultRenderer: React.FC<{ result: any }> = ({ result }) => {
  if (!result) return null
  // call_tool returns {content: [{type:'text', text:'...'}], ...}
  const content = result?.content ?? result?.result?.content
  if (Array.isArray(content)) {
    const texts = content.filter((c: any) => c?.type === 'text').map((c: any) => c.text).join('\n')
    return <TerminalOut text={texts || JSON.stringify(result, null, 2)} />
  }
  const text = result?.stdout || result?.result?.stdout || result?.result?.text
  if (typeof text === 'string') return <TerminalOut text={text} />
  return <TerminalOut text={JSON.stringify(result, null, 2)} />
}

// Smart dispatcher
const OutputRenderer: React.FC<{ toolName: string; result: any }> = ({ toolName, result }) => {
  if (!result) return null
  const stdout = result?.result?.stdout ?? result?.stdout ?? ''
  const ok = result?.ok !== false && (result?.result?.success !== false)

  if (!ok) {
    const err = result?.result?.stderr || result?.detail || 'Hata oluştu'
    return (
      <div className="flex gap-2 items-start text-red-300 bg-red-500/10 rounded-lg p-3 text-xs">
        <span className="shrink-0">✕</span><span>{err}</span>
      </div>
    )
  }

  // Builtin smart renderers
  if (toolName === 'builtin.disk') return <DiskRenderer stdout={stdout} />
  if (toolName === 'builtin.memory') return <MemoryRenderer stdout={stdout} />
  if (toolName === 'builtin.cpu_top') return <ProcessRenderer stdout={stdout} mode="top" />
  if (toolName === 'builtin.processes') return <ProcessRenderer stdout={stdout} mode="ps" />
  if (toolName === 'builtin.network_ports') return <PortsRenderer stdout={stdout} />
  if (toolName === 'builtin.dmesg_errors') return <DmesgRenderer stdout={stdout} />
  if (toolName === 'builtin.last_logins') return <LastLoginsRenderer stdout={stdout} />
  if (toolName === 'builtin.services') return <ServicesRenderer stdout={stdout} />
  if (toolName === 'builtin.os_info') return <OsInfoRenderer stdout={stdout} />
  if (toolName === 'builtin.uptime') return <UptimeRenderer stdout={stdout} />
  if (toolName.startsWith('builtin.')) return <TerminalOut text={stdout} />
  return <McpResultRenderer result={result?.result ?? result} />
}

// ─── Arg form ─────────────────────────────────────────────────────────────────
const ArgsForm: React.FC<{ tool: McpTool; args: Record<string, string>; onChange: (k: string, v: string) => void }> = ({ tool, args, onChange }) => {
  const props = tool.schema?.properties
  if (!props || Object.keys(props).length === 0) return null
  const required = tool.schema?.required || []
  return (
    <div className="mt-3 space-y-2">
      {Object.entries(props).map(([key, def]: [string, any]) => (
        <div key={key}>
          <label className="flex items-center gap-1 text-[11px] text-slate-400 mb-0.5">
            {key}
            {required.includes(key) && <span className="text-red-400">*</span>}
            {def.description && <span className="text-slate-600">— {def.description}</span>}
          </label>
          {def.type === 'boolean' ? (
            <select value={args[key] ?? ''} onChange={e => onChange(key, e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-white">
              <option value="">Seç...</option>
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
          ) : (
            <input type={def.type === 'integer' || def.type === 'number' ? 'number' : 'text'}
              value={args[key] ?? ''} onChange={e => onChange(key, e.target.value)}
              placeholder={def.default != null ? String(def.default) : `${key}...`}
              className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-white font-mono focus:border-blue-500 outline-none" />
          )}
        </div>
      ))}
    </div>
  )
}

// ─── Category config ──────────────────────────────────────────────────────────
const CAT_CONFIG: Record<string, { label: string; color: string }> = {
  system:   { label: 'Sistem',   color: 'text-cyan-300' },
  storage:  { label: 'Depolama', color: 'text-amber-300' },
  process:  { label: 'Süreçler', color: 'text-violet-300' },
  network:  { label: 'Ağ',       color: 'text-blue-300' },
  security: { label: 'Güvenlik', color: 'text-rose-300' },
  mcp:      { label: 'MCP',      color: 'text-emerald-300' },
}

// ─── Main page ────────────────────────────────────────────────────────────────
let _runId = 0

const McpTools: React.FC = () => {
  const [selectedServerId, setSelectedServerId] = useState<number | null>(null)
  const [selectedTool, setSelectedTool] = useState<McpTool | null>(null)
  const [args, setArgs] = useState<Record<string, string>>({})
  const [result, setResult] = useState<any>(null)
  const [rawMode, setRawMode] = useState(false)
  const [error, setError] = useState('')
  const [isRunning, setIsRunning] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [history, setHistory] = useState<RunRecord[]>([])
  const [histItem, setHistItem] = useState<RunRecord | null>(null)
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

  const selectedServer = useMemo(() => servers.find(s => s.id === selectedServerId) ?? null, [servers, selectedServerId])
  const tools: McpTool[] = toolsData?.tools || []
  const toolGroups = useMemo(() => {
    const g: Record<string, McpTool[]> = {}
    tools.forEach(t => { const c = t.category || 'mcp'; g[c] = [...(g[c] || []), t] })
    return g
  }, [tools])

  const setArg = useCallback((k: string, v: string) => setArgs(prev => ({ ...prev, [k]: v })), [])

  const runTool = async () => {
    if (!selectedServer || !selectedTool) return
    setIsRunning(true); setError(''); setResult(null); setHistItem(null); setElapsed(0)
    const start = Date.now()
    timerRef.current = setInterval(() => setElapsed(Date.now() - start), 100)
    try {
      const parsedArgs: Record<string, any> = {}
      if (selectedTool.schema?.properties) {
        Object.entries(args).forEach(([k, v]) => {
          const def = selectedTool.schema!.properties![k]
          parsedArgs[k] = def?.type === 'integer' ? parseInt(v) :
                          def?.type === 'number'  ? parseFloat(v) :
                          def?.type === 'boolean' ? v === 'true' : v
        })
      }
      const r = await fetch(`${API_BASE_URL}/mcp/call-tool`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool_name: selectedTool.name, host: selectedServer.ip_address || selectedServer.hostname, arguments: parsedArgs })
      })
      const body = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(body?.detail || 'Araç çalıştırılamadı')
      setResult(body)
      const rec: RunRecord = { id: ++_runId, server: selectedServer.name, tool: selectedTool.name, icon: selectedTool.icon || '🔌', ok: body?.ok !== false, elapsed: Date.now() - start, result: body, ts: new Date() }
      setHistory(prev => [rec, ...prev].slice(0, 12))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Bilinmeyen hata')
    } finally {
      clearInterval(timerRef.current); setIsRunning(false)
      setElapsed(Date.now() - start)
    }
  }

  const displayResult = histItem?.result ?? result
  const displayTool = histItem?.tool ?? selectedTool?.name ?? ''

  return (
    <div className="h-full flex gap-4 overflow-hidden" style={{ minHeight: 'calc(100vh - 112px)' }}>

      {/* ── Left panel ─────────────────────────────────────────────── */}
      <div className="w-72 flex flex-col gap-3 overflow-y-auto shrink-0 pr-1">

        {/* Server selector */}
        <div className="bg-slate-800/70 border border-slate-700 rounded-xl p-3">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Sunucu</div>
          {serversLoading ? (
            <div className="text-xs text-slate-500 animate-pulse">Yükleniyor...</div>
          ) : (
            <div className="space-y-1">
              {servers.map(s => (
                <button key={s.id} onClick={() => setSelectedServerId(s.id)}
                  className={`w-full text-left px-2.5 py-2 rounded-lg transition-all text-xs ${selectedServerId === s.id ? 'bg-blue-600/30 border border-blue-500/40 text-white' : 'hover:bg-slate-700/50 text-slate-300 border border-transparent'}`}>
                  <div className="flex items-center gap-2">
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${s.status === 'online' ? 'bg-emerald-400' : 'bg-red-400'}`} />
                    <span className="font-medium truncate">{s.name}</span>
                    {s.ai_ready && <span className="text-[9px] text-cyan-400 shrink-0">AI</span>}
                  </div>
                  <div className="text-slate-500 font-mono ml-3.5 text-[10px]">{s.ip_address}</div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Tool list */}
        <div className="bg-slate-800/70 border border-slate-700 rounded-xl p-3 flex-1">
          <div className="flex items-center justify-between mb-2">
            <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Araçlar</div>
            <button onClick={() => void refetchTools()} className="text-[10px] text-slate-500 hover:text-slate-300 border border-slate-700 rounded px-1.5 py-0.5">↺</button>
          </div>
          {toolsLoading ? (
            <div className="text-xs text-slate-500 animate-pulse">Yükleniyor...</div>
          ) : (
            <div className="space-y-3">
              {Object.entries(toolGroups).map(([cat, catTools]) => (
                <div key={cat}>
                  <div className={`text-[10px] font-semibold uppercase tracking-wider mb-1 ${CAT_CONFIG[cat]?.color || 'text-slate-400'}`}>
                    {CAT_CONFIG[cat]?.label || cat}
                  </div>
                  <div className="space-y-0.5">
                    {catTools.map(t => (
                      <button key={t.name}
                        onClick={() => { setSelectedTool(t); setArgs({}); setResult(null); setHistItem(null); setError('') }}
                        className={`w-full text-left px-2.5 py-1.5 rounded-lg transition-all text-xs flex items-start gap-2 ${selectedTool?.name === t.name ? 'bg-blue-600/30 border border-blue-500/40 text-white' : 'hover:bg-slate-700/50 text-slate-300 border border-transparent'}`}>
                        <span className="text-sm shrink-0 leading-none mt-0.5">{t.icon || '🔌'}</span>
                        <div className="min-w-0">
                          <div className="font-mono truncate text-[11px]">{t.name.replace('builtin.', '')}</div>
                          {t.description && <div className="text-slate-500 text-[10px] leading-tight truncate">{t.description}</div>}
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
          {toolsData?.warning && (
            <div className="mt-2 text-[10px] text-amber-400/80 border-t border-slate-700/50 pt-2">{toolsData.warning}</div>
          )}
        </div>
      </div>

      {/* ── Right panel ───────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col gap-3 overflow-hidden min-w-0">

        {/* Control bar */}
        <div className="bg-slate-800/70 border border-slate-700 rounded-xl p-3">
          {selectedTool ? (
            <div className="space-y-2">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-2 min-w-0">
                  <span className="text-2xl shrink-0">{selectedTool.icon}</span>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-white">{selectedTool.name.replace('builtin.', '')}</div>
                    <div className="text-xs text-slate-400">{selectedTool.description}</div>
                    {selectedServer && <div className="text-[11px] text-cyan-400/80 mt-0.5 font-mono">{selectedServer.name} ({selectedServer.ip_address})</div>}
                  </div>
                </div>
                <button onClick={runTool}
                  disabled={!selectedServer || !selectedTool || isRunning}
                  className="shrink-0 flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium transition-all">
                  {isRunning ? (
                    <><span className="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" /> {(elapsed / 1000).toFixed(1)}s</>
                  ) : '▶ Çalıştır'}
                </button>
              </div>
              {!selectedServer && <div className="text-xs text-amber-400">⚠ Sol panelden sunucu seçin</div>}
              <ArgsForm tool={selectedTool} args={args} onChange={setArg} />
            </div>
          ) : (
            <div className="text-xs text-slate-500 py-1">Sol panelden bir araç seçin</div>
          )}
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3 text-red-300 text-xs flex gap-2">
            <span>✕</span><span>{error}</span>
          </div>
        )}

        {/* Output */}
        {displayResult && (
          <div className="flex-1 bg-slate-800/70 border border-slate-700 rounded-xl overflow-hidden flex flex-col min-h-0">
            {/* Output header */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-slate-700/70 shrink-0">
              <div className="flex items-center gap-3">
                <span className={`flex items-center gap-1.5 text-xs font-medium ${displayResult?.ok !== false ? 'text-emerald-300' : 'text-red-300'}`}>
                  <span>{displayResult?.ok !== false ? '✓' : '✕'}</span>
                  <span>{displayResult?.ok !== false ? 'Başarılı' : 'Hata'}</span>
                </span>
                {histItem && <span className="text-[10px] text-slate-500 border border-slate-700 rounded px-1.5 py-0.5">Geçmiş: {histItem.server} · {histItem.tool.replace('builtin.', '')}</span>}
                {!histItem && elapsed > 0 && <span className="text-[10px] text-slate-500">{(elapsed / 1000).toFixed(2)}s</span>}
                {displayTool.startsWith('builtin.') && (
                  <span className="text-[10px] text-slate-500 font-mono border border-slate-700 rounded px-1.5 py-0.5">{displayResult?.result?.command}</span>
                )}
              </div>
              <div className="flex items-center gap-1.5">
                <button onClick={() => setRawMode(false)}
                  className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${!rawMode ? 'bg-blue-600/30 border-blue-500/40 text-blue-200' : 'border-slate-700 text-slate-500 hover:text-slate-300'}`}>
                  Görsel
                </button>
                <button onClick={() => setRawMode(true)}
                  className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${rawMode ? 'bg-blue-600/30 border-blue-500/40 text-blue-200' : 'border-slate-700 text-slate-500 hover:text-slate-300'}`}>
                  Ham
                </button>
              </div>
            </div>

            {/* Output body */}
            <div className="flex-1 overflow-y-auto p-4 bg-slate-950/40">
              {rawMode ? (
                <TerminalOut text={
                  displayResult?.result?.stdout
                  ?? displayResult?.result?.stderr
                  ?? JSON.stringify(displayResult, null, 2)
                } />
              ) : (
                <OutputRenderer toolName={displayTool} result={displayResult} />
              )}
            </div>
          </div>
        )}

        {/* History */}
        {history.length > 0 && (
          <div className="bg-slate-800/50 border border-slate-700/60 rounded-xl p-3 shrink-0">
            <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">Son Çalıştırmalar</div>
            <div className="flex gap-1.5 flex-wrap">
              {history.map(h => (
                <button key={h.id} onClick={() => { setHistItem(h); setRawMode(false) }}
                  className={`flex items-center gap-1.5 px-2 py-1 rounded-lg text-[11px] border transition-all ${histItem?.id === h.id ? 'bg-slate-700 border-slate-500 text-white' : 'border-slate-700/60 text-slate-400 hover:border-slate-600 hover:text-slate-200'}`}>
                  <span>{h.icon}</span>
                  <span className="font-mono">{h.tool.replace('builtin.', '')}</span>
                  <span className="text-slate-600">@{h.server}</span>
                  <span className={`w-1.5 h-1.5 rounded-full ${h.ok ? 'bg-emerald-400' : 'bg-red-400'}`} />
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Empty state */}
        {!displayResult && !error && (
          <div className="flex-1 flex flex-col items-center justify-center text-center gap-3">
            <div className="text-5xl opacity-20">🔧</div>
            <div className="text-sm text-slate-600">Sunucu ve araç seçip <span className="text-slate-500">▶ Çalıştır</span>'a tıklayın</div>
          </div>
        )}
      </div>
    </div>
  )
}

export default McpTools
