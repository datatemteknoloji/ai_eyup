/**
 * Sohbet «Rapor soruları» chip'leri (OpenShift sohbeti + Doğal Dil Asistanı / Yönetici).
 *
 * Her metin backend `chat_quality/report_rules.detect` ile bir hazır rapora eşlenir (LLM'siz, motor özeti).
 * Metinler backend testiyle (`test_report_rules.py` OCP_CHIPS / EXEC_CHIPS) kilitlidir — değiştirirsen ikisini birlikte güncelle.
 * TR/EN farkı yalnız sunumdur; backend her iki dilde de tanır.
 */
export type ChatReportScope = 'openshift' | 'executive'

type Loc = 'tr' | 'en'

const OPENSHIFT: Record<Loc, string[]> = {
  tr: [
    'Executive Summary raporu oluştur',
    'Kapasite raporu göster',
    'Risk dashboard raporu ver',
    'MTV migrasyon raporu göster',
    'MTV migrasyon hazırlık raporu oluştur',
    'Kapasite tahmin raporu üret',
    'Namespace kullanım raporu göster',
    'Depolama (PVC) raporu göster',
    'Workload sağlığı raporu üret',
    'KubeVirt sanal makine raporu göster',
    'Uyum ve güncelleme raporu göster',
    'Operasyon raporu göster',
  ],
  en: [
    'Create executive summary report',
    'Show capacity report',
    'Show risk dashboard report',
    'Show MTV migration report',
    'Create MTV migration readiness report',
    'Show capacity forecast report',
    'Show namespace usage report',
    'Show storage (PVC) report',
    'Show workload health report',
    'Show KubeVirt virtual machine report',
    'Show compliance and update report',
    'Show operations report',
  ],
}

const EXECUTIVE: Record<Loc, string[]> = {
  tr: [
    'Yönetici özeti raporu oluştur',
    'Tüm ortamlar kapasite raporu göster',
    'Tüm ortamlar kapasite tahmin raporu üret',
    'Tüm ortamlar risk raporu ver',
    'En riskli varlıklar raporu göster',
    'SLA ve erişilebilirlik raporu üret',
    'Yama ve uyum raporu göster',
    'Geri kazanım raporu oluştur',
    'İzleme kapsamı raporu göster',
    'Operasyon raporu göster',
    'Migrasyon (MTV) raporu göster',
  ],
  en: [
    'Create executive summary report',
    'Show all environments capacity report',
    'Show all environments capacity forecast report',
    'Show all environments risk report',
    'Show riskiest assets report',
    'Show SLA and availability report',
    'Show patch and compliance report',
    'Show reclaim report',
    'Show monitoring coverage report',
    'Show operations report',
    'Show migration (MTV) report',
  ],
}

export function chatReportQuestions(scope: ChatReportScope, locale: string): string[] {
  const loc: Loc = locale === 'en' ? 'en' : 'tr'
  return (scope === 'openshift' ? OPENSHIFT : EXECUTIVE)[loc]
}
