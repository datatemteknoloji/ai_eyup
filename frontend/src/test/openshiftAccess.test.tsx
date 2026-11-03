import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

let role = 'admin'
vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, v?: any) => (v ? `${k}:${JSON.stringify(v)}` : k),
  useLocale: () => ({ locale: 'tr', setLocale: () => {} }),
}))
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: { role, is_admin: role === 'admin' } }) }))

import OpenShiftAccessPage from '../pages/OpenShiftAccessPage'

const CAPS_ALL = { is_admin: true, can_write: true, reason: '', kinds: {
  RoleBinding: { allowed: true, reason: '' }, ClusterRoleBinding: { allowed: true, reason: '' },
  Role: { allowed: true, reason: '' }, ClusterRole: { allowed: false, reason: 'token yetkisi yok' } } }
const CAPS_NONE = { is_admin: false, can_write: false, reason: 'yalnız admin', kinds: {} }

const crbs = Array.from({ length: 130 }, (_, i) => ({
  kind: 'ClusterRoleBinding', name: `crb-${String(i).padStart(3, '0')}`, namespace: '', uid: `u${i}`, created: '2026-01-01T00:00:00Z',
  labels: i === 0 ? { 'app.kubernetes.io/managed-by': 'ainew' } : {}, annotations: {},
  role_ref: { kind: 'ClusterRole', name: i % 2 ? 'view' : 'cluster-admin' }, subjects: [{ kind: 'User', name: `u${i}`, namespace: '' }], subject_count: 1,
}))

type Call = { url: string; method: string; body?: any }
let calls: Call[] = []
let createResult: any
let previewResult: any

function mockApi() {
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    const method = init?.method || 'GET'
    calls.push({ url: u, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
    const json = (b: unknown, status = 200) => ({ ok: status < 400, status, json: async () => b })
    if (u.endsWith('/openshift/clusters')) return json({ clusters: [{ id: 1, name: 'c1' }] })
    if (u.includes('/openshift/projects')) return json({ projects: [{ name: 'dev' }, { name: 'prod' }] })
    if (u.includes('/access/capabilities')) return json(role === 'admin' ? CAPS_ALL : CAPS_NONE)
    if (u.includes('/access/create/preview')) return json(previewResult)
    if (u.includes('/access/create')) return typeof createResult.status === 'number' ? json({ detail: createResult.detail }, createResult.status) : json(createResult)
    if (u.includes('/access/list')) {
      if (u.includes('kind=clusterrolebindings')) return json({ ok: true, items: crbs, count: crbs.length })
      return json({ ok: true, items: [], count: 0 })
    }
    if (u.includes('/access/get')) return json({ ok: true, item: crbs[0] })
    if (u.includes('/access/yaml')) return json({ ok: true, yaml: 'kind: ClusterRoleBinding\n' })
    if (u.includes('/access/overview')) return json({ ok: true, counts: {}, errors: {}, identity_providers: [{ name: 'htpasswd', type: 'HTPasswd' }], token_can: {} })
    return json({})
  }))
}

const wrap = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <OpenShiftAccessPage />
  </QueryClientProvider>,
)

const PREVIEW_OK = {
  ok: true, dry_run: { ok: true, message: '' }, manifest: { kind: 'RoleBinding', metadata: { name: 'dev-view', namespace: 'dev' } },
  yaml: 'kind: RoleBinding\n', warnings: [], requires_name_confirmation: false, ignored: [],
  equivalent_delete: 'oc delete rolebinding dev-view -n dev',
}

beforeEach(() => {
  vi.unstubAllGlobals(); calls = []; role = 'admin'
  previewResult = PREVIEW_OK
  createResult = { ...PREVIEW_OK, created: true }
  mockApi()
})

async function clickCreate() {
  const btn = await screen.findByTestId('btn-create')
  await waitFor(() => expect(btn).toBeEnabled())
  fireEvent.click(btn)
}

async function openCrbTab() {
  fireEvent.click(await screen.findByTestId('tab-clusterrolebindings'))
  await screen.findByTestId('access-list')
  await waitFor(() => expect(screen.getAllByTestId('access-row').length).toBeGreaterThan(0))
}

describe('OpenShift Access / RBAC', () => {
  it('sekmeler gruplanmış ve yatay', async () => {
    wrap()
    await screen.findByTestId('tab-overview')
    for (const id of ['overview', 'risk', 'users', 'clusterroles', 'rolebindings', 'effective', 'can_i']) {
      expect(screen.getByTestId(`tab-${id}`)).toBeInTheDocument()
    }
  })

  it('liste sıralanabilir ve sayfalanır (130 kayıt → 100 satır, sonraki sayfa)', async () => {
    wrap()
    await openCrbTab()
    expect(screen.getAllByTestId('access-row')).toHaveLength(100)
    fireEvent.click(screen.getByTestId('access-list-next'))
    expect(screen.getAllByTestId('access-row')).toHaveLength(30)
    fireEvent.click(screen.getByTestId('access-list-sort-name'))   // varsayılan artan → azalan
    expect(screen.getAllByTestId('access-row')[0]).toHaveTextContent('crb-129')
  })

  it('Admin: oluştur düğmesi var; token yetkisi olmayan tür seçilemez', async () => {
    wrap()
    await openCrbTab()
    expect(screen.getByTestId('btn-create')).toBeEnabled()
    fireEvent.click(screen.getByTestId('tab-clusterroles'))
    await waitFor(() => expect(screen.getByTestId('btn-create')).toBeDisabled())   // ClusterRole: caps.allowed=false
    expect(screen.getByTestId('btn-create')).toHaveAttribute('title', 'token yetkisi yok')
  })

  it('Admin olmayan: oluştur ve YAML düğmeleri yok; IdP ayrıntısı (mapping) gizli; admin-only endpoint çağrılmaz', async () => {
    role = 'operator'
    wrap()
    await openCrbTab()
    expect(screen.queryByTestId('btn-create')).toBeNull()
    fireEvent.click(screen.getAllByTestId('access-row')[0])
    await screen.findByTestId('detail-pane')
    expect(screen.queryByTestId('btn-yaml')).toBeNull()
    fireEvent.click(screen.getByTestId('tab-idp'))
    expect(await screen.findByTestId('idp-limited')).toBeInTheDocument()
    expect(screen.queryByText('ocp_rb_col_mapping')).toBeNull()
    expect(calls.some(c => c.url.includes('/access/yaml') || c.url.includes('/access/identity-providers') || c.method === 'POST')).toBe(false)
  })

  it('Admin YAML düğmesi ham YAML\'ı getirir', async () => {
    wrap()
    await openCrbTab()
    fireEvent.click(screen.getAllByTestId('access-row')[0])
    fireEvent.click(await screen.findByTestId('btn-yaml'))
    await waitFor(() => expect(screen.getByTestId('yaml-pane')).toHaveTextContent('kind: ClusterRoleBinding'))
  })

  it('ainew etiketli nesne rozetle işaretlenir ve süzülebilir', async () => {
    wrap()
    await openCrbTab()
    fireEvent.click(screen.getByTestId('managed-only'))
    expect(screen.getAllByTestId('access-row')).toHaveLength(1)
    expect(screen.getByTestId('access-row')).toHaveTextContent('ainew')
  })

  it('oluşturma: form → önizleme (dry-run) → oluştur; gövde doğru gider; silme/düzenleme çağrısı yok', async () => {
    wrap()
    fireEvent.click(await screen.findByTestId('tab-rolebindings'))
    await clickCreate()
    const dlg = await screen.findByTestId('create-dialog')
    fireEvent.change(within(dlg).getByTestId('f-name'), { target: { value: 'dev-view' } })
    fireEvent.change(within(dlg).getByTestId('f-ns'), { target: { value: 'dev' } })
    fireEvent.change(within(dlg).getByTestId('f-ref-name'), { target: { value: 'view' } })
    fireEvent.change(within(dlg).getByTestId('subject-name'), { target: { value: 'alice' } })
    fireEvent.click(screen.getByTestId('create-preview'))
    await screen.findByTestId('create-preview-pane')
    const pv = calls.find(c => c.url.includes('/access/create/preview'))!
    expect(pv.method).toBe('POST')
    expect(pv.body.spec).toMatchObject({ name: 'dev-view', namespace: 'dev', role_ref: { kind: 'ClusterRole', name: 'view' } })
    expect(pv.body.spec.subjects[0]).toMatchObject({ kind: 'User', name: 'alice' })
    expect(screen.getByTestId('equivalent-delete')).toHaveTextContent('oc delete rolebinding dev-view -n dev')
    expect(calls.some(c => /\/access\/create$/.test(c.url))).toBe(false)   // henüz oluşturulmadı
    fireEvent.click(screen.getByTestId('create-submit'))
    await screen.findByTestId('create-done')
    expect(calls.filter(c => c.method !== 'GET').every(c => c.method === 'POST')).toBe(true)
    expect(calls.some(c => c.method === 'DELETE' || c.method === 'PUT' || c.method === 'PATCH')).toBe(false)
  })

  it('kritik uyarıda ad yazılıp onay kutusu işaretlenmeden «Oluştur» kapalı', async () => {
    previewResult = { ...PREVIEW_OK, manifest: { kind: 'ClusterRoleBinding', metadata: { name: 'ops-admin' } },
      warnings: [{ level: 'critical', code: 'cluster_admin_global', message: 'cluster-admin tam yetki verir' }],
      requires_name_confirmation: true }
    createResult = { ...previewResult, created: true }
    wrap()
    fireEvent.click(await screen.findByTestId('tab-clusterrolebindings'))
    await clickCreate()
    fireEvent.click(await screen.findByTestId('mode-yaml'))
    fireEvent.click(screen.getByTestId('create-preview'))
    await screen.findByTestId('confirm-box')
    expect(screen.getByTestId('create-warnings')).toHaveTextContent('cluster-admin tam yetki verir')
    const submit = screen.getByTestId('create-submit')
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByTestId('confirm-name'), { target: { value: 'yanlis' } })
    fireEvent.click(screen.getByTestId('confirm-check'))
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByTestId('confirm-name'), { target: { value: 'ops-admin' } })
    expect(submit).not.toBeDisabled()
    fireEvent.click(submit)
    await screen.findByTestId('create-done')
    const real = calls.find(c => /\/access\/create$/.test(c.url))!
    expect(real.body.confirm_name).toBe('ops-admin')
  })

  it('409 «zaten var» mesajı kullanıcıya gösterilir', async () => {
    createResult = { status: 409, detail: 'Aynı isimde RoleBinding zaten var: «dev-view»' }
    wrap()
    fireEvent.click(await screen.findByTestId('tab-rolebindings'))
    await clickCreate()
    fireEvent.click(await screen.findByTestId('mode-yaml'))
    fireEvent.click(screen.getByTestId('create-preview'))
    await screen.findByTestId('create-preview-pane')
    fireEvent.click(screen.getByTestId('create-submit'))
    expect(await screen.findByTestId('create-error')).toHaveTextContent('zaten var')
  })

  it('dry-run reddederse «Oluştur» kapalı', async () => {
    previewResult = { ...PREVIEW_OK, ok: false, dry_run: { ok: false, message: 'Yetki yükseltme engeli' } }
    wrap()
    fireEvent.click(await screen.findByTestId('tab-rolebindings'))
    await clickCreate()
    fireEvent.click(await screen.findByTestId('mode-yaml'))
    fireEvent.click(screen.getByTestId('create-preview'))
    expect(await screen.findByTestId('dry-fail')).toHaveTextContent('Yetki yükseltme engeli')
    expect(screen.getByTestId('create-submit')).toBeDisabled()
  })
})
