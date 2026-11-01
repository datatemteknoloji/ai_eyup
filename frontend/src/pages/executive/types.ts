export type Metric = { label: string; value: string }
export type Area = {
  name: string
  status: string
  score: number | null
  reason: string
  metrics: Metric[]
  series: Array<{ day: string; area: string; severity: string; count: number }>
  formula: string
  change: string
  assets?: Array<{ name: string; status: string; critical: string; warning: string; usage: string }>
  events?: string[]
  issues?: Array<{ problem: string; action: string }>
}
export type TreeHost = { name: string; cpu: number | null; memory: number | null; problem: boolean }
export type TreeCluster = {
  name: string
  environment: string
  kind: string
  hosts: number
  vms: number
  cpu: number
  memory: number
  host_list?: TreeHost[]
}
export type EnvCard = {
  name: string
  kind: string
  clusters: number
  hosts: number
  vms: number
  cpu: number | null
  memory: number | null
  storage?: number | null
  storage_name?: string | null
  problem: string
  action: string
  status: string
  tree?: TreeCluster[]
}
export type Landscape = {
  physical: string
  virtual: string
  platforms: Array<{ name: string; environments: number; clusters: number; hosts: number; vms: number }>
  environments: EnvCard[]
  clusters: TreeCluster[]
  datastores: Array<{ name: string; environment: string; usage: number; usageLabel: string; free: string }>
  hosts: Array<{ host: string; problem: string; action: string; cluster: string; environment: string; kind: string; hardware: boolean }>
  reclaim: Array<{ environment: string; cluster: string; count: string; vcpu: number; ram: string; disk: string }>
}
export type Capacity = {
  name: string
  resource: string
  now: string
  cpu: string
  early: string | null
  typical: string | null
  late: string | null
  low: boolean
}
export type Risk = { area: string; sentence: string; age: string; age_days: number; action: string; entity?: string | null }
export type AttentionItem = {
  title: string
  problem: string
  action: string
  environment: string
  kind: string
  cluster: string
  hardware: boolean
  extra: number
  age_days: number
  area: string
}
export type Idle = {
  categories: Array<{ name: string; count: string; vcpu: string; ram: string; disk: string }>
  top: Array<{ name: string; cluster: string; category: string; amount: string; age: string }>
  note: string
}
export type Calendar = {
  bands: Array<{ label: string; early?: number; late?: number; missing?: boolean }>
  items: Array<{ when: string; area: string; event: string; impact: string }>
}
export type DemoCard = { title: string; demo: boolean; status?: string; lines: Array<{ label: string; value: string }> }
export type View = {
  summary?: { text: string; source: string }
  kpis: Array<{ label: string; value: string; hint: string }>
  areas: Area[]
  capacity: Capacity[]
  failover?: string
  investment: { value: string; sentence: string }
  calendar?: Calendar
  idle?: Idle
  operations?: string
  sources?: Array<{ label: string; count: string; trend: string }>
  risks: Risk[]
  risk_rule: string
  events: Array<{ day: string; area: string; severity: string; count: number }>
  coverage: { measured: number; total: number; rows: Array<{ section: string; status: string; missing: string; how: string }> }
  openshift_note: string
  formula: string
  landscape?: Landscape
  attention?: AttentionItem[]
}
export type Bundle = {
  status: 'empty' | 'ready'
  generated_at: string | null
  refreshing: boolean
  period: { start: string; end: string } | null
  months?: string[]
  summary?: string | null
  summary_source?: string | null
  view?: View | null
  demo_cards?: DemoCard[]
}
