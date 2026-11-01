import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../i18n/LocaleProvider', () => ({ useT: () => (k: string) => k }))

import GenericReportView, { isGenericReport, type GenericReport } from '../components/reports/GenericReportView'
import {
  PLATFORM_REPORT_CATALOGS, PLATFORM_REPORT_SUBTITLE_KEYS, PLATFORM_REPORT_TITLE_KEYS,
  reportMethodologyKey, reportsApiBase,
} from '../config/infraReportCatalog'
import { dictionaries } from '../i18n/messages'
import { ROUTE_ACCESS } from '../config/routeAccess'

const report: GenericReport = {
  view: 'generic',
  title: 'Tüm Ortamlar — Kapasite Tahmin',
  kpis: [{ label: '12 ay içinde eşiğe varan', value: 1, tone: 'warn' }],
  applicability: {
    virt: { included: true }, openshift: { included: true }, linux: { included: true },
    windows: { included: false, reason: 'Seri yok' }, exadata: { included: false, reason: 'Kullanım serisi yok' },
  },
  sections: [
    {
      title: 'Eşiğe kalan süre', module: 'OpenShift', status: 'ok',
      columns: ['Cluster', 'Kaynak', 'Durum', 'Kayıtlı'],
      rows: [['oVirt', 'CPU', 'Kritik', true], ['oVirt', 'Memory', null, false]],
      note: 'Aralık hızlı–yavaş senaryodur.',
    },
    { title: 'Süre', module: 'Linux', status: 'unmeasured', note: 'En az 14 günlük seri gerekir; en uzun seri 3 gün.' },
  ],
  excluded: [{ module: 'Windows', reason: 'Windows için günlük kullanım serisi toplanmıyor.' }],
  recommendations: ['Memory request yüksek.'],
  notes: ['Sentetik kaynaklar dahil edilmez.'],
}

describe('GenericReportView', () => {
  it('detects the generic schema', () => {
    expect(isGenericReport(report)).toBe(true)
    expect(isGenericReport({ view: 'other' })).toBe(false)
    expect(isGenericReport(null)).toBe(false)
  })

  it('renders measured table, unmeasured note (no invented numbers) and excluded reason', () => {
    render(<GenericReportView d={report} />)
    const secs = screen.getAllByTestId('generic-section')
    expect(secs).toHaveLength(2)
    // ölçülen bölüm: tablo + boş hücre «—»
    expect(within(secs[0]).getByText('Kritik')).toBeTruthy()
    expect(within(secs[0]).getAllByText('—').length).toBeGreaterThan(0)
    // ölçülemeyen bölüm: tablo yok, neden yazılı, rozet var
    expect(within(secs[1]).queryByRole('table')).toBeNull()
    expect(within(secs[1]).getByText(/en uzun seri 3 gün/)).toBeTruthy()
    expect(within(secs[1]).getByText('rpt_gen_unmeasured')).toBeTruthy()
    // kapsam dışı + neden
    const ex = screen.getByTestId('generic-excluded')
    expect(within(ex).getByText(/günlük kullanım serisi toplanmıyor/)).toBeTruthy()
    expect(screen.getByText('Memory request yüksek.')).toBeTruthy()
  })

  it('shows module coverage chips with the reason as tooltip', () => {
    render(<GenericReportView d={report} />)
    const cov = screen.getByTestId('generic-coverage')
    expect(within(cov).getByText('rpt_gen_mod_windows').getAttribute('title')).toBe('Seri yok')
    expect(within(cov).getByText('rpt_gen_mod_virt').getAttribute('title')).toBeNull()
  })

  it('colours English status words like the Turkish ones (report language follows the UI language)', () => {
    const d: GenericReport = {
      view: 'generic', title: 'x',
      sections: [{ title: 'T', status: 'ok', columns: ['s'], rows: [['Critical'], ['Attention'], ['Normal'], ['Not measured'], ['Kritik'], ['Dikkat']] }],
    }
    render(<GenericReportView d={d} />)
    expect(screen.getByText('Critical').className).toContain('text-red-400')
    expect(screen.getByText('Attention').className).toContain('text-amber-400')
    expect(screen.getByText('Normal').className).toContain('text-green-400')
    expect(screen.getByText('Not measured').className).toContain('text-slate-500')
    expect(screen.getByText('Kritik').className).toContain('text-red-400')
    expect(screen.getByText('Dikkat').className).toContain('text-amber-400')
  })

  it('renders empty rows message instead of an empty table', () => {
    render(<GenericReportView d={{ view: 'generic', title: 'x', sections: [{ title: 'T', status: 'ok', columns: ['a'], rows: [] }] }} />)
    expect(screen.getByText('rpt_gen_no_rows')).toBeTruthy()
  })
})

describe('report catalogs', () => {
  const ocpTypes = ['executive_summary', 'capacity', 'forecast', 'capacity_plan', 'risk', 'riskiest_assets', 'namespace_usage',
    'storage', 'workload_health', 'vm_health', 'compliance_update', 'operations', 'mtv_migration', 'mtv_readiness']
  const execTypes = ['executive_summary', 'capacity', 'forecast', 'risk', 'riskiest_assets', 'operations', 'sla',
    'patch_compliance', 'reclaim', 'monitoring_coverage', 'migration']

  it('OpenShift catalog matches the backend (14 reports incl. MTV)', () => {
    expect(PLATFORM_REPORT_CATALOGS.openshift.map((c) => c.type)).toEqual(ocpTypes)
  })

  it('Executive catalog matches the backend; no backup/Veeam report', () => {
    expect(PLATFORM_REPORT_CATALOGS.executive.map((c) => c.type)).toEqual(execTypes)
  })

  it('every title/desc key exists in both languages', () => {
    for (const p of ['openshift', 'executive'] as const) {
      for (const c of PLATFORM_REPORT_CATALOGS[p]) {
        for (const k of [c.titleKey, c.descKey]) {
          expect(dictionaries.tr[k], `${p}:${c.type}:${k} tr`).toBeTruthy()
          expect(dictionaries.en[k], `${p}:${c.type}:${k} en`).toBeTruthy()
        }
      }
      expect(dictionaries.en[PLATFORM_REPORT_TITLE_KEYS[p]]).toBeTruthy()
      expect(dictionaries.en[PLATFORM_REPORT_SUBTITLE_KEYS[p]]).toBeTruthy()
    }
  })

  it('uses dedicated API bases and no virt/linux methodology fallbacks', () => {
    expect(reportsApiBase('executive')).toBe('/executive-reports')
    expect(reportsApiBase('openshift')).toBe('/platform-reports/openshift')
    expect(reportMethodologyKey('openshift', 'forecast')).toBeUndefined()
    expect(reportMethodologyKey('executive', 'executive_summary')).toBeUndefined()
    expect(reportMethodologyKey('virt', 'forecast')).toBeDefined()
  })

  it('new routes are module-protected', () => {
    const map = new Map(ROUTE_ACCESS)
    expect(map.get('/openshift/reports')).toEqual({ modules: ['openshift'] })
    expect(map.get('/executive/infra-reports')).toEqual({ modules: ['executive'] })
  })
})
