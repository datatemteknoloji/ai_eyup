/**
 * Centrify / Delinea Server Suite — Zone Yönetim Sayfası
 *
 * Centrify Access Manager tarzı hiyerarşik ağaç.
 * Sol panel: daraltılabilir çekmece — zone/computer/role/command tree + global arama
 * Sağ panel: seçili düğümün içeriği
 * Sağ tık menüleri ile CRUD işlemleri.
 * RoleDialog: 5 tab (General, System Rights, Authentication, Audit, Custom Attributes)
 * AssignRoleDialog: Filtrelenebilir data-grid rol seçimi + zone/computer scope ayrımı
 */
import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  KeyRound, ChevronRight, ChevronDown, FolderTree, Shield,
  Terminal, Users, Monitor, User, RefreshCw, AlertTriangle,
  Loader2, Info, Search, Folder,
  PanelLeftClose, PanelLeft, XCircle, CheckCircle2,
  Plus, Copy, ClipboardPaste, Pencil, Trash2, FileDown, Link2, Unlink, Send,
} from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import { useT } from '../../i18n/LocaleProvider'
import type { TranslationKey } from '../../i18n/messages'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { chatMarkdownComponents, chatResponseBody } from '../../components/chatMarkdown'

// ── Tipler ───────────────────────────────────────────────────

interface Zone {
  id: number; ad_guid: string; ad_dn: string; name: string
  zone_type: string; parent_zone_id: number | null
  description: string | null; management_state: string
}
interface Role {
  id: number; ad_guid: string; name: string; description: string | null
  is_system_role: boolean; management_state: string; command_count: number
  zone_name?: string; zone_dn?: string
  allow_local_accounts?: boolean
  password_login_allowed?: boolean; sso_login_allowed?: boolean
  ad_disabled_sudo_cron?: boolean; non_restricted_shell?: boolean; user_visible?: boolean
  console_login_allowed?: boolean; remote_login_allowed?: boolean; powershell_remote_allowed?: boolean
  rescue_login_allowed?: boolean; require_mfa?: boolean
  audit_level?: string; custom_attributes?: { name: string; value: string }[] | null
}
interface Command {
  id: number; ad_guid: string; name: string; command_path: string | null
  match_type: string | null; run_as_user: string | null; auth_type: string | null
  description: string | null; management_state: string
}
interface Computer {
  id: number; name: string; fqdn: string; os_type: string
  agent_version: string; zone_id: number; management_state: string
}
interface CircuitStatus { open: boolean; fail_count: number; ttl_seconds: number | null; redis_available: boolean }
interface SyncStatus { synced: boolean; zone_count: number; last_synced_at: string | null }
interface Config {
  id: number; label: string; winrm_host: string; winrm_port: number
  winrm_https: boolean; service_account: string; sync_interval_minutes: number
  sync_enabled: boolean; enabled: boolean
}

type VNodeType =
  | 'zone' | 'computers' | 'computer_item'
  | 'windows_data' | 'unix_data' | 'users' | 'groups' | 'local_users' | 'local_groups'
  | 'authorization' | 'role_assignments' | 'computer_roles'
  | 'role_definitions' | 'unix_right_defs' | 'pam_access' | 'commands' | 'ssh_rights'
  | 'windows_right_defs' | 'child_zones'

interface TreeSelection {
  zoneId: number; nodeType: VNodeType; zoneName: string; itemId?: number; itemName?: string
}

interface CtxMenu {
  x: number; y: number; zoneId: number; nodeType: VNodeType
  item?: any; computerId?: number
}

interface ClipItem {
  kind: 'role' | 'command'
  sourceZoneId: number
  item: Role | Command
}

interface SearchResult {
  zones: { id: number; name: string; zone_type: string; path: string }[]
  computers: { id: number; name: string; fqdn: string; os_type: string; agent_version: string; zone_id: number; zone_path: string }[]
  users: { id: number; user_name: string; uid: number; home_dir: string; shell: string; zone_id: number; zone_path: string }[]
}

// ── API ──────────────────────────────────────────────────────

const api = (p: string) => `${API_BASE_URL}/centrify-mgmt${p}`
const token = () => localStorage.getItem('auth_token') || localStorage.getItem('token')
const hdrs = () => ({ Authorization: `Bearer ${token()}`, 'Content-Type': 'application/json' })

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(api(path), { headers: { Authorization: `Bearer ${token()}` } })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

// ── Ağaç yardımcıları ────────────────────────────────────────

function rootZones(zones: Zone[]) { return zones.filter(z => z.parent_zone_id === null) }
function childZones(zones: Zone[], pid: number) { return zones.filter(z => z.parent_zone_id === pid) }

const ICON: Record<string, React.ReactNode> = {
  zone: <FolderTree size={14} />, computers: <Monitor size={14} />, computer_item: <Monitor size={13} />,
  windows_data: <Folder size={14} />, unix_data: <Folder size={14} />,
  users: <User size={14} />, groups: <Users size={14} />,
  local_users: <User size={14} />, local_groups: <Users size={14} />,
  authorization: <Shield size={14} />, role_assignments: <Users size={14} />,
  computer_roles: <Monitor size={14} />, role_definitions: <Shield size={14} />,
  unix_right_defs: <Folder size={14} />, pam_access: <Folder size={14} />,
  commands: <Terminal size={14} />, ssh_rights: <Shield size={14} />,
  windows_right_defs: <Folder size={14} />, child_zones: <FolderTree size={14} />,
}

const LABEL_KEY: Record<VNodeType, TranslationKey> = {
  zone: 'cz_computers', computers: 'cz_computers', computer_item: 'cz_computers',
  windows_data: 'cz_windows_data', unix_data: 'cz_unix_data',
  users: 'cz_users', groups: 'cz_groups', local_users: 'cz_local_users', local_groups: 'cz_local_groups',
  authorization: 'cz_authorization', role_assignments: 'cz_role_assignments',
  computer_roles: 'cz_computer_roles', role_definitions: 'cz_role_definitions',
  unix_right_defs: 'cz_unix_right_defs', pam_access: 'cz_pam_access',
  commands: 'cz_commands', ssh_rights: 'cz_ssh_rights',
  windows_right_defs: 'cz_windows_right_defs', child_zones: 'cz_child_zones',
}

// ── Expanded state yönetimi ──────────────────────────────────

type ExpandedMap = Record<string, boolean>

function eKey(zoneId: number, nodeType: string, itemId?: number) {
  return `${zoneId}:${nodeType}${itemId ? `:${itemId}` : ''}`
}

// ── VirtualNode bileşeni ─────────────────────────────────────

const VNode: React.FC<{
  label: string; nodeType: VNodeType; zoneId: number; zoneName: string; depth: number
  sel: TreeSelection | null; onSel: (s: TreeSelection) => void
  children?: React.ReactNode; defaultOpen?: boolean; itemId?: number; itemName?: string
  onCtx?: (e: React.MouseEvent) => void
  expanded: ExpandedMap; setExpanded: React.Dispatch<React.SetStateAction<ExpandedMap>>
}> = ({ label, nodeType, zoneId, zoneName, depth, sel, onSel, children, defaultOpen, itemId, itemName, onCtx, expanded, setExpanded }) => {
  const k = eKey(zoneId, nodeType, itemId)
  const isOpen = expanded[k] ?? (defaultOpen || false)
  const hasKids = !!children
  const isSel = sel?.zoneId === zoneId && sel?.nodeType === nodeType && sel?.itemId === itemId

  const toggle = () => setExpanded(prev => ({ ...prev, [k]: !isOpen }))
  const openKids = () => setExpanded(prev => ({ ...prev, [k]: true }))

  return (
    <div>
      <button
        onClick={() => { onSel({ zoneId, nodeType, zoneName, itemId, itemName }) }}
        onDoubleClick={() => { onSel({ zoneId, nodeType, zoneName, itemId, itemName }); if (hasKids) openKids() }}
        onContextMenu={e => { e.preventDefault(); onCtx?.(e) }}
        className={`w-full flex items-center gap-1 px-1.5 py-[3px] text-[12.5px] rounded transition-colors
          ${isSel ? 'bg-blue-600/20 text-blue-400 font-medium' : 'text-slate-300 hover:bg-slate-700/40 hover:text-slate-100'}`}
        style={{ paddingLeft: `${depth * 14 + 6}px` }}
      >
        {hasKids ? (
          <span
            role="button"
            onClick={e => { e.stopPropagation(); toggle() }}
            className="shrink-0 text-slate-500 hover:text-slate-300"
          >
            {isOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
          </span>
        ) : <span className="w-[11px] shrink-0" />}
        <span className={`shrink-0 ${isSel ? 'text-blue-400' : 'text-slate-500'}`}>{ICON[nodeType]}</span>
        <span className="truncate">{label}</span>
      </button>
      {isOpen && hasKids && <div>{children}</div>}
    </div>
  )
}

// ── Computer'ları ağaçta gösteren bileşen ────────────────────

const ComputerTreeNodes: React.FC<{
  zoneId: number; zoneName: string; depth: number
  sel: TreeSelection | null; onSel: (s: TreeSelection) => void
  onCtx: (e: React.MouseEvent, zoneId: number, nodeType: VNodeType, item?: any, computerId?: number) => void
  expanded: ExpandedMap; setExpanded: React.Dispatch<React.SetStateAction<ExpandedMap>>
}> = ({ zoneId, zoneName, depth, sel, onSel, onCtx, expanded, setExpanded }) => {
  const { data: computers = [] } = useQuery<Computer[]>({
    queryKey: ['centrify-computers', zoneId],
    queryFn: () => fetchJson(`/zones/${zoneId}/computers`),
  })

  return (
    <>
      {computers.map(c => (
        <VNode key={c.id} label={c.name} nodeType="computer_item" zoneId={zoneId} zoneName={zoneName}
          depth={depth} sel={sel} onSel={onSel} itemId={c.id} itemName={c.name}
          onCtx={e => onCtx(e, zoneId, 'computer_item', c)}
          expanded={expanded} setExpanded={setExpanded}>
          <VNode label="UNIX Data" nodeType="unix_data" zoneId={zoneId} zoneName={zoneName}
            depth={depth + 1} sel={sel} onSel={onSel} itemId={c.id} expanded={expanded} setExpanded={setExpanded} />
          <VNode label="Role Assignments" nodeType="role_assignments" zoneId={zoneId} zoneName={zoneName}
            depth={depth + 1} sel={sel} onSel={onSel} itemId={c.id} itemName={c.name}
            onCtx={e => onCtx(e, zoneId, 'role_assignments', undefined, c.id)}
            expanded={expanded} setExpanded={setExpanded} />
        </VNode>
      ))}
    </>
  )
}

// ── Zone ağaç düğümü (recursive) ─────────────────────────────

const ZoneTreeNode: React.FC<{
  zone: Zone; allZones: Zone[]; sel: TreeSelection | null
  onSel: (s: TreeSelection) => void; depth: number
  t: (k: TranslationKey) => string
  onCtx: (e: React.MouseEvent, zoneId: number, nodeType: VNodeType, item?: any, computerId?: number) => void
  expanded: ExpandedMap; setExpanded: React.Dispatch<React.SetStateAction<ExpandedMap>>
}> = ({ zone, allZones, sel, onSel, depth, t, onCtx, expanded, setExpanded }) => {
  const k = eKey(zone.id, 'zone')
  const isOpen = expanded[k] ?? (depth < 1)
  const kids = childZones(allZones, zone.id)
  const isSel = sel?.zoneId === zone.id && sel?.nodeType === 'zone'

  const toggle = () => setExpanded(prev => ({ ...prev, [k]: !isOpen }))

  return (
    <div>
      <button
        onClick={() => { onSel({ zoneId: zone.id, nodeType: 'zone', zoneName: zone.name }); toggle() }}
        onContextMenu={e => { e.preventDefault(); onCtx(e, zone.id, 'zone') }}
        className={`w-full flex items-center gap-1 px-1.5 py-[3px] text-[12.5px] rounded transition-colors
          ${isSel ? 'bg-blue-600/20 text-blue-400 font-medium' : 'text-slate-300 hover:bg-slate-700/40 hover:text-slate-100'}`}
        style={{ paddingLeft: `${depth * 14 + 6}px` }}
      >
        {isOpen ? <ChevronDown size={11} className="text-slate-500 shrink-0" />
                 : <ChevronRight size={11} className="text-slate-500 shrink-0" />}
        <span className={`shrink-0 ${isSel ? 'text-blue-400' : 'text-yellow-500/70'}`}><FolderTree size={14} /></span>
        <span className="truncate font-medium">{zone.name}</span>
      </button>

      {isOpen && (
        <>
          <VNode label={t('cz_computers')} nodeType="computers" zoneId={zone.id} zoneName={zone.name}
            depth={depth + 1} sel={sel} onSel={onSel}
            onCtx={e => onCtx(e, zone.id, 'computers')}
            expanded={expanded} setExpanded={setExpanded}>
            <ComputerTreeNodes zoneId={zone.id} zoneName={zone.name} depth={depth + 2}
              sel={sel} onSel={onSel} onCtx={onCtx}
              expanded={expanded} setExpanded={setExpanded} />
          </VNode>

          <VNode label={t('cz_windows_data')} nodeType="windows_data" zoneId={zone.id} zoneName={zone.name}
            depth={depth + 1} sel={sel} onSel={onSel} expanded={expanded} setExpanded={setExpanded} />

          <VNode label={t('cz_unix_data')} nodeType="unix_data" zoneId={zone.id} zoneName={zone.name}
            depth={depth + 1} sel={sel} onSel={onSel} expanded={expanded} setExpanded={setExpanded}>
            <VNode label={t('cz_users')} nodeType="users" zoneId={zone.id} zoneName={zone.name}
              depth={depth + 2} sel={sel} onSel={onSel} expanded={expanded} setExpanded={setExpanded} />
            <VNode label={t('cz_groups')} nodeType="groups" zoneId={zone.id} zoneName={zone.name}
              depth={depth + 2} sel={sel} onSel={onSel} expanded={expanded} setExpanded={setExpanded} />
            <VNode label={t('cz_local_users')} nodeType="local_users" zoneId={zone.id} zoneName={zone.name}
              depth={depth + 2} sel={sel} onSel={onSel} expanded={expanded} setExpanded={setExpanded} />
            <VNode label={t('cz_local_groups')} nodeType="local_groups" zoneId={zone.id} zoneName={zone.name}
              depth={depth + 2} sel={sel} onSel={onSel} expanded={expanded} setExpanded={setExpanded} />
          </VNode>

          <VNode label={t('cz_authorization')} nodeType="authorization" zoneId={zone.id} zoneName={zone.name}
            depth={depth + 1} sel={sel} onSel={onSel}
            onCtx={e => onCtx(e, zone.id, 'authorization')}
            expanded={expanded} setExpanded={setExpanded}>
            <VNode label={t('cz_role_assignments')} nodeType="role_assignments" zoneId={zone.id} zoneName={zone.name}
              depth={depth + 2} sel={sel} onSel={onSel}
              onCtx={e => onCtx(e, zone.id, 'role_assignments')}
              expanded={expanded} setExpanded={setExpanded} />
            <VNode label={t('cz_computer_roles')} nodeType="computer_roles" zoneId={zone.id} zoneName={zone.name}
              depth={depth + 2} sel={sel} onSel={onSel} expanded={expanded} setExpanded={setExpanded} />
            <VNode label={t('cz_role_definitions')} nodeType="role_definitions" zoneId={zone.id} zoneName={zone.name}
              depth={depth + 2} sel={sel} onSel={onSel}
              onCtx={e => onCtx(e, zone.id, 'role_definitions')}
              expanded={expanded} setExpanded={setExpanded} />
            <VNode label={t('cz_windows_right_defs')} nodeType="windows_right_defs" zoneId={zone.id} zoneName={zone.name}
              depth={depth + 2} sel={sel} onSel={onSel} expanded={expanded} setExpanded={setExpanded} />
            <VNode label={t('cz_unix_right_defs')} nodeType="unix_right_defs" zoneId={zone.id} zoneName={zone.name}
              depth={depth + 2} sel={sel} onSel={onSel} expanded={expanded} setExpanded={setExpanded}>
              <VNode label={t('cz_pam_access')} nodeType="pam_access" zoneId={zone.id} zoneName={zone.name}
                depth={depth + 3} sel={sel} onSel={onSel} expanded={expanded} setExpanded={setExpanded} />
              <VNode label={t('cz_commands')} nodeType="commands" zoneId={zone.id} zoneName={zone.name}
                depth={depth + 3} sel={sel} onSel={onSel}
                onCtx={e => onCtx(e, zone.id, 'commands')}
                expanded={expanded} setExpanded={setExpanded} />
              <VNode label={t('cz_ssh_rights')} nodeType="ssh_rights" zoneId={zone.id} zoneName={zone.name}
                depth={depth + 3} sel={sel} onSel={onSel} expanded={expanded} setExpanded={setExpanded} />
            </VNode>
          </VNode>

          {kids.length > 0 && (
            <VNode label={t('cz_child_zones')} nodeType="child_zones" zoneId={zone.id} zoneName={zone.name}
              depth={depth + 1} sel={sel} onSel={onSel} defaultOpen expanded={expanded} setExpanded={setExpanded}>
              {kids.map(cz => (
                <ZoneTreeNode key={cz.id} zone={cz} allZones={allZones} sel={sel}
                  onSel={onSel} depth={depth + 2} t={t} onCtx={onCtx}
                  expanded={expanded} setExpanded={setExpanded} />
              ))}
            </VNode>
          )}
        </>
      )}
    </div>
  )
}

// ── Context menü ─────────────────────────────────────────────

const ContextMenu: React.FC<{
  ctx: CtxMenu; t: (k: TranslationKey) => string
  clipboard: ClipItem | null
  onAction: (action: string) => void; onClose: () => void
}> = ({ ctx, t, clipboard, onAction, onClose }) => {
  const items: { key: string; label: string; icon: React.ReactNode; danger?: boolean }[] = []

  if (ctx.nodeType === 'computer_item' && ctx.item) {
    items.push({ key: 'assign_role', label: t('cz_assign_role'), icon: <Plus size={13} /> })
  }
  if (ctx.nodeType === 'role_assignments') {
    items.push({ key: 'assign_role', label: t('cz_assign_role'), icon: <Plus size={13} /> })
  }
  if (ctx.nodeType === 'role_definitions') {
    items.push({ key: 'add_role', label: t('cz_add_role'), icon: <Plus size={13} /> })
  }
  if (ctx.nodeType === 'commands') {
    items.push({ key: 'new_command', label: t('cz_new_command'), icon: <Plus size={13} /> })
  }
  if (ctx.item && ctx.nodeType === 'commands') {
    items.push(
      { key: 'add_to_role', label: t('cz_add_cmd_to_role'), icon: <Link2 size={13} /> },
      { key: 'remove_from_role', label: t('cz_remove_cmd_from_role'), icon: <Unlink size={13} /> },
    )
  }
  if (ctx.item && (ctx.nodeType === 'role_definitions' || ctx.nodeType === 'commands')) {
    items.push(
      { key: 'edit', label: t('cz_edit'), icon: <Pencil size={13} /> },
      { key: 'copy', label: t('cz_copy'), icon: <Copy size={13} /> },
      { key: 'delete', label: t('cz_delete'), icon: <Trash2 size={13} />, danger: true },
    )
  }
  const canPasteRole = ctx.nodeType === 'role_definitions' && clipboard?.kind === 'role'
  const canPasteCmd = ctx.nodeType === 'commands' && clipboard?.kind === 'command'
  if (canPasteRole || canPasteCmd) {
    const clipName = clipboard?.item?.name || ''
    items.push({ key: 'paste', label: `${t('cz_paste')} (${clipName})`, icon: <ClipboardPaste size={13} /> })
  }

  items.push({ key: 'refresh', label: t('cz_refresh'), icon: <RefreshCw size={13} /> })

  if (['role_definitions', 'commands', 'role_assignments', 'computers'].includes(ctx.nodeType)) {
    items.push({ key: 'export', label: t('cz_export_list'), icon: <FileDown size={13} /> })
  }

  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div className="fixed z-50 bg-slate-800 border border-slate-600 rounded-lg shadow-2xl py-1 min-w-[180px]"
        style={{ left: Math.min(ctx.x, window.innerWidth - 220), top: Math.min(ctx.y, window.innerHeight - 250) }}>
        {items.map((it, i) => (
          <React.Fragment key={it.key}>
            {i > 0 && it.key === 'refresh' && <div className="border-t border-slate-700/50 my-0.5" />}
            <button onClick={() => { onAction(it.key); onClose() }}
              className={`w-full text-left px-3 py-1.5 text-[12.5px] flex items-center gap-2 hover:bg-slate-700/60 transition-colors
                ${it.danger ? 'text-red-400' : 'text-slate-300'}`}>
              {it.icon} {it.label}
            </button>
          </React.Fragment>
        ))}
      </div>
    </>
  )
}

// ── Tab bileşeni (dialog tab'ları için) ──────────────────────

const DialogTab: React.FC<{
  tabs: { key: string; label: string }[]; active: string; onChange: (k: string) => void
}> = ({ tabs, active, onChange }) => (
  <div className="flex border-b border-slate-700/50 mb-4">
    {tabs.map(tab => (
      <button key={tab.key} onClick={() => onChange(tab.key)}
        className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors
          ${active === tab.key
            ? 'border-blue-500 text-blue-400'
            : 'border-transparent text-slate-400 hover:text-slate-200 hover:border-slate-500'}`}>
        {tab.label}
      </button>
    ))}
  </div>
)

// ── Checkbox bileşeni ────────────────────────────────────────

const Chk: React.FC<{ checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }> = ({ checked, onChange, label, disabled }) => (
  <label className={`flex items-start gap-2 py-0.5 ${disabled ? 'opacity-50' : 'cursor-pointer'}`}>
    <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} disabled={disabled}
      className="mt-0.5 rounded border-slate-600 bg-slate-900 text-blue-500 focus:ring-blue-500/30" />
    <span className="text-xs text-slate-300 leading-relaxed">{label}</span>
  </label>
)

// ── Create/Edit Role diyaloğu (5 tab — Centrify uyumlu) ──────

const RoleDialog: React.FC<{
  zoneId: number; role?: Role | null; mode: 'create' | 'edit' | 'copy'
  onClose: () => void; onDone: () => void
}> = ({ zoneId, role, mode, onClose, onDone }) => {
  const t = useT()
  const [tab, setTab] = useState('general')
  const [name, setName] = useState(mode === 'copy' ? `${role?.name || ''}-copy` : (role?.name || ''))
  const [desc, setDesc] = useState(role?.description || '')
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  // General
  const [allowLocal, setAllowLocal] = useState(role?.allow_local_accounts || false)

  // System Rights — UNIX
  const [passwordLogin, setPasswordLogin] = useState(role?.password_login_allowed || false)
  const [ssoLogin, setSsoLogin] = useState(role?.sso_login_allowed || false)
  const [adDisabledSudo, setAdDisabledSudo] = useState(role?.ad_disabled_sudo_cron || false)
  const [nonRestrictedShell, setNonRestrictedShell] = useState(role?.non_restricted_shell || false)
  const [userVisible, setUserVisible] = useState(role?.user_visible !== false)
  // System Rights — Windows
  const [consoleLogin, setConsoleLogin] = useState(role?.console_login_allowed || false)
  const [remoteLogin, setRemoteLogin] = useState(role?.remote_login_allowed || false)
  const [powershellRemote, setPowershellRemote] = useState(role?.powershell_remote_allowed || false)
  // Rescue
  const [rescueLogin, setRescueLogin] = useState(role?.rescue_login_allowed || false)

  // Authentication
  const [requireMfa, setRequireMfa] = useState(role?.require_mfa || false)

  // Audit
  const [auditLevel, setAuditLevel] = useState(role?.audit_level || 'if_possible')

  // Custom Attributes
  const [attrs, setAttrs] = useState<{ name: string; value: string }[]>(role?.custom_attributes || [])
  const [newAttrName, setNewAttrName] = useState('')
  const [newAttrValue, setNewAttrValue] = useState('')

  const tabs = [
    { key: 'general', label: t('cz_tab_general') },
    { key: 'system_rights', label: t('cz_tab_system_rights') },
    { key: 'authentication', label: t('cz_tab_authentication') },
    { key: 'audit', label: t('cz_tab_audit') },
    { key: 'custom_attrs', label: t('cz_tab_custom_attrs') },
  ]

  const doSave = async () => {
    setSaving(true)
    setError('')
    const res = await fetch(api('/operations'), {
      method: 'POST', headers: hdrs(),
      body: JSON.stringify({
        operation_type: mode === 'create' ? 'create_role' : mode === 'copy' ? 'clone_role' : 'update_role',
        zone_id: zoneId,
        desired_state: {
          name, description: desc, source_role_name: role?.name,
          allow_local_accounts: allowLocal,
          password_login_allowed: passwordLogin, sso_login_allowed: ssoLogin,
          ad_disabled_sudo_cron: adDisabledSudo, non_restricted_shell: nonRestrictedShell,
          user_visible: userVisible,
          console_login_allowed: consoleLogin, remote_login_allowed: remoteLogin,
          powershell_remote_allowed: powershellRemote, rescue_login_allowed: rescueLogin,
          require_mfa: requireMfa, audit_level: auditLevel,
          custom_attributes: attrs.length > 0 ? attrs : null,
        },
        reason: reason || `${name} — ${mode}`,
      }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      setError(typeof body.detail === 'string' ? body.detail : `İşlem oluşturulamadı (${res.status})`)
      setSaving(false)
      return
    }
    setSaving(false); onDone(); onClose()
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 w-[540px] max-h-[85vh] flex flex-col shadow-2xl"
        onClick={e => e.stopPropagation()}>
        <h3 className="text-sm font-semibold text-slate-100 mb-3 flex items-center gap-2">
          <Shield size={16} className="text-blue-400" />
          {mode === 'create' ? t('cz_create_role') : mode === 'copy' ? t('cz_copy') : t('cz_edit')}
        </h3>

        <DialogTab tabs={tabs} active={tab} onChange={setTab} />

        <div className="flex-1 overflow-y-auto min-h-[280px]">
          {/* General */}
          {tab === 'general' && (
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-slate-400 mb-1">{t('cz_role_name')}</label>
                <input className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:border-blue-500 outline-none"
                  value={name} onChange={e => setName(e.target.value)} autoFocus />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">{t('cz_role_desc')}</label>
                <textarea className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:border-blue-500 outline-none resize-none h-20"
                  value={desc} onChange={e => setDesc(e.target.value)} />
              </div>
              <div className="border border-slate-700/50 rounded-lg p-3">
                <Chk checked={allowLocal} onChange={setAllowLocal} label={t('cz_allow_local_accounts')} />
                <p className="text-[10px] text-slate-500 ml-5 mt-1 leading-relaxed">{t('cz_allow_local_accounts_warn')}</p>
              </div>
              <button className="text-xs text-blue-400 hover:text-blue-300 border border-slate-700 rounded px-3 py-1.5">
                {t('cz_available_times')}
              </button>
            </div>
          )}

          {/* System Rights */}
          {tab === 'system_rights' && (
            <div className="space-y-4">
              <p className="text-xs text-slate-400">System rights granted by this role:</p>

              <fieldset className="border border-slate-700/50 rounded-lg p-3">
                <legend className="text-xs font-medium text-slate-300 px-1">{t('cz_unix_rights')}</legend>
                <div className="space-y-1.5 mt-1">
                  <Chk checked={passwordLogin} onChange={setPasswordLogin} label={t('cz_password_login')} />
                  <Chk checked={ssoLogin} onChange={setSsoLogin} label={t('cz_sso_login')} />
                  <Chk checked={adDisabledSudo} onChange={setAdDisabledSudo} label={t('cz_ad_disabled_sudo')} />
                  <Chk checked={nonRestrictedShell} onChange={setNonRestrictedShell} label={t('cz_non_restricted_shell')} />
                  <Chk checked={userVisible} onChange={setUserVisible} label={t('cz_user_visible')} />
                </div>
              </fieldset>

              <fieldset className="border border-slate-700/50 rounded-lg p-3">
                <legend className="text-xs font-medium text-slate-300 px-1">{t('cz_windows_rights')}</legend>
                <div className="space-y-1.5 mt-1">
                  <Chk checked={consoleLogin} onChange={setConsoleLogin} label={t('cz_console_login')} />
                  <Chk checked={remoteLogin} onChange={setRemoteLogin} label={t('cz_remote_login')} />
                  <Chk checked={powershellRemote} onChange={setPowershellRemote} label={t('cz_powershell_remote')} />
                </div>
              </fieldset>

              <fieldset className="border border-slate-700/50 rounded-lg p-3">
                <legend className="text-xs font-medium text-slate-300 px-1">{t('cz_rescue_rights')}</legend>
                <div className="mt-1">
                  <Chk checked={rescueLogin} onChange={setRescueLogin} label={t('cz_rescue_login')} />
                </div>
              </fieldset>
            </div>
          )}

          {/* Authentication */}
          {tab === 'authentication' && (
            <div>
              <fieldset className="border border-slate-700/50 rounded-lg p-4">
                <legend className="text-xs font-medium text-slate-300 px-1">Multi-factor Authentication</legend>
                <Chk checked={requireMfa} onChange={setRequireMfa} label={t('cz_require_mfa')} />
              </fieldset>
            </div>
          )}

          {/* Audit */}
          {tab === 'audit' && (
            <div>
              <p className="text-xs text-slate-400 mb-3">{t('cz_audit_level')}</p>
              <div className="space-y-3">
                {([
                  { val: 'none', label: t('cz_audit_none'), desc: t('cz_audit_none_desc') },
                  { val: 'if_possible', label: t('cz_audit_if_possible'), desc: t('cz_audit_if_possible_desc') },
                  { val: 'required', label: t('cz_audit_required'), desc: t('cz_audit_required_desc') },
                ] as const).map(opt => (
                  <label key={opt.val} className="flex items-start gap-2 cursor-pointer">
                    <input type="radio" name="audit" value={opt.val} checked={auditLevel === opt.val}
                      onChange={() => setAuditLevel(opt.val)}
                      className="mt-0.5 text-blue-500 bg-slate-900 border-slate-600" />
                    <div>
                      <span className="text-xs text-slate-200 font-medium">{opt.label}</span>
                      <p className="text-[10.5px] text-slate-500 leading-relaxed">{opt.desc}</p>
                    </div>
                  </label>
                ))}
              </div>
            </div>
          )}

          {/* Custom Attributes */}
          {tab === 'custom_attrs' && (
            <div>
              <div className="flex gap-2 mb-3">
                <div className="flex-1 border border-slate-700 rounded overflow-hidden">
                  <table className="w-full text-xs">
                    <thead><tr className="bg-slate-900/50 text-slate-400">
                      <th className="text-left py-1.5 px-2 font-medium">{t('cz_attr_name')}</th>
                      <th className="text-left py-1.5 px-2 font-medium">{t('cz_attr_value')}</th>
                    </tr></thead>
                    <tbody>
                      {attrs.length === 0 && <tr><td colSpan={2} className="py-6 text-center text-slate-600">No attributes</td></tr>}
                      {attrs.map((a, i) => (
                        <tr key={i} className="border-t border-slate-800 hover:bg-slate-800/30">
                          <td className="py-1 px-2 text-slate-300">{a.name}</td>
                          <td className="py-1 px-2 text-slate-300">{a.value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="flex flex-col gap-1 min-w-[80px]">
                  <button className="px-2 py-1 bg-slate-700 hover:bg-slate-600 text-xs text-slate-200 rounded"
                    onClick={() => {
                      if (newAttrName.trim()) {
                        setAttrs(prev => [...prev, { name: newAttrName.trim(), value: newAttrValue }])
                        setNewAttrName(''); setNewAttrValue('')
                      }
                    }}>{t('cz_attr_add')}</button>
                  <button className="px-2 py-1 bg-slate-700/50 text-xs text-slate-400 rounded" disabled>{t('cz_attr_edit')}</button>
                  <button className="px-2 py-1 bg-slate-700/50 text-xs text-slate-400 rounded"
                    onClick={() => setAttrs(prev => prev.slice(0, -1))} disabled={attrs.length === 0}>{t('cz_attr_remove')}</button>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <input className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 outline-none"
                  value={newAttrName} onChange={e => setNewAttrName(e.target.value)} placeholder="Name" />
                <input className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 outline-none"
                  value={newAttrValue} onChange={e => setNewAttrValue(e.target.value)} placeholder="Value" />
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-slate-700/50 pt-3 mt-3 space-y-2">
          <div>
            <label className="block text-xs text-slate-400 mb-1">{t('cz_reason')}</label>
            <input className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-200 outline-none"
              value={reason} onChange={e => setReason(e.target.value)} placeholder="min 3 karakter" />
          </div>
          {error && <p className="text-xs text-red-400">{error}</p>}
          <div className="flex gap-2 justify-end">
            <button onClick={onClose} className="px-4 py-1.5 bg-slate-700 hover:bg-slate-600 text-xs text-slate-200 rounded-lg">{t('cancel')}</button>
            <button onClick={doSave} disabled={saving || !name.trim() || reason.length < 3}
              className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-xs text-white rounded-lg">
              {saving ? '…' : 'OK'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Create/Edit Command diyaloğu ─────────────────────────────

const CommandDialog: React.FC<{
  zoneId: number; cmd?: Command | null; mode: 'create' | 'edit' | 'copy'
  onClose: () => void; onDone: () => void
}> = ({ zoneId, cmd, mode, onClose, onDone }) => {
  const t = useT()
  const [name, setName] = useState(mode === 'copy' ? `${cmd?.name || ''}-copy` : (cmd?.name || ''))
  const [path, setPath] = useState(cmd?.command_path || '')
  const [matchType, setMatchType] = useState(cmd?.match_type || 'glob')
  const [runAs, setRunAs] = useState(cmd?.run_as_user || 'root')
  const [authType, setAuthType] = useState(cmd?.auth_type || 'password')
  const [desc, setDesc] = useState(cmd?.description || '')
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const doSave = async () => {
    setSaving(true)
    setError('')
    const res = await fetch(api('/commands'), {
      method: 'POST', headers: hdrs(),
      body: JSON.stringify({
        zone_id: zoneId, name, command_path: path, match_type: matchType,
        run_as_user: runAs, run_as_group: '', auth_type: authType,
        description: desc, reason: reason || `${name} — ${mode}`,
      }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      setError(typeof body.detail === 'string' ? body.detail : `Komut oluşturulamadı (${res.status})`)
      setSaving(false)
      return
    }
    setSaving(false); onDone(); onClose()
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 w-[520px] shadow-2xl" onClick={e => e.stopPropagation()}>
        <h3 className="text-sm font-semibold text-slate-100 mb-4 flex items-center gap-2">
          <Terminal size={16} className="text-green-400" />
          {mode === 'create' ? t('cz_create_command') : mode === 'copy' ? t('cz_copy') : t('cz_edit')}
        </h3>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="block text-xs text-slate-400 mb-1">{t('cz_cmd_name')}</label>
              <input className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 outline-none"
                value={name} onChange={e => setName(e.target.value)} autoFocus />
            </div>
            <div className="col-span-2">
              <label className="block text-xs text-slate-400 mb-1">{t('cz_cmd_path')}</label>
              <input className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 font-mono outline-none"
                value={path} onChange={e => setPath(e.target.value)} />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">{t('cz_cmd_match')}</label>
              <select className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 outline-none"
                value={matchType} onChange={e => setMatchType(e.target.value)}>
                <option value="exact">Exact</option><option value="glob">Glob</option><option value="regex">Regex</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">{t('cz_cmd_run_as')}</label>
              <input className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 outline-none"
                value={runAs} onChange={e => setRunAs(e.target.value)} />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">{t('cz_cmd_auth')}</label>
              <select className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 outline-none"
                value={authType} onChange={e => setAuthType(e.target.value)}>
                <option value="none">None</option><option value="password">User password</option><option value="mfa">MFA</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">{t('cz_role_desc')}</label>
              <input className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 outline-none"
                value={desc} onChange={e => setDesc(e.target.value)} />
            </div>
            <div className="col-span-2">
              <label className="block text-xs text-slate-400 mb-1">{t('cz_reason')}</label>
              <input className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 outline-none"
                value={reason} onChange={e => setReason(e.target.value)} placeholder="min 3 karakter" />
            </div>
          </div>
          {error && <p className="text-xs text-red-400 pt-1">{error}</p>}
          <div className="flex gap-2 pt-1">
            <button onClick={onClose} className="flex-1 px-3 py-2 bg-slate-700 hover:bg-slate-600 text-xs text-slate-200 rounded-lg">{t('cancel')}</button>
            <button onClick={doSave} disabled={saving || !name.trim() || !path.trim() || reason.length < 3}
              className="flex-1 px-3 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-50 text-xs text-white rounded-lg">
              {saving ? '…' : t('save')}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Komut → Role ekle / çıkar ────────────────────────────────

const CommandToRoleDialog: React.FC<{
  zoneId: number; cmd: Command; mode: 'add' | 'remove'
  onClose: () => void; onDone: () => void
}> = ({ zoneId, cmd, mode, onClose, onDone }) => {
  const t = useT()
  const { data: roles = [] } = useQuery<Role[]>({
    queryKey: ['centrify-roles-with-parents', zoneId],
    queryFn: () => fetchJson(`/zones/${zoneId}/roles?include_parents=true`),
  })
  const [roleName, setRoleName] = useState('')
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const doSave = async () => {
    setSaving(true)
    setError('')
    const path = mode === 'add' ? '/commands/add-to-role' : '/commands/remove-from-role'
    const res = await fetch(api(path), {
      method: 'POST', headers: hdrs(),
      body: JSON.stringify({
        zone_id: zoneId,
        role_name: roleName,
        command_name: cmd.name,
        reason,
      }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      setError(typeof body.detail === 'string' ? body.detail : `İşlem oluşturulamadı (${res.status})`)
      setSaving(false)
      return
    }
    setSaving(false); onDone(); onClose()
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 w-[460px] shadow-2xl" onClick={e => e.stopPropagation()}>
        <h3 className="text-sm font-semibold text-slate-100 mb-4 flex items-center gap-2">
          {mode === 'add' ? <Link2 size={16} className="text-blue-400" /> : <Unlink size={16} className="text-amber-400" />}
          {mode === 'add' ? t('cz_add_cmd_to_role_title') : t('cz_remove_cmd_from_role_title')}
        </h3>
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-slate-400 mb-1">{t('cz_cmd_name')}</label>
            <input className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-300 outline-none" value={cmd.name} readOnly />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">{t('cz_col_role')}</label>
            <select className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 outline-none"
              value={roleName} onChange={e => setRoleName(e.target.value)}>
              <option value="">{t('cz_select_role')}</option>
              {roles.map(r => (
                <option key={r.id} value={r.name}>{r.name}{r.zone_name ? ` / ${r.zone_name}` : ''}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">{t('cz_reason')}</label>
            <input className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 outline-none"
              value={reason} onChange={e => setReason(e.target.value)} placeholder="min 3 karakter" />
          </div>
          {error && <p className="text-xs text-red-400">{error}</p>}
          <div className="flex gap-2 pt-1">
            <button onClick={onClose} className="flex-1 px-3 py-2 bg-slate-700 hover:bg-slate-600 text-xs text-slate-200 rounded-lg">{t('cancel')}</button>
            <button onClick={doSave} disabled={saving || !roleName || reason.length < 3}
              className="flex-1 px-3 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-xs text-white rounded-lg">
              {saving ? '…' : 'OK'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Add AD Account alt-diyaloğu ──────────────────────────────

const AddADAccountDialog: React.FC<{
  onAdd: (type: string, name: string) => void; onClose: () => void
}> = ({ onAdd, onClose }) => {
  const t = useT()
  const [findType, setFindType] = useState('User')
  const [domain, setDomain] = useState('kfs.local')
  const [name, setName] = useState('')

  return (
    <div className="fixed inset-0 bg-black/40 z-[60] flex items-center justify-center" onClick={onClose}>
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 w-[440px] shadow-2xl" onClick={e => e.stopPropagation()}>
        <h3 className="text-sm font-semibold text-slate-100 mb-3 flex items-center gap-2">
          <Search size={14} className="text-blue-400" /> {t('cz_ar_add_ad_title')}
        </h3>
        <div className="flex items-center gap-2 mb-3">
          <span className="text-xs text-slate-400">{t('cz_ar_find')}</span>
          <select className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 outline-none"
            value={findType} onChange={e => setFindType(e.target.value)}>
            <option value="User">User</option><option value="Group">Group</option>
          </select>
          <span className="text-xs text-slate-400">{t('cz_ar_in')}</span>
          <input className="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 outline-none"
            value={domain} onChange={e => setDomain(e.target.value)} />
        </div>
        <div className="flex gap-2 mb-3 border-b border-slate-700/50 pb-1">
          <span className="text-xs text-blue-400 border-b-2 border-blue-500 px-2 py-1">{t('cz_ar_user_tab')}</span>
          <span className="text-xs text-slate-500 px-2 py-1">{t('cz_ar_advanced_tab')}</span>
          <div className="ml-auto flex flex-col gap-1">
            <button onClick={() => { if (name.trim()) { onAdd(findType === 'User' ? 'AD User' : 'AD Group', name.trim()); onClose() } }}
              className="px-3 py-1 bg-blue-600 hover:bg-blue-500 text-[10px] text-white rounded">{t('cz_ar_find_now')}</button>
            <button className="px-3 py-1 bg-slate-700/50 text-[10px] text-slate-500 rounded" disabled>{t('cz_ar_clear_all')}</button>
          </div>
        </div>
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400 w-20">Name:</span>
            <input className="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 outline-none"
              value={name} onChange={e => setName(e.target.value)} autoFocus />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400 w-20">{t('cz_ar_description')}:</span>
            <input className="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 outline-none" />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-3">
          <button onClick={onClose} className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-xs text-slate-200 rounded">{t('cancel')}</button>
        </div>
      </div>
    </div>
  )
}

// ── Add Local Account alt-diyaloğu ───────────────────────────

const AddLocalAccountDialog: React.FC<{
  onAdd: (type: string, name: string) => void; onClose: () => void
}> = ({ onAdd, onClose }) => {
  const t = useT()
  const [localType, setLocalType] = useState('Local UNIX User')
  const [account, setAccount] = useState('')

  const types = [
    { value: 'Local UNIX User', label: t('cz_ar_local_unix_user') },
    { value: 'Local UNIX UID', label: t('cz_ar_local_unix_uid') },
    { value: 'Local UNIX Group', label: t('cz_ar_local_unix_group') },
    { value: 'Local Windows User', label: t('cz_ar_local_win_user') },
    { value: 'Local Windows Group', label: t('cz_ar_local_win_group') },
  ]

  return (
    <div className="fixed inset-0 bg-black/40 z-[60] flex items-center justify-center" onClick={onClose}>
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 w-[360px] shadow-2xl" onClick={e => e.stopPropagation()}>
        <h3 className="text-sm font-semibold text-slate-100 mb-3">{t('cz_ar_add_local_title')}</h3>
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400 w-16">{t('cz_ar_local_type')}</span>
            <select className="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-200 outline-none"
              value={localType} onChange={e => setLocalType(e.target.value)}>
              {types.map(lt => <option key={lt.value} value={lt.value}>{lt.label}</option>)}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400 w-16">{t('cz_ar_local_account')}</span>
            <input className="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-200 outline-none"
              value={account} onChange={e => setAccount(e.target.value)} autoFocus />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={() => { if (account.trim()) { onAdd(localType, account.trim()); onClose() } }}
            className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-xs text-white rounded"
            disabled={!account.trim()}>OK</button>
          <button onClick={onClose} className="px-4 py-1.5 bg-slate-700 hover:bg-slate-600 text-xs text-slate-200 rounded">{t('cancel')}</button>
        </div>
      </div>
    </div>
  )
}

// ── Assign Role diyaloğu (2 aşama: Select Role → Assign Detail) ─

const AssignRoleDialog: React.FC<{
  zoneId: number; computerId?: number; computerName?: string
  onClose: () => void; onDone: () => void
}> = ({ zoneId, computerId, computerName, onClose, onDone }) => {
  const t = useT()
  const { data: roles = [] } = useQuery<Role[]>({
    queryKey: ['centrify-roles-with-parents', zoneId],
    queryFn: () => fetchJson(`/zones/${zoneId}/roles?include_parents=true`),
  })

  // Aşama: 'select' = rol seç, 'assign' = detay
  const [step, setStep] = useState<'select' | 'assign'>('select')
  const [selectedRole, setSelectedRole] = useState<Role | null>(null)

  // Select Role filtreler
  const [fRole, setFRole] = useState('')
  const [fZone, setFZone] = useState('')
  const [fAllow, setFAllow] = useState('')
  const [fDesc, setFDesc] = useState('')

  // Assign Detail state
  const [startImmediate, setStartImmediate] = useState(true)
  const [neverExpire, setNeverExpire] = useState(true)
  const [startTime, setStartTime] = useState(() => new Date().toISOString().slice(0, 16))
  const [endTime, setEndTime] = useState(() => new Date().toISOString().slice(0, 16))
  const [assignDesc, setAssignDesc] = useState('')
  const [reason, setReason] = useState('')

  // Assignee
  const [assigneeMode, setAssigneeMode] = useState<'all' | 'below'>('below')
  const [allAD, setAllAD] = useState(true)
  const [allWindows, setAllWindows] = useState(true)
  const [allUnix, setAllUnix] = useState(true)
  const [assignees, setAssignees] = useState<{ type: string; name: string }[]>([])

  // Sub-dialogs
  const [showAddAD, setShowAddAD] = useState(false)
  const [showAddLocal, setShowAddLocal] = useState(false)

  const [saving, setSaving] = useState(false)

  const allowLocal = selectedRole?.allow_local_accounts || false

  const filtered = useMemo(() => {
    return roles.filter(r => {
      if (fRole && !r.name.toLowerCase().includes(fRole.toLowerCase())) return false
      if (fZone && !(r.zone_dn || '').toLowerCase().includes(fZone.toLowerCase()) && !(r.zone_name || '').toLowerCase().includes(fZone.toLowerCase())) return false
      if (fAllow) {
        const allowStr = r.allow_local_accounts ? 'yes' : 'no'
        if (!allowStr.includes(fAllow.toLowerCase())) return false
      }
      if (fDesc && !(r.description || '').toLowerCase().includes(fDesc.toLowerCase())) return false
      return true
    })
  }, [roles, fRole, fZone, fAllow, fDesc])

  const handleSelectOk = () => {
    if (selectedRole) setStep('assign')
  }

  const doAssign = async () => {
    if (!selectedRole) return
    setSaving(true)

    const assigneeList = assigneeMode === 'all'
      ? [{ type: 'all', name: allowLocal ? `AD:${allAD},Win:${allWindows},Unix:${allUnix}` : 'All AD accounts' }]
      : assignees

    for (const a of assigneeList) {
      await fetch(api('/operations'), {
        method: 'POST', headers: hdrs(),
        body: JSON.stringify({
          operation_type: 'create_role_assignment', zone_id: zoneId,
          desired_state: {
            role_name: selectedRole.name,
            assignee_name: a.name,
            assignee_type: a.type.includes('Group') ? 'group' : a.type === 'all' ? 'all' : 'user',
            computer_id: computerId || null,
            scope_type: computerId ? 'computer' : 'zone',
            start_time: startImmediate ? null : startTime,
            end_time: neverExpire ? null : endTime,
            description: assignDesc,
          },
          reason: reason || `${a.name} → ${selectedRole.name}`,
        }),
      })
    }
    setSaving(false); onDone(); onClose()
  }

  // ── Aşama 1: Select Role ────────────────────

  if (step === 'select') return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 w-[660px] max-h-[80vh] flex flex-col shadow-2xl"
        onClick={e => e.stopPropagation()}>
        <h3 className="text-sm font-semibold text-slate-100 mb-3">{t('cz_select_role')}</h3>

        {computerId && (
          <div className="mb-2">
            <span className="inline-flex items-center gap-1.5 text-[11px] text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded px-2 py-0.5">
              <Monitor size={11} /> {computerName}
            </span>
          </div>
        )}

        <div className="border border-slate-700 rounded-lg overflow-hidden flex-1 min-h-0 mb-3">
          <div className="max-h-[340px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 z-10">
                <tr className="bg-slate-900 text-slate-400 border-b border-slate-700">
                  <th className="text-left py-1.5 px-2 font-medium w-[150px]">
                    {t('cz_col_role')}
                    <input className="block w-full mt-0.5 bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-[10px] text-slate-300 outline-none"
                      value={fRole} onChange={e => setFRole(e.target.value)} placeholder="Enter text …" />
                  </th>
                  <th className="text-left py-1.5 px-2 font-medium">
                    {t('cz_col_zone')}
                    <input className="block w-full mt-0.5 bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-[10px] text-slate-300 outline-none"
                      value={fZone} onChange={e => setFZone(e.target.value)} placeholder="Enter text here" />
                  </th>
                  <th className="text-left py-1.5 px-2 font-medium w-[100px]">
                    {t('cz_col_allow_local')}
                    <input className="block w-full mt-0.5 bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-[10px] text-slate-300 outline-none"
                      value={fAllow} onChange={e => setFAllow(e.target.value)} placeholder="Enter text here" />
                  </th>
                  <th className="text-left py-1.5 px-2 font-medium">
                    {t('cz_col_desc')}
                    <input className="block w-full mt-0.5 bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-[10px] text-slate-300 outline-none"
                      value={fDesc} onChange={e => setFDesc(e.target.value)} placeholder="Enter text here" />
                  </th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(r => (
                  <tr key={r.id}
                    onClick={() => setSelectedRole(r)}
                    onDoubleClick={() => { setSelectedRole(r); setStep('assign') }}
                    className={`border-b border-slate-800/50 cursor-pointer transition-colors
                      ${selectedRole?.id === r.id ? 'bg-blue-600/20 text-blue-300' : 'hover:bg-slate-800/40 text-slate-300'}`}>
                    <td className="py-1 px-2 truncate">{r.name}</td>
                    <td className="py-1 px-2 truncate text-slate-400 max-w-[200px]">{r.zone_dn || r.zone_name || '—'}</td>
                    <td className="py-1 px-2">{r.allow_local_accounts ? 'Yes' : 'No'}</td>
                    <td className="py-1 px-2 truncate text-slate-500 max-w-[160px]">{r.description || ''}</td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr><td colSpan={4} className="py-4 text-center text-slate-500">No roles match filter</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="flex gap-2 justify-end">
          <button onClick={handleSelectOk} disabled={!selectedRole}
            className="px-5 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-xs text-white rounded-lg">OK</button>
          <button onClick={onClose} className="px-5 py-1.5 bg-slate-700 hover:bg-slate-600 text-xs text-slate-200 rounded-lg">{t('cancel')}</button>
        </div>
      </div>
    </div>
  )

  // ── Aşama 2: Assign Role Detail ─────────────

  const roleName = `${selectedRole!.name}/${selectedRole!.zone_name || ''}`

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 w-[520px] max-h-[88vh] flex flex-col shadow-2xl overflow-y-auto"
        onClick={e => e.stopPropagation()}>
        <h3 className="text-sm font-semibold text-slate-100 mb-3">{t('cz_ar_title')}</h3>

        {/* Role fieldset */}
        <fieldset className="border border-slate-700/50 rounded-lg p-3 mb-3">
          <legend className="text-xs font-medium text-slate-300 px-1">{t('cz_ar_role_section')}</legend>
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400 w-20 shrink-0">{t('cz_ar_role_label')}</span>
              <input className="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 outline-none" value={roleName} readOnly />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400 w-20 shrink-0">{t('cz_ar_start_time')}</span>
              <input type="datetime-local" className="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 outline-none"
                value={startTime} onChange={e => setStartTime(e.target.value)} disabled={startImmediate} />
              <label className="flex items-center gap-1 text-xs text-slate-400 shrink-0 cursor-pointer">
                <input type="checkbox" checked={startImmediate} onChange={e => setStartImmediate(e.target.checked)}
                  className="rounded border-slate-600 bg-slate-900 text-blue-500" />
                {t('cz_ar_start_immediately')}
              </label>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400 w-20 shrink-0">{t('cz_ar_end_time')}</span>
              <input type="datetime-local" className="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 outline-none"
                value={endTime} onChange={e => setEndTime(e.target.value)} disabled={neverExpire} />
              <label className="flex items-center gap-1 text-xs text-slate-400 shrink-0 cursor-pointer">
                <input type="checkbox" checked={neverExpire} onChange={e => setNeverExpire(e.target.checked)}
                  className="rounded border-slate-600 bg-slate-900 text-blue-500" />
                {t('cz_ar_never_expire')}
              </label>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400 w-20 shrink-0">{t('cz_ar_description')}</span>
              <input className="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 outline-none"
                value={assignDesc} onChange={e => setAssignDesc(e.target.value)} />
            </div>
          </div>
        </fieldset>

        {/* Assignee fieldset */}
        <fieldset className="border border-slate-700/50 rounded-lg p-3 mb-3">
          <legend className="text-xs font-medium text-slate-300 px-1">{t('cz_ar_assignee_section')}</legend>
          <div className="space-y-2">
            {/* Radio: All accounts */}
            <label className="flex items-start gap-2 cursor-pointer">
              <input type="radio" name="assignee-mode" checked={assigneeMode === 'all'} onChange={() => setAssigneeMode('all')}
                className="mt-0.5 text-blue-500 bg-slate-900 border-slate-600" />
              <div>
                <span className="text-xs text-slate-300">
                  {allowLocal ? t('cz_ar_all_accounts') : t('cz_ar_all_ad_accounts')}
                </span>
                {allowLocal && assigneeMode === 'all' && (
                  <div className="ml-4 mt-1 space-y-0.5">
                    <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer">
                      <input type="checkbox" checked={allAD} onChange={e => setAllAD(e.target.checked)}
                        className="rounded border-slate-600 bg-slate-900 text-blue-500" />
                      {t('cz_ar_all_ad_check')}
                    </label>
                    <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer">
                      <input type="checkbox" checked={allWindows} onChange={e => setAllWindows(e.target.checked)}
                        className="rounded border-slate-600 bg-slate-900 text-blue-500" />
                      {t('cz_ar_all_windows_check')}
                    </label>
                    <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer">
                      <input type="checkbox" checked={allUnix} onChange={e => setAllUnix(e.target.checked)}
                        className="rounded border-slate-600 bg-slate-900 text-blue-500" />
                      {t('cz_ar_all_unix_check')}
                    </label>
                  </div>
                )}
              </div>
            </label>

            {/* Radio: Accounts below */}
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="radio" name="assignee-mode" checked={assigneeMode === 'below'} onChange={() => setAssigneeMode('below')}
                className="text-blue-500 bg-slate-900 border-slate-600" />
              <span className="text-xs text-slate-300">{t('cz_ar_accounts_below')}</span>
            </label>

            {assigneeMode === 'below' && (
              <div className="ml-5 flex gap-2">
                <div className="flex-1 border border-slate-700 rounded overflow-hidden">
                  <table className="w-full text-xs">
                    <thead><tr className="bg-slate-900/50 text-slate-400">
                      <th className="text-left py-1 px-2 font-medium w-[120px]">{t('cz_ar_col_type')}</th>
                      <th className="text-left py-1 px-2 font-medium">{t('cz_ar_col_assignee')}</th>
                    </tr></thead>
                    <tbody>
                      {assignees.length === 0 && <tr><td colSpan={2} className="py-4 text-center text-slate-600 text-[10px]">No accounts added</td></tr>}
                      {assignees.map((a, i) => (
                        <tr key={i} className="border-t border-slate-800 hover:bg-slate-800/30">
                          <td className="py-1 px-2 text-slate-400">{a.type}</td>
                          <td className="py-1 px-2 text-slate-300">{a.name}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="flex flex-col gap-1.5 min-w-[148px]">
                  <button type="button" onClick={() => setShowAddAD(true)}
                    className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-[11px] font-medium text-white rounded-md shadow-sm text-center">
                    {t('cz_ar_add_ad_account')}
                  </button>
                  {allowLocal && (
                    <button type="button" onClick={() => setShowAddLocal(true)}
                      className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-[11px] font-medium text-white rounded-md shadow-sm text-center">
                      {t('cz_ar_add_local_account')}
                    </button>
                  )}
                  <button type="button" onClick={() => setAssignees(prev => prev.slice(0, -1))} disabled={assignees.length === 0}
                    className="px-3 py-1.5 bg-slate-600 hover:bg-slate-500 text-[11px] font-medium text-white rounded-md shadow-sm text-center disabled:opacity-40">
                    {t('cz_ar_remove')}
                  </button>
                </div>
              </div>
            )}
          </div>
        </fieldset>

        {/* Reason (ainew specific) */}
        <div className="mb-3">
          <label className="block text-xs text-slate-400 mb-1">{t('cz_reason')}</label>
          <input className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-200 outline-none"
            value={reason} onChange={e => setReason(e.target.value)} placeholder="min 3 karakter" />
        </div>

        <div className="flex gap-2 justify-end">
          <button onClick={doAssign}
            disabled={saving || reason.length < 3 || (assigneeMode === 'below' && assignees.length === 0)}
            className="px-5 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-xs text-white rounded-lg">
            {saving ? '…' : 'OK'}
          </button>
          <button onClick={onClose} className="px-5 py-1.5 bg-slate-700 hover:bg-slate-600 text-xs text-slate-200 rounded-lg">{t('cancel')}</button>
        </div>
      </div>

      {/* Sub-dialogs */}
      {showAddAD && <AddADAccountDialog onAdd={(type, name) => setAssignees(prev => [...prev, { type, name }])} onClose={() => setShowAddAD(false)} />}
      {showAddLocal && <AddLocalAccountDialog onAdd={(type, name) => setAssignees(prev => [...prev, { type, name }])} onClose={() => setShowAddLocal(false)} />}
    </div>
  )
}

// ── Sağ panel bileşenleri ────────────────────────────────────

const Spin: React.FC = () => <div className="flex items-center justify-center py-12 text-slate-500"><Loader2 size={20} className="animate-spin mr-2" /> Loading…</div>
const Empty: React.FC<{ text: string }> = ({ text }) => <div className="flex flex-col items-center justify-center py-12 text-slate-500"><Info size={24} className="mb-2" /><span className="text-sm">{text}</span></div>
const Badge: React.FC<{ state: string }> = ({ state }) => state === 'managed'
  ? <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-500/20 text-green-400">Managed</span>
  : <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-600/30 text-slate-400">Read Only</span>

const ComputersPanel: React.FC<{
  zoneId: number; zoneName: string
  onOpenComputer: (c: Computer) => void
  onCtxFolder: (e: React.MouseEvent) => void
  onCtxComputer: (e: React.MouseEvent, c: Computer) => void
}> = ({ zoneId, zoneName, onOpenComputer, onCtxFolder, onCtxComputer }) => {
  const t = useT()
  const { data: items = [], isLoading } = useQuery<Computer[]>({ queryKey: ['centrify-computers', zoneId], queryFn: () => fetchJson(`/zones/${zoneId}/computers`) })
  if (isLoading) return <Spin />
  if (!items.length) return <Empty text={t('cz_no_data')} />
  return (
    <div className="overflow-x-auto h-full" onContextMenu={e => { e.preventDefault(); onCtxFolder(e) }}>
      <table className="w-full text-sm">
        <thead><tr className="text-left text-slate-400 border-b border-slate-700/50 bg-slate-900/30">
          <th className="py-2 px-3 text-xs font-medium">{t('cz_col_name')}</th>
          <th className="py-2 px-3 text-xs font-medium">{t('cz_col_joined')}</th>
          <th className="py-2 px-3 text-xs font-medium">{t('cz_col_agent')}</th>
          <th className="py-2 px-3 text-xs font-medium">{t('cz_col_os')}</th>
          <th className="py-2 px-3 text-xs font-medium">{t('cz_col_desc')}</th>
          <th className="py-2 px-3 text-xs font-medium">{t('cz_col_canonical')}</th>
        </tr></thead>
        <tbody>
          {items.map(c => (
            <tr key={c.id}
              className="border-b border-slate-800/50 hover:bg-slate-800/30 cursor-pointer"
              onDoubleClick={() => onOpenComputer(c)}
              onContextMenu={e => { e.preventDefault(); e.stopPropagation(); onCtxComputer(e, c) }}>
              <td className="py-1.5 px-3"><div className="flex items-center gap-2"><Monitor size={13} className="text-blue-400" /><span className="text-slate-200 text-xs">{c.name}</span></div></td>
              <td className="py-1.5 px-3 text-xs text-slate-400">{c.management_state === 'managed' ? 'Y' : 'N'}</td>
              <td className="py-1.5 px-3 text-xs text-slate-400">{c.agent_version || '—'}</td>
              <td className="py-1.5 px-3 text-xs text-slate-400">{c.os_type || '—'}</td>
              <td className="py-1.5 px-3 text-xs text-slate-500">—</td>
              <td className="py-1.5 px-3 text-xs text-slate-500 font-mono truncate max-w-[200px]">{c.fqdn || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="px-3 py-2 text-[11px] text-slate-600">{zoneName} — çift tıklayarak sunucu alt öğelerini açın</p>
    </div>
  )
}

const ComputerExplorer: React.FC<{
  zoneId: number; zoneName: string; computerId: number; computerName: string
  onSel: (s: TreeSelection) => void
  onCtx: (e: React.MouseEvent, nodeType: VNodeType, computerId?: number) => void
}> = ({ zoneId, zoneName, computerId, computerName, onSel, onCtx }) => {
  const folders: { nodeType: VNodeType; label: string }[] = [
    { nodeType: 'unix_data', label: 'UNIX Data' },
    { nodeType: 'role_assignments', label: 'Role Assignments' },
  ]
  return (
    <div className="p-3">
      <div className="text-xs text-slate-400 mb-2 flex items-center gap-1.5">
        <Monitor size={13} className="text-blue-400" />
        <span className="text-slate-200 font-medium">{computerName}</span>
      </div>
      <div className="border border-slate-700/50 rounded-lg overflow-hidden">
        {folders.map(f => (
          <button key={f.nodeType}
            onClick={() => onSel({ zoneId, nodeType: f.nodeType, zoneName, itemId: computerId, itemName: computerName })}
            onDoubleClick={() => onSel({ zoneId, nodeType: f.nodeType, zoneName, itemId: computerId, itemName: computerName })}
            onContextMenu={e => { e.preventDefault(); onCtx(e, f.nodeType, computerId) }}
            className="w-full flex items-center gap-2 px-3 py-2 text-left text-sm text-slate-200 hover:bg-slate-800/50 border-b border-slate-800/60 last:border-0">
            <Folder size={14} className="text-amber-400/80" />
            {f.label}
          </button>
        ))}
      </div>
    </div>
  )
}

const UsersPanel: React.FC<{ zoneId: number }> = ({ zoneId }) => {
  const t = useT()
  const { data: items = [], isLoading } = useQuery<any[]>({ queryKey: ['centrify-unix-profiles', zoneId], queryFn: () => fetchJson(`/zones/${zoneId}/unix-profiles`) })
  if (isLoading) return <Spin />
  if (!items.length) return <Empty text={t('cz_no_data')} />
  return (
    <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left text-slate-400 border-b border-slate-700/50 bg-slate-900/30">
      <th className="py-2 px-3 text-xs font-medium">{t('cz_col_user')}</th>
      <th className="py-2 px-3 text-xs font-medium">{t('cz_col_unix_name')}</th>
      <th className="py-2 px-3 text-xs font-medium">{t('cz_col_uid')}</th>
      <th className="py-2 px-3 text-xs font-medium">{t('cz_col_primary_group')}</th>
      <th className="py-2 px-3 text-xs font-medium">{t('cz_col_gecos')}</th>
      <th className="py-2 px-3 text-xs font-medium">{t('cz_col_home')}</th>
      <th className="py-2 px-3 text-xs font-medium">{t('cz_col_shell')}</th>
    </tr></thead><tbody>
      {items.map((p: any) => <tr key={p.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
        <td className="py-1.5 px-3"><div className="flex items-center gap-2"><User size={13} className="text-cyan-400" /><span className="text-slate-200 text-xs">{p.user_name}</span></div></td>
        <td className="py-1.5 px-3 text-xs text-slate-400">{p.user_name}</td>
        <td className="py-1.5 px-3 text-xs text-slate-400">{p.uid ?? '—'}</td>
        <td className="py-1.5 px-3 text-xs text-slate-400">{p.gid ?? '—'}</td>
        <td className="py-1.5 px-3 text-xs text-slate-500">{p.gecos || '—'}</td>
        <td className="py-1.5 px-3 text-xs text-slate-400 font-mono">{p.home_dir || '—'}</td>
        <td className="py-1.5 px-3 text-xs text-slate-400 font-mono">{p.shell || '—'}</td>
      </tr>)}
    </tbody></table></div>
  )
}

const RolesPanel: React.FC<{ zoneId: number; onRowCtx: (e: React.MouseEvent, r: Role) => void }> = ({ zoneId, onRowCtx }) => {
  const t = useT()
  const { data: roles = [], isLoading } = useQuery<Role[]>({ queryKey: ['centrify-roles', zoneId], queryFn: () => fetchJson(`/zones/${zoneId}/roles`) })
  if (isLoading) return <Spin />
  if (!roles.length) return <Empty text={t('cz_no_data')} />
  return (
    <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left text-slate-400 border-b border-slate-700/50 bg-slate-900/30">
      <th className="py-2 px-3 text-xs font-medium">{t('cz_col_name')}</th>
      <th className="py-2 px-3 text-xs font-medium">{t('cz_col_desc')}</th>
      <th className="py-2 px-3 text-xs font-medium text-center">{t('cz_commands')}</th>
      <th className="py-2 px-3 text-xs font-medium">Status</th>
    </tr></thead><tbody>
      {roles.map(r => <tr key={r.id} className="border-b border-slate-800/50 hover:bg-slate-800/30 cursor-context-menu"
        onContextMenu={e => { e.preventDefault(); onRowCtx(e, r) }}>
        <td className="py-1.5 px-3"><div className="flex items-center gap-2">
          <Shield size={13} className={r.is_system_role ? 'text-amber-400' : 'text-blue-400'} />
          <span className="text-slate-200 text-xs font-medium">{r.name}</span>
          {r.is_system_role && <span className="text-[9px] px-1 py-0.5 rounded bg-amber-500/20 text-amber-400">SYS</span>}
        </div></td>
        <td className="py-1.5 px-3 text-xs text-slate-400 max-w-xs truncate">{r.description || '—'}</td>
        <td className="py-1.5 px-3 text-center text-xs text-slate-300">{r.command_count}</td>
        <td className="py-1.5 px-3"><Badge state={r.management_state} /></td>
      </tr>)}
    </tbody></table></div>
  )
}

const CommandsPanel: React.FC<{ zoneId: number; onRowCtx: (e: React.MouseEvent, c: Command) => void }> = ({ zoneId, onRowCtx }) => {
  const t = useT()
  const { data: cmds = [], isLoading } = useQuery<Command[]>({ queryKey: ['centrify-commands', zoneId], queryFn: () => fetchJson(`/zones/${zoneId}/commands`) })
  if (isLoading) return <Spin />
  if (!cmds.length) return <Empty text={t('cz_no_data')} />
  return (
    <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left text-slate-400 border-b border-slate-700/50 bg-slate-900/30">
      <th className="py-2 px-3 text-xs font-medium">{t('cz_col_name')}</th>
      <th className="py-2 px-3 text-xs font-medium">{t('cz_col_desc')}</th>
      <th className="py-2 px-3 text-xs font-medium">{t('cz_col_command')}</th>
      <th className="py-2 px-3 text-xs font-medium">{t('cz_col_path')}</th>
      <th className="py-2 px-3 text-xs font-medium">{t('cz_col_run_as_dzdo')}</th>
      <th className="py-2 px-3 text-xs font-medium">{t('cz_col_authentication')}</th>
    </tr></thead><tbody>
      {cmds.map(c => <tr key={c.id} className="border-b border-slate-800/50 hover:bg-slate-800/30 cursor-context-menu"
        onContextMenu={e => { e.preventDefault(); onRowCtx(e, c) }}>
        <td className="py-1.5 px-3 text-xs text-slate-200">{c.name}</td>
        <td className="py-1.5 px-3 text-xs text-slate-500 max-w-[120px] truncate">{c.description || ''}</td>
        <td className="py-1.5 px-3 text-xs text-slate-300">{c.name}</td>
        <td className="py-1.5 px-3 text-xs text-slate-400 font-mono max-w-[180px] truncate">{c.command_path || '—'}</td>
        <td className="py-1.5 px-3 text-xs text-slate-400">{c.run_as_user || '—'}</td>
        <td className="py-1.5 px-3"><span className={`text-[10px] px-1.5 py-0.5 rounded ${
          c.auth_type === 'mfa' ? 'bg-red-500/20 text-red-400' : c.auth_type === 'password' ? 'bg-yellow-500/20 text-yellow-400' : 'bg-slate-700 text-slate-400'
        }`}>{c.auth_type === 'password' ? 'User password' : c.auth_type || 'None'}</span></td>
      </tr>)}
    </tbody></table></div>
  )
}

const AssignmentsPanel: React.FC<{
  zoneId: number; computerId?: number; computerName?: string
  onAssign: () => void
  onCtx?: (e: React.MouseEvent) => void
}> = ({ zoneId, computerId, onAssign, onCtx }) => {
  const t = useT()
  const endpoint = computerId
    ? `/zones/${zoneId}/computers/${computerId}/role-assignments`
    : `/zones/${zoneId}/role-assignments`
  const { data: items = [], isLoading } = useQuery<any[]>({
    queryKey: ['centrify-assignments', zoneId, computerId || 'zone'],
    queryFn: () => fetchJson(endpoint),
  })
  return (
    <div className="flex flex-col h-full min-h-0" onContextMenu={e => { e.preventDefault(); onCtx?.(e) }}>
      <div className="px-3 py-2 border-b border-slate-700/40 flex justify-end">
        <button type="button" onClick={onAssign}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-[11px] font-medium text-white rounded-md">
          <Plus size={12} /> {t('cz_assign_role')}
        </button>
      </div>
      {isLoading ? <Spin /> : !items.length ? <Empty text="There are no items to show in this view." /> : (
        <div className="overflow-x-auto flex-1"><table className="w-full text-sm"><thead><tr className="text-left text-slate-400 border-b border-slate-700/50 bg-slate-900/30">
          <th className="py-2 px-3 text-xs font-medium">{t('cz_col_assignee')}</th>
          <th className="py-2 px-3 text-xs font-medium">{t('cz_col_assignee_type')}</th>
          <th className="py-2 px-3 text-xs font-medium">{t('cz_col_role')}</th>
          <th className="py-2 px-3 text-xs font-medium">Scope</th>
        </tr></thead><tbody>
          {items.map((a: any) => <tr key={a.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
            <td className="py-1.5 px-3 text-xs text-slate-200">{a.assignee_name}</td>
            <td className="py-1.5 px-3 text-xs text-slate-400 capitalize">{a.assignee_type}</td>
            <td className="py-1.5 px-3 text-xs text-slate-400">{a.role_id}</td>
            <td className="py-1.5 px-3"><span className={`text-[10px] px-1.5 py-0.5 rounded ${
              a.scope_type === 'computer' ? 'bg-amber-500/20 text-amber-400' : 'bg-blue-500/20 text-blue-400'
            }`}>{a.scope_type || 'zone'}</span></td>
          </tr>)}
        </tbody></table></div>
      )}
    </div>
  )
}

const GenericPanel: React.FC<{ zoneId: number; endpoint: string }> = ({ zoneId, endpoint }) => {
  const t = useT()
  const { data: items = [], isLoading } = useQuery<any[]>({ queryKey: ['centrify', endpoint, zoneId], queryFn: () => fetchJson(`/zones/${zoneId}/${endpoint}`) })
  if (isLoading) return <Spin />
  if (!items.length) return <Empty text={t('cz_no_data')} />
  const keys = Object.keys(items[0]).filter(k => !['id', 'ad_guid', 'ad_dn'].includes(k)).slice(0, 7)
  return (
    <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left text-slate-400 border-b border-slate-700/50 bg-slate-900/30">
      {keys.map(k => <th key={k} className="py-2 px-3 text-xs font-medium capitalize">{k.replace(/_/g, ' ')}</th>)}
    </tr></thead><tbody>
      {items.map((it, i) => <tr key={it.id ?? i} className="border-b border-slate-800/50 hover:bg-slate-800/30">
        {keys.map(k => <td key={k} className="py-1.5 px-3 text-slate-300 text-xs max-w-xs truncate">{typeof it[k] === 'boolean' ? (it[k] ? '✓' : '—') : (it[k] ?? '—')}</td>)}
      </tr>)}
    </tbody></table></div>
  )
}

const ZoneOverview: React.FC<{ zoneId: number }> = ({ zoneId }) => {
  const { data: roles = [] } = useQuery<Role[]>({ queryKey: ['centrify-roles', zoneId], queryFn: () => fetchJson(`/zones/${zoneId}/roles`) })
  const { data: comps = [] } = useQuery<Computer[]>({ queryKey: ['centrify-computers', zoneId], queryFn: () => fetchJson(`/zones/${zoneId}/computers`) })
  const { data: profs = [] } = useQuery<any[]>({ queryKey: ['centrify-unix-profiles', zoneId], queryFn: () => fetchJson(`/zones/${zoneId}/unix-profiles`) })
  const { data: cmds = [] } = useQuery<Command[]>({ queryKey: ['centrify-commands', zoneId], queryFn: () => fetchJson(`/zones/${zoneId}/commands`) })
  const stats = [
    { label: 'Computers', v: comps.length, icon: <Monitor size={18} className="text-blue-400" />, c: 'text-blue-400' },
    { label: 'Roles', v: roles.length, icon: <Shield size={18} className="text-amber-400" />, c: 'text-amber-400' },
    { label: 'Commands', v: cmds.length, icon: <Terminal size={18} className="text-green-400" />, c: 'text-green-400' },
    { label: 'UNIX Profiles', v: profs.length, icon: <User size={18} className="text-cyan-400" />, c: 'text-cyan-400' },
  ]
  return (
    <div className="p-6"><div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {stats.map(s => <div key={s.label} className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-2">{s.icon}<span className="text-xs text-slate-400">{s.label}</span></div>
        <div className={`text-2xl font-bold ${s.c}`}>{s.v}</div>
      </div>)}
    </div></div>
  )
}

// ── Arama sonuçları ──────────────────────────────────────────

const SearchResults: React.FC<{
  results: SearchResult; q: string
  onNav: (zoneId: number, nodeType: VNodeType, itemName?: string) => void
}> = ({ results, q, onNav }) => {
  const t = useT()
  const total = results.zones.length + results.computers.length + results.users.length
  if (!total) return <Empty text={t('cz_no_results')} />
  return (
    <div className="space-y-4 p-4">
      {results.zones.length > 0 && <div>
        <h3 className="text-xs font-semibold text-slate-400 mb-2 uppercase tracking-wider">Zones ({results.zones.length})</h3>
        {results.zones.map(z => <button key={z.id} onClick={() => onNav(z.id, 'zone')}
          className="w-full text-left px-3 py-2 rounded-lg bg-slate-800/40 hover:bg-slate-700/50 mb-1">
          <div className="flex items-center gap-2"><FolderTree size={14} className="text-yellow-500/70" /><span className="text-sm text-slate-200 font-medium">{z.name}</span></div>
          <div className="text-[11px] text-slate-500 ml-5">{z.path}</div>
        </button>)}
      </div>}
      {results.computers.length > 0 && <div>
        <h3 className="text-xs font-semibold text-slate-400 mb-2 uppercase tracking-wider">{t('cz_computers')} ({results.computers.length})</h3>
        {results.computers.map(c => <button key={c.id} onClick={() => onNav(c.zone_id, 'computers', c.name)}
          className="w-full text-left px-3 py-2 rounded-lg bg-slate-800/40 hover:bg-slate-700/50 mb-1">
          <div className="flex items-center gap-2"><Monitor size={14} className="text-blue-400" /><span className="text-sm text-slate-200">{c.name}</span><span className="text-xs text-slate-500 ml-auto">{c.os_type}</span></div>
          <div className="text-[11px] text-slate-500 ml-5">{t('cz_found_in')}: {c.zone_path}</div>
        </button>)}
      </div>}
      {results.users.length > 0 && <div>
        <h3 className="text-xs font-semibold text-slate-400 mb-2 uppercase tracking-wider">{t('cz_users')} ({results.users.length})</h3>
        {results.users.map(u => <button key={u.id} onClick={() => onNav(u.zone_id, 'users')}
          className="w-full text-left px-3 py-2 rounded-lg bg-slate-800/40 hover:bg-slate-700/50 mb-1">
          <div className="flex items-center gap-2"><User size={14} className="text-cyan-400" /><span className="text-sm text-slate-200">{u.user_name}</span><span className="text-xs text-slate-500 ml-auto">UID:{u.uid}</span></div>
          <div className="text-[11px] text-slate-500 ml-5">{t('cz_found_in')}: {u.zone_path}</div>
        </button>)}
      </div>}
    </div>
  )
}

// ── Ana sayfa ────────────────────────────────────────────────

const DRAWER_KEY = 'ainew.centrify-tree-collapsed'

function stripAiHtml(s: string): string {
  if (!s.includes('<')) return s
  return s
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>/gi, '\n\n')
    .replace(/<\/li>\s*<li[^>]*>/gi, '\n- ')
    .replace(/<li[^>]*>/gi, '\n- ')
    .replace(/<\/?(ul|ol|p|div|span|strong|em|b|i|table|thead|tbody|tr|td|th)[^>]*>/gi, '')
    .replace(/<\/?[^>]+>/g, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

const CentrifyAiDrawer: React.FC<{ zoneId?: number; onClose: () => void }> = ({ zoneId, onClose }) => {
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [lines, setLines] = useState<{ role: 'user' | 'ai'; text: string }[]>([])
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight })
  }, [lines])

  const send = async () => {
    const msg = input.trim()
    if (!msg || busy) return
    setInput('')
    setLines(prev => [...prev, { role: 'user', text: msg }, { role: 'ai', text: '' }])
    setBusy(true)
    try {
      const res = await fetch(`${API_BASE_URL}/centrify-chat/stream`, {
        method: 'POST',
        headers: hdrs(),
        body: JSON.stringify({ message: msg, zone_id: zoneId || null }),
      })
      if (!res.ok || !res.body) {
        const err = await res.text().catch(() => '')
        setLines(prev => {
          const next = [...prev]
          next[next.length - 1] = { role: 'ai', text: err || `Hata: ${res.status}` }
          return next
        })
        setBusy(false)
        return
      }
      const reader = res.body.getReader()
      const dec = new TextDecoder()
      let buf = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const parts = buf.split('\n')
        buf = parts.pop() || ''
        for (const line of parts) {
          const s = line.trim()
          if (!s.startsWith('data:')) continue
          try {
            const d = JSON.parse(s.slice(5).trim())
            if (typeof d.token === 'string') {
              setLines(prev => {
                const next = [...prev]
                const last = next[next.length - 1]
                next[next.length - 1] = { role: 'ai', text: (last?.text || '') + d.token }
                return next
              })
            }
          } catch { /* ignore */ }
        }
      }
    } catch (e: any) {
      setLines(prev => {
        const next = [...prev]
        next[next.length - 1] = { role: 'ai', text: e?.message || 'Bağlantı hatası' }
        return next
      })
    }
    setBusy(false)
  }

  return (
    <div className="fixed bottom-6 right-6 z-40 w-[440px] max-w-[calc(100vw-2rem)] h-[520px] max-h-[75vh] bg-slate-900 border border-slate-700 rounded-xl shadow-2xl flex flex-col overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-700 bg-slate-800/80">
        <KeyRound size={15} className="text-purple-400" />
        <span className="text-sm font-medium text-slate-100">Centrify AI</span>
        <button onClick={onClose} className="ml-auto p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-slate-100" title="Kapat">
          <XCircle size={16} />
        </button>
      </div>
      <div ref={boxRef} className="flex-1 overflow-y-auto p-3 space-y-2 text-sm">
        {lines.length === 0 && (
          <p className="text-xs text-slate-500">Zone, rol, komut ve atamalar hakkında soru sorun.</p>
        )}
        {lines.map((l, i) => (
          <div key={i} className={`rounded-lg px-2.5 py-1.5 min-w-0 overflow-x-auto ${l.role === 'user' ? 'bg-blue-600/20 text-slate-100 ml-6 whitespace-pre-wrap' : 'bg-slate-800 text-slate-200 mr-1'}`}>
            {l.role === 'ai' ? (
              l.text
                ? <div className={chatResponseBody}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>
                      {stripAiHtml(l.text)}
                    </ReactMarkdown>
                  </div>
                : (busy && i === lines.length - 1 ? '…' : '')
            ) : (l.text)}
          </div>
        ))}
      </div>
      <form className="p-2 border-t border-slate-700 flex gap-2" onSubmit={e => { e.preventDefault(); send() }}>
        <input
          className="flex-1 bg-slate-800 border border-slate-600 rounded-md px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-purple-500"
          value={input} onChange={e => setInput(e.target.value)} placeholder="Soru yazın…" disabled={busy}
        />
        <button type="submit" disabled={busy || !input.trim()}
          className="px-2.5 py-1.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-40 text-white rounded-md">
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
        </button>
      </form>
    </div>
  )
}

export default function CentrifyPage() {
  const t = useT()
  const qc = useQueryClient()
  const [sel, setSel] = useState<TreeSelection | null>(null)
  const [searchQ, setSearchQ] = useState('')
  const [isSearching, setIsSearching] = useState(false)
  const [searchRes, setSearchRes] = useState<SearchResult | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(() => localStorage.getItem(DRAWER_KEY) !== '1')
  const [chatOpen, setChatOpen] = useState(false)
  const [ctxMenu, setCtxMenu] = useState<CtxMenu | null>(null)
  const [dialog, setDialog] = useState<{
    type: 'role' | 'command' | 'assign' | 'cmd_to_role'
    mode: 'create' | 'edit' | 'copy' | 'add' | 'remove'
    zoneId: number; item?: any; computerId?: number; computerName?: string
  } | null>(null)
  const [clipboard, setClipboard] = useState<ClipItem | null>(null)
  const [clipHint, setClipHint] = useState('')
  const [expanded, setExpanded] = useState<ExpandedMap>({})
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const tk = token()

  const toggleDrawer = useCallback(() => {
    setDrawerOpen(prev => { const n = !prev; localStorage.setItem(DRAWER_KEY, n ? '0' : '1'); return n })
  }, [])

  const { data: config } = useQuery<Config | null>({
    queryKey: ['centrify-config'],
    queryFn: async () => { const r = await fetch(api('/config'), { headers: { Authorization: `Bearer ${tk}` } }); if (!r.ok) return null; return r.json() },
  })
  const { data: zones = [], refetch: refetchZones } = useQuery<Zone[]>({ queryKey: ['centrify-zones'], queryFn: () => fetchJson('/zones'), enabled: !!config })
  const { data: syncStatus } = useQuery<SyncStatus>({ queryKey: ['centrify-sync-status'], queryFn: () => fetchJson('/sync/status'), enabled: !!config, refetchInterval: 30_000 })
  const { data: circuitStatus } = useQuery<CircuitStatus>({ queryKey: ['centrify-circuit-status'], queryFn: () => fetchJson('/circuit-status'), enabled: !!config, refetchInterval: 15_000 })

  const [syncing, setSyncing] = useState(false)
  const triggerSync = useCallback(async () => {
    setSyncing(true); try { await fetch(api('/sync/trigger'), { method: 'POST', headers: { Authorization: `Bearer ${tk}` } }); await refetchZones() } catch {} setSyncing(false)
  }, [refetchZones, tk])

  // Search
  const doSearch = useCallback(async (q: string) => {
    if (q.length < 2) { setSearchRes(null); setIsSearching(false); return }
    setIsSearching(true)
    try { const r = await fetch(api(`/search?q=${encodeURIComponent(q)}&limit=30`), { headers: { Authorization: `Bearer ${tk}` } }); if (r.ok) setSearchRes(await r.json()) } catch {}
    setIsSearching(false)
  }, [tk])

  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current)
    if (!searchQ || searchQ.length < 2) { setSearchRes(null); return }
    searchTimer.current = setTimeout(() => doSearch(searchQ), 350)
    return () => { if (searchTimer.current) clearTimeout(searchTimer.current) }
  }, [searchQ, doSearch])

  // Arama sonucundan navigasyon
  const handleSearchNav = useCallback((zoneId: number, nodeType: VNodeType, itemName?: string) => {
    const zone = zones.find(z => z.id === zoneId)
    if (!zone) return
    const newExp: ExpandedMap = { ...expanded }
    const openPath = (zid: number) => {
      const z = zones.find(zz => zz.id === zid)
      if (!z) return
      newExp[eKey(z.id, 'zone')] = true
      if (z.parent_zone_id) {
        const parent = zones.find(zz => zz.id === z.parent_zone_id)
        if (parent) {
          newExp[eKey(parent.id, 'zone')] = true
          newExp[eKey(parent.id, 'child_zones')] = true
          openPath(parent.id)
        }
      }
    }
    openPath(zoneId)
    if (nodeType === 'computers') newExp[eKey(zoneId, 'computers')] = true
    else if (nodeType === 'users') newExp[eKey(zoneId, 'unix_data')] = true
    setExpanded(newExp)
    setSel({ zoneId, nodeType, zoneName: zone.name, itemName })
    setSearchQ(''); setSearchRes(null)
  }, [zones, expanded])

  // Context menu actions
  const handleCtxAction = useCallback((action: string) => {
    if (!ctxMenu) return
    const { zoneId, nodeType, item, computerId } = ctxMenu

    if (action === 'assign_role') {
      const cid = computerId ?? (nodeType === 'computer_item' ? item?.id : undefined)
      const computerName = item?.name || sel?.itemName
      setDialog({ type: 'assign', mode: 'create', zoneId, computerId: cid, computerName })
    }
    else if (action === 'add_role') setDialog({ type: 'role', mode: 'create', zoneId })
    else if (action === 'new_command') setDialog({ type: 'command', mode: 'create', zoneId })
    else if (action === 'edit' && item) {
      if (nodeType === 'role_definitions' || nodeType === 'commands') {
        setDialog({ type: nodeType === 'role_definitions' ? 'role' : 'command', mode: 'edit', zoneId, item })
      }
    }
    else if (action === 'copy' && item) {
      const kind = nodeType === 'role_definitions' ? 'role' : 'command'
      setClipboard({ kind, sourceZoneId: zoneId, item })
      setClipHint(`${item.name}`)
    }
    else if (action === 'paste' && clipboard) {
      if (clipboard.kind === 'role' && nodeType === 'role_definitions') {
        setDialog({ type: 'role', mode: 'copy', zoneId, item: clipboard.item })
      } else if (clipboard.kind === 'command' && nodeType === 'commands') {
        setDialog({ type: 'command', mode: 'copy', zoneId, item: clipboard.item })
      }
    }
    else if (action === 'add_to_role' && item) {
      setDialog({ type: 'cmd_to_role', mode: 'add', zoneId, item })
    }
    else if (action === 'remove_from_role' && item) {
      setDialog({ type: 'cmd_to_role', mode: 'remove', zoneId, item })
    }
    else if (action === 'delete' && item) {
      const confirmMsg = t('cz_confirm_delete')
      if (confirm(`${confirmMsg}\n\n${item.name}`)) {
        fetch(api(nodeType === 'commands' ? '/commands/delete' : '/operations'), {
          method: 'POST', headers: hdrs(),
          body: JSON.stringify(
            nodeType === 'commands'
              ? { zone_id: zoneId, command_name: item.name, reason: `Delete ${item.name}` }
              : { operation_type: 'delete_role', zone_id: zoneId, desired_state: { name: item.name }, reason: `Delete ${item.name}` }
          ),
        }).then(() => {
          qc.invalidateQueries({ queryKey: nodeType === 'commands' ? ['centrify-commands', zoneId] : ['centrify-roles', zoneId] })
        })
      }
    }
    else if (action === 'refresh') {
      qc.invalidateQueries({ queryKey: ['centrify-roles', zoneId] })
      qc.invalidateQueries({ queryKey: ['centrify-commands', zoneId] })
      qc.invalidateQueries({ queryKey: ['centrify-assignments', zoneId] })
      qc.invalidateQueries({ queryKey: ['centrify-computers', zoneId] })
      qc.invalidateQueries({ queryKey: ['centrify-ops-pending'] })
    }
  }, [ctxMenu, qc, t, sel, clipboard])

  const handleDialogDone = useCallback(() => {
    if (!dialog) return
    qc.invalidateQueries({ queryKey: ['centrify-roles', dialog.zoneId] })
    qc.invalidateQueries({ queryKey: ['centrify-roles-with-parents', dialog.zoneId] })
    qc.invalidateQueries({ queryKey: ['centrify-commands', dialog.zoneId] })
    qc.invalidateQueries({ queryKey: ['centrify-assignments', dialog.zoneId] })
    qc.invalidateQueries({ queryKey: ['centrify-ops-pending'] })
  }, [dialog, qc])

  const handleTreeCtx = useCallback((e: React.MouseEvent, zoneId: number, nodeType: VNodeType, item?: any, computerId?: number) => {
    setCtxMenu({ x: e.clientX, y: e.clientY, zoneId, nodeType, item, computerId })
  }, [])

  if (config === null) return (
    <div className="flex flex-col items-center justify-center h-[calc(100vh-56px)] text-slate-500">
      <KeyRound size={48} className="mb-4 text-slate-700" />
      <h3 className="text-lg font-medium text-slate-400 mb-2">{t('cz_not_configured')}</h3>
      <p className="text-sm mb-4">{t('cz_go_integrations')}</p>
      <Link to="/integrations/centrify" className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-sm text-white rounded-lg"><KeyRound size={14} /> {t('cz_int_title')}</Link>
    </div>
  )
  if (config === undefined) return <Spin />

  const roots = rootZones(zones)

  const renderContent = () => {
    if (searchRes) return <SearchResults results={searchRes} q={searchQ} onNav={handleSearchNav} />
    if (!sel) return (
      <div className="flex-1 flex flex-col items-center justify-center text-slate-500">
        <KeyRound size={48} className="mb-4 text-slate-700" />
        <h3 className="text-lg font-medium text-slate-400 mb-1">Centrify Zone Management</h3>
        <p className="text-sm">{t('cz_select_node')}</p>
        {!zones.length && config && <button onClick={triggerSync} disabled={syncing} className="mt-4 flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-sm text-white rounded-lg disabled:opacity-50">
          {syncing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Sync
        </button>}
      </div>
    )
    switch (sel.nodeType) {
      case 'computers': return (
        <ComputersPanel
          zoneId={sel.zoneId} zoneName={sel.zoneName}
          onOpenComputer={c => {
            setExpanded(prev => ({
              ...prev,
              [eKey(sel.zoneId, 'computers')]: true,
              [eKey(sel.zoneId, 'computer_item', c.id)]: true,
            }))
            setSel({ zoneId: sel.zoneId, nodeType: 'computer_item', zoneName: sel.zoneName, itemId: c.id, itemName: c.name })
          }}
          onCtxFolder={e => handleTreeCtx(e, sel.zoneId, 'computers')}
          onCtxComputer={(e, c) => handleTreeCtx(e, sel.zoneId, 'computer_item', c)}
        />
      )
      case 'computer_item': return sel.itemId ? (
        <ComputerExplorer
          zoneId={sel.zoneId} zoneName={sel.zoneName}
          computerId={sel.itemId} computerName={sel.itemName || ''}
          onSel={s => {
            setExpanded(prev => ({ ...prev, [eKey(sel.zoneId, 'computer_item', sel.itemId)]: true }))
            setSel(s)
          }}
          onCtx={(e, nt, cid) => handleTreeCtx(e, sel.zoneId, nt, undefined, cid)}
        />
      ) : <Empty text={t('cz_no_data')} />
      case 'users': case 'local_users': case 'unix_data': return <UsersPanel zoneId={sel.zoneId} />
      case 'role_definitions': return <RolesPanel zoneId={sel.zoneId} onRowCtx={(e, r) => handleTreeCtx(e, sel.zoneId, 'role_definitions', r)} />
      case 'commands': return <CommandsPanel zoneId={sel.zoneId} onRowCtx={(e, c) => handleTreeCtx(e, sel.zoneId, 'commands', c)} />
      case 'role_assignments':
        return (
          <AssignmentsPanel
            zoneId={sel.zoneId} computerId={sel.itemId} computerName={sel.itemName}
            onAssign={() => setDialog({ type: 'assign', mode: 'create', zoneId: sel.zoneId, computerId: sel.itemId, computerName: sel.itemName })}
            onCtx={e => handleTreeCtx(e, sel.zoneId, 'role_assignments', undefined, sel.itemId)}
          />
        )
      case 'computer_roles': return <GenericPanel zoneId={sel.zoneId} endpoint="computer-roles" />
      case 'zone': case 'authorization': case 'child_zones': return <ZoneOverview zoneId={sel.zoneId} />
      default: return <Empty text={t('cz_no_data')} />
    }
  }

  return (
    <div className="flex flex-col flex-1 h-full min-h-0 overflow-hidden">
      {circuitStatus?.open && (
        <div className="bg-red-500/10 border-b border-red-500/30 px-4 py-2 flex items-center gap-2 text-sm text-red-300">
          <AlertTriangle size={16} className="text-red-400" /><span className="font-medium">Circuit breaker open</span> — All Centrify operations suspended.
        </div>
      )}

      <div className="flex flex-1 min-h-0">
        {/* Sol panel */}
        <div className={`border-r border-slate-700/50 flex flex-col bg-slate-900/30 transition-all duration-200 ${drawerOpen ? 'w-72' : 'w-10'}`}>
          {drawerOpen ? <>
            <div className="p-2.5 border-b border-slate-700/50">
              <div className="flex items-center gap-2 mb-2">
                <FolderTree size={15} className="text-slate-400" />
                <span className="text-xs font-medium text-slate-300">{t('cz_tree_title')}</span>
                <div className="ml-auto flex items-center gap-0.5">
                  <button onClick={triggerSync} disabled={syncing} title="Sync" className="p-1 rounded hover:bg-slate-700/50 text-slate-500 hover:text-slate-300 disabled:opacity-50">
                    <RefreshCw size={13} className={syncing ? 'animate-spin' : ''} />
                  </button>
                  <button onClick={toggleDrawer} title={t('cz_tree_collapse')} className="p-1 rounded hover:bg-slate-700/50 text-slate-500 hover:text-slate-300">
                    <PanelLeftClose size={13} />
                  </button>
                </div>
              </div>
              <div className="relative">
                <Search size={13} className="absolute left-2 top-[7px] text-slate-500" />
                <input className="w-full bg-slate-800 border border-slate-700 rounded-md pl-7 pr-3 py-1 text-xs text-slate-300 placeholder-slate-600 focus:border-blue-500 outline-none"
                  placeholder={t('cz_tree_search')} value={searchQ} onChange={e => setSearchQ(e.target.value)} />
                {isSearching && <Loader2 size={11} className="absolute right-2 top-2 animate-spin text-slate-500" />}
              </div>
            </div>
            <div className="flex-1 overflow-y-auto py-0.5">
              {!zones.length ? <div className="px-3 py-8 text-center text-xs text-slate-500">No zones. Sync required.</div>
                : roots.map(z => <ZoneTreeNode key={z.id} zone={z} allZones={zones} sel={sel} onSel={setSel} depth={0} t={t} onCtx={handleTreeCtx} expanded={expanded} setExpanded={setExpanded} />)
              }
            </div>
            <div className="p-2.5 border-t border-slate-700/50 space-y-0.5 text-[10.5px] shrink-0">
              <div className="flex items-center gap-1 text-slate-500"><span className={`w-1.5 h-1.5 rounded-full ${circuitStatus?.open ? 'bg-red-400' : 'bg-green-400'}`} />{circuitStatus?.open ? 'Circuit open' : 'Connected'}</div>
              <div className="text-slate-600">{syncStatus?.last_synced_at ? `Last sync: ${new Date(syncStatus.last_synced_at).toLocaleTimeString('tr-TR')}` : 'Not synced'}</div>
              <div className="text-slate-600">{zones.length} zones</div>
              {clipboard && (
                <div className="text-blue-400/80 truncate" title={clipHint}>
                  {t('cz_clipboard')}: {clipboard.kind === 'role' ? t('cz_role_definitions') : t('cz_commands')} / {clipHint}
                </div>
              )}
            </div>
          </> : <button onClick={toggleDrawer} title={t('cz_tree_title')} className="flex flex-col items-center gap-2 py-3 text-slate-500 hover:text-slate-300 w-full">
            <PanelLeft size={15} /><FolderTree size={13} />
          </button>}
        </div>

        {/* Sağ panel */}
        <div className="flex-1 flex flex-col min-w-0">
          {sel && !searchRes && (
            <div className="px-4 py-2.5 border-b border-slate-700/50 bg-slate-900/20">
              <div className="flex items-center gap-2">
                <span className="text-blue-400">{ICON[sel.nodeType]}</span>
                <h2 className="text-sm font-semibold text-slate-100">
                  {sel.zoneName}
                  {sel.nodeType !== 'zone' && <span className="text-slate-500 font-normal"> / {t(LABEL_KEY[sel.nodeType])}</span>}
                  {sel.itemName && <span className="text-slate-400 font-normal"> / {sel.itemName}</span>}
                </h2>
              </div>
            </div>
          )}
          {searchRes && (
            <div className="px-4 py-2.5 border-b border-slate-700/50 bg-slate-900/20">
              <div className="flex items-center gap-2">
                <Search size={15} className="text-blue-400" />
                <h2 className="text-sm font-semibold text-slate-100">{t('cz_search_results')}</h2>
                <span className="text-xs text-slate-500 ml-1">"{searchQ}"</span>
              </div>
            </div>
          )}
          <div className="flex-1 overflow-y-auto min-h-0">{renderContent()}</div>
        </div>
      </div>

      {/* Context menu */}
      {ctxMenu && <ContextMenu ctx={ctxMenu} t={t} clipboard={clipboard} onAction={handleCtxAction} onClose={() => setCtxMenu(null)} />}

      {/* Diyaloglar */}
      {dialog?.type === 'role' && <RoleDialog zoneId={dialog.zoneId} role={dialog.item} mode={dialog.mode === 'copy' || dialog.mode === 'edit' || dialog.mode === 'create' ? dialog.mode : 'create'} onClose={() => setDialog(null)} onDone={handleDialogDone} />}
      {dialog?.type === 'command' && <CommandDialog zoneId={dialog.zoneId} cmd={dialog.item} mode={dialog.mode === 'copy' || dialog.mode === 'edit' || dialog.mode === 'create' ? dialog.mode : 'create'} onClose={() => setDialog(null)} onDone={handleDialogDone} />}
      {dialog?.type === 'assign' && <AssignRoleDialog zoneId={dialog.zoneId} computerId={dialog.computerId} computerName={dialog.computerName} onClose={() => setDialog(null)} onDone={handleDialogDone} />}
      {dialog?.type === 'cmd_to_role' && dialog.item && (
        <CommandToRoleDialog zoneId={dialog.zoneId} cmd={dialog.item} mode={dialog.mode === 'remove' ? 'remove' : 'add'}
          onClose={() => setDialog(null)} onDone={handleDialogDone} />
      )}

      {/* AI */}
      {chatOpen
        ? <CentrifyAiDrawer zoneId={sel?.zoneId} onClose={() => setChatOpen(false)} />
        : (
          <button onClick={() => setChatOpen(true)}
            className="fixed bottom-6 right-6 z-30 w-12 h-12 rounded-full bg-purple-600 hover:bg-purple-500 text-white shadow-lg flex items-center justify-center hover:scale-110 transition-transform"
            title="Centrify AI"><KeyRound size={20} /></button>
        )}
    </div>
  )
}
