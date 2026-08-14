/** OpenShift Explorer — ortak tipler (Atlas IA, ainew API). */

export type OcpSection =
  | 'genel'
  | 'projeler'
  | 'topoloji'
  | 'deployments'
  | 'statefulsets'
  | 'daemonsets'
  | 'pods'
  | 'services'
  | 'routes'
  | 'depolama'
  | 'pvc'
  | 'pv'
  | 'configmaps'
  | 'kaynaklar'
  | 'vms'
  | 'tasima'
  | 'saglik'
  | 'riskler'

export const SECTION_HELP: Partial<Record<OcpSection, string>> = {
  genel:
    'Cluster genel durumu: kapasite, node’lar, StorageClass ve Multus ağ tanımları. Buradan başlayın.',
  saglik:
    'ClusterOperator sağlığı ve güncelleme durumu. Bir şey bozulduğunda ilk bakılacak yer.',
  topoloji:
    'Seçili projedeki uygulamaların görsel haritası. Node’a tıklayınca ilişkiler sağda açılır.',
  depolama: 'StorageClass, PVC, PV ve Multus ağ tanımları.',
  vms: 'OpenShift Virtualization (KubeVirt) — VNC konsol, güç, snapshot/klon (admin) ve canlı CPU/bellek.',
  tasima: 'VMware → OpenShift taşıma (MTV) hazırlığı ve operatör durumu.',
  kaynaklar: 'Kubernetes nesnelerini listeleyip YAML görüntüleyin; Deployment’larda ölçek ±.',
  projeler: 'Proje seçin; Workload / Pod / Route listeleri bu bağlamda çalışır.',
  riskler: 'CrashLoop / ImagePull / yüksek restart riskli Pod’lar.',
  pods: 'Pod durumu, container’lar, events ve log — satırı genişletin.',
}

export const NEEDS_PROJECT: OcpSection[] = [
  'deployments',
  'statefulsets',
  'daemonsets',
  'pods',
  'services',
  'routes',
  'pvc',
  'configmaps',
  'topoloji',
]

export const SECTION_KIND: Partial<Record<OcpSection, string>> = {
  deployments: 'deployments',
  statefulsets: 'statefulsets',
  daemonsets: 'daemonsets',
  pods: 'pods',
  services: 'services',
  routes: 'routes',
  pvc: 'persistentvolumeclaims',
  pv: 'persistentvolumes',
  configmaps: 'configmaps',
}

export interface OcpCluster {
  id: number
  name: string
  api_url: string
  status: string | null
  version: string | null
  last_sync: string | null
  auth_method?: string
  verify_ssl?: boolean
  has_token?: boolean
}

export interface OcpProject {
  id: number
  cluster_id: number
  name: string
  status: string | null
  display_name: string | null
  requester: string | null
  pod_count?: number
  deployment_count?: number
  route_count?: number
  is_system: boolean
  updated_at?: string | null
}
