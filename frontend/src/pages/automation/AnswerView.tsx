import { memo, useState } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ChevronDown } from 'lucide-react'
import { chatMarkdownComponents } from '../../components/chatMarkdown'
import { fmtDateTime } from './ui'

/**
 * Automic asistan yanıtının sunumu: model içeriği Markdown olarak üretir, görünümü bu dosya (ve
 * `.automic-md` CSS'i) belirler. Başlıklar sade etiket, ilk paragraf giriş cümlesi, maddeler aralıklı
 * bloklar; zaman/sistem/kaynak gibi teknik ayrıntılar `AnswerFooter` içinde ikincil bilgi olarak durur.
 */

export type AnswerScope = {
  system?: string | null
  clients?: number[]
  time_from?: string | null
  time_to?: string | null
  data_source?: 'db' | 'source' | 'mixed' | string
  record_count?: number | null
  source_lag_sec?: number | null
  last_collection_at?: string | null
  partial?: boolean
  retention_limited?: boolean
  fallback_tools?: boolean
  tools?: string[]
}

export type Severity = 'ok' | 'info' | 'warning' | 'critical'
export type Confidence = 'high' | 'medium' | 'low' | null | undefined

const META_FENCE = /```ainew-meta[\s\S]*?(```|$)/g
const LEAD_FENCE = /^\s*```(?:markdown|md)[ \t]*\r?\n/i

/**
 * Ham modelden gelen metni gösterime hazırlar:
 *  - ainew-meta bloğunu çıkarır,
 *  - tüm yanıtı saran ```markdown çitini kaldırır (aksi halde mesajın tamamı tek gri kod alanı görünür),
 *  - akış sırasında yarım kalmış çit/meta başlangıcını gizler.
 */
export function normalizeAnswer(text: string, streaming = false): string {
  let t = (text || '').replace(META_FENCE, '').trimEnd()
  const wrapped = LEAD_FENCE.test(t)
  if (wrapped) {
    t = t.replace(LEAD_FENCE, '')
    t = t.replace(/\r?\n```[ \t]*$/, '')
  }
  if (streaming) {
    // yarım kalmış kapanış/meta çiti (`, ``, ```, ```ain…) akışta bir an görünmesin
    t = t.replace(/\r?\n?`{1,3}[a-z-]{0,12}$/i, '')
  }
  return t.trimEnd()
}

const Label = ({ children }: { children?: React.ReactNode }) => <h4 className="am-h">{children}</h4>

const components: Components = {
  ...chatMarkdownComponents,
  h1: Label, h2: Label, h3: Label, h4: Label, h5: Label, h6: Label,
  p: ({ children }) => <p className="am-p">{children}</p>,
  ul: ({ children }) => <ul className="am-ul">{children}</ul>,
  ol: ({ children }) => <ol className="am-ol">{children}</ol>,
  li: ({ children }) => <li className="am-li">{children}</li>,
  blockquote: ({ children }) => <blockquote className="am-quote">{children}</blockquote>,
  hr: () => <hr className="am-hr" />,
  strong: ({ children }) => <strong className="am-strong">{children}</strong>,
  a: ({ children, href }) => <a className="am-a" href={href} target="_blank" rel="noreferrer">{children}</a>,
  code: ({ className, children }) =>
    className ? <code className={className}>{children}</code> : <code className="am-code">{children}</code>,
}

export const AutomicMarkdown = memo(function AutomicMarkdown({ text, severity = 'info', streaming = false }: {
  text: string
  severity?: Severity
  streaming?: boolean
}) {
  return (
    <div className="automic-md" data-severity={severity}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {normalizeAnswer(text, streaming)}
      </ReactMarkdown>
    </div>
  )
})

const CONFIDENCE: Record<string, { label: string; cls: string }> = {
  high: { label: 'Yüksek', cls: 'am-conf-high' },
  medium: { label: 'Orta', cls: 'am-conf-medium' },
  low: { label: 'Düşük', cls: 'am-conf-low' },
}

export function ConfidenceBadge({ value }: { value: Confidence }) {
  const c = value ? CONFIDENCE[value] : null
  if (!c) return null
  return (
    <span className={`am-conf ${c.cls}`} title="Yanıtın araç verisine dayanma düzeyi">
      <i aria-hidden />Güven: {c.label}
    </span>
  )
}

const SOURCE_LABEL: Record<string, string> = { db: 'Modül DB', source: 'Kaynak (canlı)', mixed: 'Modül DB + kaynak' }

const TOOL_LABELS: Record<string, string> = {
  automic_search_executions: 'Çalışma arama',
  automic_execution: 'Çalışma detayı',
  automic_active: 'Aktif işler',
  automic_object: 'Nesne özeti',
  automic_agent: 'Agent',
  automic_history: 'Analiz',
  automic_status: 'Entegrasyon durumu',
}

function fmtLag(sec?: number | null): string | null {
  if (sec == null) return null
  const s = Math.round(sec)
  if (s < 60) return `${s} sn`
  if (s < 3600) return `${Math.round(s / 60)} dk`
  return `${Math.floor(s / 3600)} sa ${Math.round((s % 3600) / 60)} dk`
}

function fmtRange(from?: string | null, to?: string | null): string | null {
  if (!from && !to) return null
  const f = from ? fmtDateTime(from) : '…'
  const t = to ? fmtDateTime(to) : '…'
  return `${f} – ${t}`
}

/** Tek satır özet (sistem · zaman aralığı · kayıt · kaynak) + tıklayınca ayrıntı. */
export function AnswerFooter({ scope, confidence, tools }: {
  scope?: AnswerScope | null
  confidence?: Confidence
  tools?: string[]
}) {
  const [open, setOpen] = useState(false)
  const s = scope || {}
  const toolList = Array.from(new Set([...(tools ?? []), ...(s.tools ?? [])]))
  const range = fmtRange(s.time_from, s.time_to)
  const lag = fmtLag(s.source_lag_sec)
  const summary = [
    s.system,
    range,
    s.record_count != null ? `${s.record_count.toLocaleString('tr-TR')} kayıt` : null,
    s.data_source ? SOURCE_LABEL[s.data_source] ?? s.data_source : null,
  ].filter(Boolean) as string[]
  const notes = [
    s.partial ? 'Sonuç kısmi (sınır aşıldı veya kaynak tam yanıt vermedi).' : null,
    s.retention_limited ? 'Saklama süresi dışındaki dönem günlük özetlerden okundu; tekil çalışma içermez.' : null,
    s.fallback_tools ? 'Araçlar model yerine doğrudan çalıştırıldı.' : null,
  ].filter(Boolean) as string[]
  if (summary.length === 0 && !confidence && toolList.length === 0) return null
  return (
    <div className="am-footer">
      <div className="am-footer-row">
        <button type="button" className="am-footer-toggle" aria-expanded={open} onClick={() => setOpen(o => !o)}>
          <span className="am-footer-summary">{summary.join(' · ') || 'Sorgu detayı'}</span>
          <ChevronDown size={12} className={`am-chevron ${open ? 'am-chevron-open' : ''}`} />
        </button>
        <ConfidenceBadge value={confidence} />
      </div>
      {open && (
        <dl className="am-footer-detail">
          {s.system && <><dt>Sistem</dt><dd>{s.system}</dd></>}
          {s.clients && s.clients.length > 0 && <><dt>Client</dt><dd>{s.clients.join(', ')}</dd></>}
          {range && <><dt>Zaman aralığı</dt><dd>{range}</dd></>}
          {s.record_count != null && <><dt>Kayıt sayısı</dt><dd>{s.record_count.toLocaleString('tr-TR')}</dd></>}
          {s.data_source && <><dt>Veri kaynağı</dt><dd>{SOURCE_LABEL[s.data_source] ?? s.data_source}</dd></>}
          {lag && <><dt>Kaynak gecikmesi</dt><dd>{lag}</dd></>}
          {s.last_collection_at && <><dt>Son toplama</dt><dd>{fmtDateTime(s.last_collection_at)}</dd></>}
          {toolList.length > 0 && (
            <><dt>Araçlar</dt><dd>{toolList.map(t => TOOL_LABELS[t] ?? t).join(', ')}</dd></>
          )}
          {notes.length > 0 && <><dt>Notlar</dt><dd>{notes.join(' ')}</dd></>}
        </dl>
      )}
    </div>
  )
}
