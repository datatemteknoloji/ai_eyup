/**
 * OpenShift Explorer — Atlas tarzı bilgi mimarisi (küme → proje → sol menü),
 * ainew API + stil. Atlas’a runtime bağlantısı yok.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Boxes, LayoutGrid, FolderOpen, Network, Database, Layers, Stethoscope,
  Share2, Globe, HardDrive, Server, Settings2, FileCode, MonitorPlay,
  HeartPulse, AlertTriangle, RefreshCw, Info, Terminal, ChevronRight, ArrowRightLeft,
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
import OcpVmAdminActions from '../components/openshift/OcpVmAdminActions'
import {
  NEEDS_PROJECT, SECTION_HELP, SECTION_KIND, type OcpCluster, type OcpSection,
} from '../components/openshift/ocpTypes'

const VALID: OcpSection[] = [
  'genel', 'projeler', 'topoloji', 'deployments', 'statefulsets', 'daemonsets',
  'pods', 'services', 'routes', 'depolama', 'pvc', 'pv', 'configmaps',
  'kaynaklar', 'vms', 'tasima', 'saglik', 'riskler',
]

function parseSection(raw: string | null): OcpSection | null {
  if (raw && VALID.includes(raw as OcpSection)) return raw as OcpSection
  return null
}

function openVmConsole(clusterId: number, namespace: string, name: string) {
  const title = encodeURIComponent(`${namespace}/${name}`)
  const url =
    `/openshift/vms/${clusterId}/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/console?title=${title}`
  window.open(url, `ocp-console-${namespace}-${name}`, 'width=1100,height=720')
}

export default function OpenShiftExplorer({ initialSection = 'genel' }: { initialSection?: OcpSection }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const sectionFromUrl = parseSection(searchParams.get('section')) || parseSection(searchParams.get('tab'))
  const [section, setSection] = useState<OcpSection>(sectionFromUrl || initialSection)
  const [clusterId, setClusterId] = useState<number | null>(null)
  const [project, setProject] = useState(searchParams.get('project') || '')

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
    queryKey: ['ocp-explorer-projects-select', clusterId],
    queryFn: async () => {
      const params = new URLSearchParams({
        cluster_id: String(clusterId),
        include_system: 'true',
        page: '1',
        page_size: '200',
      })
      const r = await fetch(`${API_BASE_URL}/openshift/projects?${params}`)
      if (!r.ok) return { projects: [] }
      return r.json()
    },
    enabled: !!clusterId,
  })
  const projects = projectsData?.projects || []

  // Tek kullanıcı projesi varsa otomatik seç — sürtünmeyi azaltır
  useEffect(() => {
    if (!clusterId || project) return
    const users = projects.filter((p: any) => !p.is_system)
    if (users.length === 1) {
      const name = users[0].name as string
      setProject(name)
      const p = new URLSearchParams(searchParams)
      p.set('project', name)
      setSearchParams(p, { replace: true })
    }
  }, [clusterId, projects, project, searchParams, setSearchParams])

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

  const { data: kubevirtVms } = useQuery({
    queryKey: ['openshift-kubevirt-vms', clusterId],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/kubevirt/vms`)
      if (!r.ok) return { vms: [] }
      return r.json()
    },
    enabled: !!clusterId && section === 'vms',
    refetchInterval: 30_000,
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
          { id: 'genel', label: 'Genel Bakış', icon: LayoutGrid },
          { id: 'projeler', label: 'Projeler', icon: FolderOpen },
          { id: 'topoloji', label: 'Topoloji', icon: Network },
        ],
      },
      {
        group: 'İş Yükleri',
        items: [
          { id: 'deployments', label: 'Deployments', icon: Boxes },
          { id: 'statefulsets', label: 'StatefulSets', icon: Database },
          { id: 'daemonsets', label: 'DaemonSets', icon: Layers },
          { id: 'pods', label: 'Pod & Log', icon: Stethoscope },
        ],
      },
      {
        group: 'Ağ',
        items: [
          { id: 'services', label: 'Services', icon: Share2 },
          { id: 'routes', label: 'Routes', icon: Globe },
        ],
      },
      {
        group: 'Depolama',
        items: [
          { id: 'depolama', label: 'Genel', icon: HardDrive },
          { id: 'pvc', label: 'PVC', icon: Database },
          { id: 'pv', label: 'PersistentVolumes', icon: Server },
        ],
      },
      {
        group: 'Yapılandırma',
        items: [
          { id: 'configmaps', label: 'ConfigMaps', icon: Settings2 },
          { id: 'kaynaklar', label: 'Tüm Kaynaklar', icon: FileCode },
        ],
      },
      {
        group: 'Sanallaştırma',
        items: [
          ...(hasKubevirt ? [{ id: 'vms' as OcpSection, label: 'Sanal Makineler', icon: MonitorPlay }] : []),
          { id: 'tasima' as OcpSection, label: 'Taşıma (MTV)', icon: ArrowRightLeft },
        ],
      },
      {
        group: 'Küme',
        items: [
          { id: 'saglik', label: 'Sağlık', icon: HeartPulse },
          { id: 'riskler', label: 'Riskler', icon: AlertTriangle },
        ],
      },
    ]
    return groups.filter((g) => g.items.length > 0)
  }, [hasKubevirt])

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
              <h1 className="text-base font-bold text-slate-100 leading-tight">OpenShift</h1>
              <p className="text-[11px] text-slate-500">Konteyner platformu ve sanallaştırma</p>
            </div>
          </div>

          {clusters.length > 0 && (
            <>
              <span className="w-px h-8 bg-white/[0.08] hidden sm:block" />
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[11px] text-slate-500">Küme</span>
                <select
                  className="rounded-lg border border-white/[0.08] bg-cyber-deep/80 text-sm text-slate-200 py-1.5 px-2 w-52"
                  value={clusterId ?? ''}
                  onChange={(e) => {
                    setClusterId(Number(e.target.value))
                    setProject('')
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
                <span className="text-[11px] text-slate-500 ml-1">Proje</span>
                <select
                  className="rounded-lg border border-white/[0.08] bg-cyber-deep/80 text-sm text-slate-200 py-1.5 px-2 w-52"
                  value={project}
                  onChange={(e) => {
                    const v = e.target.value
                    setProject(v)
                    const p = new URLSearchParams(searchParams)
                    if (v) p.set('project', v)
                    else p.delete('project')
                    setSearchParams(p, { replace: true })
                  }}
                  title="İş yükü / pod / route bağlamı"
                >
                  <option value="">— proje seçin —</option>
                  <optgroup label="Kullanıcı projeleri">
                    {projects.filter((p: any) => !p.is_system).map((p: any) => (
                      <option key={p.name} value={p.name}>{p.display_name || p.name}</option>
                    ))}
                  </optgroup>
                  <optgroup label="Sistem">
                    {projects.filter((p: any) => p.is_system).map((p: any) => (
                      <option key={p.name} value={p.name}>{p.name}</option>
                    ))}
                  </optgroup>
                </select>
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
                <RefreshCw size={12} className={ovFetching ? 'animate-spin' : ''} /> Yenile
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
            <RefreshCw size={14} className="animate-spin" /> Yükleniyor…
          </div>
        )}

        {!clustersLoading && clusters.length === 0 && (
          <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-10 text-center">
            <Boxes size={36} className="mx-auto mb-3 text-slate-600" />
            <p className="text-sm text-slate-300">Henüz OpenShift kümesi eklenmedi</p>
            <p className="text-xs text-slate-500 mt-2 max-w-md mx-auto">
              Küme bağlantısını Entegrasyonlar üzerinden ekleyin; ardından burada envanter ve iş yükleri görünür.
            </p>
            <Link
              to="/integrations/openshift"
              className="inline-flex mt-4 text-xs px-4 py-2 rounded-lg bg-rose-600/90 text-white hover:bg-rose-500"
            >
              Entegrasyonlar’a git
            </Link>
          </div>
        )}

        {clusterId && overview && (
          <div className="flex gap-4 items-start">
            <nav className="w-48 sm:w-52 flex-shrink-0 sticky top-2 space-y-3 hidden md:block">
              {NAV.map((g, gi) => (
                <div key={gi}>
                  {g.group && (
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
                          className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs transition-colors text-left ${
                            on
                              ? 'bg-rose-500/12 text-rose-300 font-medium'
                              : 'text-slate-400 hover:text-slate-200 hover:bg-white/[0.04]'
                          }`}
                        >
                          <Icon size={14} className="flex-shrink-0" />
                          <span className="truncate">{it.label}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              ))}
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
                  <p className="text-[11px] text-amber-100/80">
                    Proje seçilmedi — üstteki <b>Proje</b> seçicisinden birini seçin ya da{' '}
                    <button type="button" onClick={() => go('projeler')} className="underline mx-0.5">
                      Projeler
                    </button>{' '}
                    listesinden gidin.
                  </p>
                </div>
              )}

              {SECTION_HELP[active] && (
                <div className="flex items-start gap-2 rounded-lg border border-sky-500/20 bg-sky-500/10 px-3 py-2">
                  <Info size={14} className="text-sky-400 mt-px flex-shrink-0" />
                  <p className="text-[11px] text-sky-100/80 leading-relaxed">{SECTION_HELP[active]}</p>
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
                    Sürüm {opHealth.version || '—'}
                    {opHealth.updating ? ` · güncelleniyor: ${opHealth.update_message || ''}` : ''}
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
                  <div className="text-sm text-white font-medium mb-2">Riskli pod’lar</div>
                  {(risksData?.risks || []).length === 0 && (
                    <div className="text-sm text-slate-500 py-6 text-center">Risk kaydı yok</div>
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
                  title="Kaynak gezgini (Deployments)"
                  namespaced
                />
              )}

              {active === 'vms' && (
                <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="text-sm text-white font-medium flex items-center gap-2">
                      <MonitorPlay size={16} className="text-rose-400" /> Sanal Makineler
                    </div>
                  </div>
                  <div className="overflow-x-auto rounded-lg border border-white/[0.06]">
                    <table className="w-full text-xs">
                      <thead className="bg-cyber-deep/80 text-slate-500 text-left">
                        <tr>
                          <th className="px-3 py-2">Ad</th>
                          <th className="px-3 py-2">Namespace</th>
                          <th className="px-3 py-2">Durum</th>
                          <th className="px-3 py-2">IP</th>
                          <th className="px-3 py-2">Node</th>
                          <th className="px-3 py-2 text-right">İşlemler</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(kubevirtVms?.vms || []).map((vm: any) => {
                          const running = (vm.phase || vm.printable_status || '').toLowerCase() === 'running'
                          return (
                            <tr key={`${vm.namespace}/${vm.name}`} className="border-t border-white/[0.04]">
                              <td className="px-3 py-2 text-slate-200 font-medium">{vm.name}</td>
                              <td className="px-3 py-2 text-slate-500">{vm.namespace}</td>
                              <td className="px-3 py-2 text-slate-400">{vm.phase || vm.printable_status || '—'}</td>
                              <td className="px-3 py-2 text-cyan-300/90 font-mono tabular-nums" title={vm.ip_address || ''}>
                                {vm.ip_address || '—'}
                              </td>
                              <td className="px-3 py-2 text-slate-500">{vm.node_name || '—'}</td>
                              <td className="px-3 py-2">
                                <div className="flex items-center justify-end gap-2">
                                  <button
                                    type="button"
                                    disabled={!running}
                                    title={running ? 'Serial console' : 'VM Running olmalı'}
                                    onClick={() => openVmConsole(clusterId, vm.namespace, vm.name)}
                                    className="inline-flex items-center gap-1 text-cyan-300 disabled:opacity-40"
                                  >
                                    <Terminal size={12} /> Console
                                  </button>
                                  <OcpVmAdminActions clusterId={clusterId} vm={vm} />
                                </div>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                    {(kubevirtVms?.vms || []).length === 0 && (
                      <div className="text-sm text-slate-500 py-8 text-center">VM yok</div>
                    )}
                  </div>
                </div>
              )}

              {/* AIOps kısayolları */}
              <div className="flex flex-wrap gap-2 pt-2 text-[11px] text-slate-500">
                <Link to="/openshift/ops" className="inline-flex items-center gap-1 text-rose-300/80 hover:underline">
                  Komuta Merkezi <ChevronRight size={12} />
                </Link>
                <Link to="/openshift/events" className="inline-flex items-center gap-1 text-rose-300/80 hover:underline">
                  Events <ChevronRight size={12} />
                </Link>
                <Link to="/openshift/chat" className="inline-flex items-center gap-1 text-rose-300/80 hover:underline">
                  Asistan <ChevronRight size={12} />
                </Link>
              </div>
            </div>
          </div>
        )}

        {clusterId && !overview && ovFetching && (
          <div className="text-sm text-slate-500 flex items-center gap-2 py-12 justify-center">
            <RefreshCw size={14} className="animate-spin" /> Küme sorgulanıyor…
          </div>
        )}
      </div>
    </div>
  )
}
