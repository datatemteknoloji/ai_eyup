/**
 * OpenShift Explorer — Atlas tarzı bilgi mimarisi (küme → proje → sol menü),
 * ainew API + stil. Atlas’a runtime bağlantısı yok.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import {
  Boxes, LayoutGrid, FolderOpen, Network, Database, Layers, Stethoscope,
  Share2, Globe, HardDrive, Server, Settings2, FileCode, MonitorPlay,
  HeartPulse, AlertTriangle, RefreshCw, Info, ChevronRight, ChevronLeft, ArrowRightLeft,
} from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import OcpProjectsPanel from '../components/openshift/OcpProjectsPanel'
import OcpResourceList from '../components/openshift/OcpResourceList'
import OcpOverviewPanel from '../components/openshift/OcpOverviewPanel'
import OcpStoragePanel from '../components/openshift/OcpStoragePanel'
import OcpTopologyPanel from '../components/openshift/OcpTopologyPanel'
import OcpPodsPanel from '../components/openshift/OcpPodsPanel'
import OcpMtvPanel from '../components/openshift/OcpMtvPanel'
import OcpClusterManageMenu from '../components/openshift/OcpClusterManageMenu'
import OcpProjectPicker from '../components/openshift/OcpProjectPicker'
import OcpVmsPanel from '../components/openshift/OcpVmsPanel'
import {
  NEEDS_PROJECT, SECTION_KIND, type OcpCluster, type OcpSection,
} from '../components/openshift/ocpTypes'
import { useT } from '../i18n/LocaleProvider'
import type { TranslationKey } from '../i18n/messages'

const VALID: OcpSection[] = [
  'genel', 'projeler', 'topoloji', 'deployments', 'statefulsets', 'daemonsets',
  'pods', 'services', 'routes', 'depolama', 'pvc', 'pv', 'configmaps',
  'kaynaklar', 'vms', 'tasima', 'saglik', 'riskler',
]

const SECTION_HELP_KEYS: Partial<Record<OcpSection, TranslationKey>> = {
  genel: 'ocp_help_overview',
  saglik: 'ocp_help_health',
  topoloji: 'ocp_help_topology',
  depolama: 'ocp_help_storage',
  vms: 'ocp_help_vms',
  tasima: 'ocp_help_mtv',
  kaynaklar: 'ocp_help_resources',
  projeler: 'ocp_help_projects',
  riskler: 'ocp_help_risks',
  pods: 'ocp_help_pods',
}

function parseSection(raw: string | null): OcpSection | null {
  if (raw && VALID.includes(raw as OcpSection)) return raw as OcpSection
  return null
}

export default function OpenShiftExplorer({ initialSection = 'genel' }: { initialSection?: OcpSection }) {
  const t = useT()
  const [searchParams, setSearchParams] = useSearchParams()
  const sectionFromUrl = parseSection(searchParams.get('section')) || parseSection(searchParams.get('tab'))
  const [section, setSection] = useState<OcpSection>(sectionFromUrl || initialSection)
  const [clusterId, setClusterId] = useState<number | null>(null)
  const [project, setProject] = useState(searchParams.get('project') || '')
  const [projSearch, setProjSearch] = useState('')
  const [navCollapsed, setNavCollapsed] = useState(() => {
    try { return localStorage.getItem('ainew_ocp_nav_collapsed') === '1' } catch { return false }
  })
  const toggleNav = () => {
    setNavCollapsed((v) => {
      const next = !v
      try { localStorage.setItem('ainew_ocp_nav_collapsed', next ? '1' : '0') } catch { /* ignore */ }
      return next
    })
  }

  useEffect(() => {
    const next = sectionFromUrl || initialSection
    setSection(next)
  }, [sectionFromUrl, initialSection])

  const go = (s: OcpSection, opts?: { project?: string }) => {
    setSection(s)
    const p = new URLSearchParams(searchParams)
    p.set('section', s)
    const proj = opts?.project !== undefined ? opts.project : project
    if (proj) p.set('project', proj)
    else p.delete('project')
    if (opts?.project !== undefined) setProject(opts.project)
    setSearchParams(p, { replace: true })
  }

  const { data: clusters = [], isLoading: clustersLoading } = useQuery<OcpCluster[]>({
    queryKey: ['openshift-clusters'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters`)
      if (!r.ok) return []
      const body = await r.json()
      return Array.isArray(body?.clusters) ? body.clusters : []
    },
    refetchInterval: 60_000,
  })

  useEffect(() => {
    if (!clusters.length) {
      setClusterId(null)
      return
    }
    if (!clusterId || !clusters.some((c) => c.id === clusterId)) {
      setClusterId(clusters[0].id)
    }
  }, [clusters, clusterId])

  const { data: projectsData } = useQuery({
    queryKey: ['ocp-explorer-projects-select', clusterId, projSearch],
    queryFn: async () => {
      const params = new URLSearchParams({
        cluster_id: String(clusterId),
        include_system: 'true',
        page: '1',
        page_size: '1000',
      })
      const q = projSearch.trim()
      if (q.length >= 2) params.set('q', q)
      const r = await fetch(`${API_BASE_URL}/openshift/projects?${params}`)
      if (!r.ok) return { projects: [] }
      return r.json()
    },
    enabled: !!clusterId,
    placeholderData: keepPreviousData,
  })
  const projects = projectsData?.projects || []

  // Tek kullanıcı projesi varsa otomatik seç — sürtünmeyi azaltır
  useEffect(() => {
    if (!clusterId || project || projSearch.trim()) return
    const users = projects.filter((p: any) => !p.is_system)
    if (users.length === 1) {
      const name = users[0].name as string
      setProject(name)
      const p = new URLSearchParams(searchParams)
      p.set('project', name)
      setSearchParams(p, { replace: true })
    }
  }, [clusterId, projects, project, projSearch, searchParams, setSearchParams])

  const { data: overview, isFetching: ovFetching, refetch: refetchOv } = useQuery({
    queryKey: ['openshift-overview', clusterId],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/overview`)
      if (!r.ok) throw new Error('overview')
      return r.json()
    },
    enabled: !!clusterId,
    refetchInterval: 60_000,
  })

  const { data: opHealth } = useQuery({
    queryKey: ['openshift-op-health', clusterId],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/operators-health`)
      if (!r.ok) throw new Error('op health')
      return r.json()
    },
    enabled: !!clusterId && (section === 'saglik' || section === 'genel'),
  })

  const { data: risksData } = useQuery({
    queryKey: ['openshift-risks', clusterId],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/risks?limit=100&cluster_id=${clusterId}`)
      if (!r.ok) return { risks: [] }
      return r.json()
    },
    enabled: !!clusterId && section === 'riskler',
  })

  const hasKubevirt = (overview?.operators || []).some(
    (o: any) => o.group === 'kubevirt.io' && o.installed,
  )

  const NAV = useMemo(() => {
    const groups: { group?: string; items: { id: OcpSection; label: string; icon: any }[] }[] = [
      {
        items: [
          { id: 'genel', label: t('ocp_nav_overview'), icon: LayoutGrid },
          { id: 'projeler', label: t('ocp_projects'), icon: FolderOpen },
          { id: 'topoloji', label: t('ocp_nav_topology'), icon: Network },
        ],
      },
      {
        group: t('ocp_nav_workloads'),
        items: [
          { id: 'deployments', label: 'Deployments', icon: Boxes },
          { id: 'statefulsets', label: 'StatefulSets', icon: Database },
          { id: 'daemonsets', label: 'DaemonSets', icon: Layers },
          { id: 'pods', label: t('ocp_nav_pod_log'), icon: Stethoscope },
        ],
      },
      {
        group: t('ocp_nav_network'),
        items: [
          { id: 'services', label: 'Services', icon: Share2 },
          { id: 'routes', label: 'Routes', icon: Globe },
        ],
      },
      {
        group: t('ocp_nav_storage'),
        items: [
          { id: 'depolama', label: t('ocp_nav_storage_genel'), icon: HardDrive },
          { id: 'pvc', label: 'PVC', icon: Database },
          { id: 'pv', label: 'PersistentVolumes', icon: Server },
        ],
      },
      {
        group: t('ocp_nav_config'),
        items: [
          { id: 'configmaps', label: 'ConfigMaps', icon: Settings2 },
          { id: 'kaynaklar', label: t('ocp_nav_all_res'), icon: FileCode },
        ],
      },
      {
        group: t('ocp_nav_virt'),
        items: [
          ...(hasKubevirt ? [{ id: 'vms' as OcpSection, label: t('ocp_nav_vms'), icon: MonitorPlay }] : []),
          { id: 'tasima' as OcpSection, label: t('ocp_nav_mtv'), icon: ArrowRightLeft },
        ],
      },
      {
        group: 'Cluster',
        items: [
          { id: 'saglik', label: t('ocp_nav_health'), icon: HeartPulse },
          { id: 'riskler', label: t('ocp_nav_risks'), icon: AlertTriangle },
        ],
      },
    ]
    return groups.filter((g) => g.items.length > 0)
  }, [hasKubevirt, t])

  const active: OcpSection = NAV.flatMap((g) => g.items.map((i) => i.id)).includes(section)
    ? section
    : 'genel'

  const current = clusters.find((c) => c.id === clusterId)
  const fixedKind = active === 'pods' ? undefined : SECTION_KIND[active]

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Modül çubuğu */}
      <div className="px-4 sm:px-5 pt-4 pb-3 border-b border-white/[0.06] bg-cyber-card/40">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2.5">
            <span className="grid place-items-center w-9 h-9 rounded-lg bg-rose-500/12 ring-1 ring-inset ring-rose-500/20">
              <Boxes size={18} className="text-rose-400" />
            </span>
            <div>
              <h1 className="text-base font-bold text-slate-100 leading-tight">{t('nav_openshift')}</h1>
              <p className="text-[11px] text-slate-500">{t('ocp_subtitle')}</p>
            </div>
          </div>

          {clusters.length > 0 && (
            <>
              <span className="w-px h-8 bg-white/[0.08] hidden sm:block" />
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[11px] text-slate-500">Cluster</span>
                <select
                  className="rounded-lg border border-white/[0.08] bg-cyber-deep/80 text-sm text-slate-200 py-1.5 px-2 w-52"
                  value={clusterId ?? ''}
                  onChange={(e) => {
                    setClusterId(Number(e.target.value))
                    setProject('')
                    setProjSearch('')
                  }}
                >
                  {clusters.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
                {(overview?.version || current?.version) && (
                  <span className="text-[10px] px-2 py-1 rounded-lg bg-white/[0.06] text-slate-400 font-mono">
                    k8s {overview?.version || current?.version}
                  </span>
                )}
                <span className="text-[11px] text-slate-500 ml-1">{t('ocp_project')}</span>
                <OcpProjectPicker
                  projects={projects}
                  value={project}
                  disabled={!clusterId}
                  onQuery={setProjSearch}
                  onChange={(v) => {
                    setProject(v)
                    const p = new URLSearchParams(searchParams)
                    if (v) p.set('project', v)
                    else p.delete('project')
                    setSearchParams(p, { replace: true })
                  }}
                />
              </div>
            </>
          )}

          <div className="ml-auto flex items-center gap-2">
            {clusterId && (
              <button
                type="button"
                onClick={() => refetchOv()}
                className="text-xs px-2.5 py-1.5 rounded-lg border border-white/[0.08] text-slate-300 hover:bg-white/[0.04] inline-flex items-center gap-1.5"
              >
                <RefreshCw size={12} className={ovFetching ? 'animate-spin' : ''} /> {t('refresh_action')}
              </button>
            )}
            <OcpClusterManageMenu
              cluster={current}
              onCreated={(id) => setClusterId(id)}
              onDeleted={() => setClusterId(null)}
            />
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-4 sm:px-5 space-y-4">
        {clustersLoading && (
          <div className="text-sm text-slate-500 flex items-center gap-2 py-12 justify-center">
            <RefreshCw size={14} className="animate-spin" /> {t('loading')}
          </div>
        )}

        {!clustersLoading && clusters.length === 0 && (
          <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-10 text-center">
            <Boxes size={36} className="mx-auto mb-3 text-slate-600" />
            <p className="text-sm text-slate-300">{t('ocp_no_cluster')}</p>
            <p className="text-xs text-slate-500 mt-2 max-w-md mx-auto">
              {t('ocp_no_cluster_hint')}
            </p>
            <Link
              to="/integrations/openshift"
              className="inline-flex mt-4 text-xs px-4 py-2 rounded-lg bg-rose-600/90 text-white hover:bg-rose-500"
            >
              {t('ocp_go_integrations')}
            </Link>
          </div>
        )}

        {clusterId && overview && (
          <div className="flex gap-4 items-start">
            <nav
              className={`hidden md:flex flex-col flex-shrink-0 sticky top-2 self-start rounded-xl border border-white/[0.06] bg-cyber-card/50 overflow-hidden transition-[width] duration-300 ${
                navCollapsed ? 'w-12' : 'w-52'
              }`}
            >
              <button
                type="button"
                onClick={toggleNav}
                title={navCollapsed ? t('ocp_nav_expand') : t('ocp_nav_collapse')}
                className="flex items-center justify-center h-9 border-b border-white/[0.06] text-slate-500 hover:text-slate-200 hover:bg-white/[0.04]"
              >
                {navCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
              </button>
              <div className="py-2 space-y-3 overflow-y-auto max-h-[calc(100vh-12rem)]">
              {NAV.map((g, gi) => (
                <div key={gi}>
                  {g.group && !navCollapsed && (
                    <p className="text-[10px] uppercase tracking-wide text-slate-600 px-2 mb-1">{g.group}</p>
                  )}
                  <div className="space-y-0.5">
                    {g.items.map((it) => {
                      const Icon = it.icon
                      const on = active === it.id
                      return (
                        <button
                          key={it.id}
                          type="button"
                          onClick={() => go(it.id)}
                          title={it.label}
                          className={`w-full flex items-center gap-2 py-1.5 rounded-lg text-xs transition-colors text-left ${
                            navCollapsed ? 'justify-center px-0' : 'px-2.5'
                          } ${
                            on
                              ? 'bg-rose-500/12 text-rose-300 font-medium'
                              : 'text-slate-400 hover:text-slate-200 hover:bg-white/[0.04]'
                          }`}
                        >
                          <Icon size={14} className="flex-shrink-0" />
                          {!navCollapsed && <span className="truncate">{it.label}</span>}
                        </button>
                      )
                    })}
                  </div>
                </div>
              ))}
              </div>
            </nav>

            {/* mobil section seçici */}
            <div className="md:hidden w-full mb-2">
              <select
                className="w-full rounded-lg border border-white/[0.08] bg-cyber-deep text-sm text-slate-200 py-2 px-3"
                value={active}
                onChange={(e) => go(e.target.value as OcpSection)}
              >
                {NAV.flatMap((g) =>
                  g.items.map((it) => (
                    <option key={it.id} value={it.id}>
                      {g.group ? `${g.group} · ` : ''}{it.label}
                    </option>
                  )),
                )}
              </select>
            </div>

            <div className="flex-1 min-w-0 space-y-4">
              {NEEDS_PROJECT.includes(active) && !project && (
                <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2">
                  <Info size={14} className="text-amber-400 flex-shrink-0" />
                  <p className="text-[11px] text-amber-100/80">{t('ocp_need_project')}</p>
                </div>
              )}

              {SECTION_HELP_KEYS[active] && (
                <div className="flex items-start gap-2 rounded-lg border border-sky-500/20 bg-sky-500/10 px-3 py-2">
                  <Info size={14} className="text-sky-400 mt-px flex-shrink-0" />
                  <p className="text-[11px] text-sky-100/80 leading-relaxed">{t(SECTION_HELP_KEYS[active]!)}</p>
                </div>
              )}

              {active === 'genel' && overview && (
                <OcpOverviewPanel overview={overview} onGoMtv={() => go('tasima')} />
              )}

              {active === 'projeler' && (
                <OcpProjectsPanel
                  clusterId={clusterId}
                  selected={project}
                  onSelect={(ns) => go('deployments', { project: ns })}
                />
              )}

              {active === 'topoloji' && (
                <OcpTopologyPanel
                  clusterId={clusterId}
                  project={project}
                  onPickProject={() => go('projeler')}
                />
              )}

              {active === 'depolama' && (
                <OcpStoragePanel clusterId={clusterId} />
              )}

              {active === 'pods' && (
                <OcpPodsPanel
                  clusterId={clusterId}
                  project={project}
                  onPickProject={() => go('projeler')}
                />
              )}

              {active === 'tasima' && clusterId && (
                <OcpMtvPanel clusterId={clusterId} overview={overview} />
              )}

              {active === 'saglik' && opHealth && (
                <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4 space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="text-sm text-white font-medium">ClusterOperator / MCP</div>
                    <span className="text-xs uppercase text-slate-400">{opHealth.overall}</span>
                  </div>
                  <div className="text-xs text-slate-400">
                    {t('ocp_version', { v: opHealth.version || '—' })}
                    {opHealth.updating ? ` · ${t('ocp_updating', { msg: opHealth.update_message || '' })}` : ''}
                  </div>
                  {(opHealth.operators?.degraded || []).length > 0 && (
                    <div className="space-y-1 pt-2">
                      {(opHealth.operators.degraded || []).slice(0, 12).map((d: any) => (
                        <div key={d.name} className="text-xs text-red-300">
                          {d.name}: {d.reason || d.message}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {active === 'riskler' && (
                <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4 space-y-2">
                  <div className="text-sm text-white font-medium mb-2">{t('ocp_risk_pods')}</div>
                  {(risksData?.risks || []).length === 0 && (
                    <div className="text-sm text-slate-500 py-6 text-center">{t('ocp_no_risks')}</div>
                  )}
                  {(risksData?.risks || []).slice(0, 50).map((w: any) => (
                    <div
                      key={`${w.project}/${w.name}`}
                      className="flex items-center gap-2 text-xs border-b border-white/[0.04] py-2"
                    >
                      <AlertTriangle size={12} className="text-amber-400 flex-shrink-0" />
                      <span className="text-slate-200 truncate">{w.name}</span>
                      <span className="text-slate-500">{w.project}</span>
                      <span className="text-red-300 ml-auto">{w.status}</span>
                      <span className="text-slate-600">rst {w.restart_count}</span>
                    </div>
                  ))}
                </div>
              )}

              {fixedKind && (
                <OcpResourceList
                  clusterId={clusterId}
                  kind={fixedKind}
                  namespace={project}
                  onPickProject={() => go('projeler')}
                  title={
                    active === 'pvc' ? 'PersistentVolumeClaims'
                      : active === 'pv' ? 'PersistentVolumes'
                        : active.charAt(0).toUpperCase() + active.slice(1)
                  }
                  namespaced={active !== 'pv'}
                />
              )}

              {active === 'kaynaklar' && (
                <OcpResourceList
                  clusterId={clusterId}
                  kind="deployments"
                  namespace={project}
                  onPickProject={() => go('projeler')}
                  title={t('ocp_explorer_title')}
                  namespaced
                />
              )}

              {active === 'vms' && clusterId && <OcpVmsPanel clusterId={clusterId} />}

              {/* AIOps kısayolları */}
              <div className="flex flex-wrap gap-2 pt-2 text-[11px] text-slate-500">
                <Link to="/openshift/ops" className="inline-flex items-center gap-1 text-rose-300/80 hover:underline">
                  {t('nav_command_center')} <ChevronRight size={12} />
                </Link>
                <Link to="/openshift/events" className="inline-flex items-center gap-1 text-rose-300/80 hover:underline">
                  {t('nav_events')} <ChevronRight size={12} />
                </Link>
                <Link to="/openshift/chat" className="inline-flex items-center gap-1 text-rose-300/80 hover:underline">
                  {t('nav_assistant')} <ChevronRight size={12} />
                </Link>
              </div>
            </div>
          </div>
        )}

        {clusterId && !overview && ovFetching && (
          <div className="text-sm text-slate-500 flex items-center gap-2 py-12 justify-center">
            <RefreshCw size={14} className="animate-spin" /> {t('ocp_cluster_query')}
          </div>
        )}
      </div>
    </div>
  )
}
