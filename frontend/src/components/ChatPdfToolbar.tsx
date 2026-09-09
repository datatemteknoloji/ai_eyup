import type { ReactNode } from 'react'
import { CheckSquare, FileDown, X } from 'lucide-react'
import { useT } from '../i18n/LocaleProvider'
import type { ChatPdfPair } from '../lib/chatPdfSelect'
import { exportChatMessagesToPrintWindow, type PdfExportOptions } from '../utils/pdfExport'

type SelectApi = {
  selectMode: boolean
  selectedCount: number
  enter: () => void
  exit: () => void
  selectAll: (ids: string[]) => void
  exportSelected: (pairs: ChatPdfPair[], options: PdfExportOptions) => void
}

export function ChatPdfToolbar({
  pairs,
  select,
  fullExport,
}: {
  pairs: ChatPdfPair[]
  select: SelectApi
  fullExport: PdfExportOptions
}) {
  const t = useT()
  if (pairs.length === 0) return null

  if (!select.selectMode) {
    return (
      <>
        <button
          type="button"
          onClick={() => exportChatMessagesToPrintWindow(
            pairs.flatMap(p => p.messages),
            fullExport,
          )}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-red-500/15 text-red-300 border border-red-500/30 hover:bg-red-500/25"
          title={t('chat_pdf_title')}
        >
          <FileDown size={13} /> {t('chat_pdf_chat')}
        </button>
        <button
          type="button"
          onClick={select.enter}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-white/[0.06] text-slate-300 border border-white/[0.1] hover:bg-white/[0.1]"
          title={t('chat_pdf_select_title')}
        >
          <CheckSquare size={13} /> {t('chat_pdf_select')}
        </button>
      </>
    )
  }

  return (
    <>
      <button
        type="button"
        onClick={() => select.selectAll(pairs.map(p => p.id))}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-white/[0.06] text-slate-300 border border-white/[0.1] hover:bg-white/[0.1]"
      >
        {t('chat_select_all')}
      </button>
      <button
        type="button"
        disabled={select.selectedCount === 0}
        onClick={() => select.exportSelected(pairs, {
          ...fullExport,
          title: `${fullExport.title || t('chat_pdf_chat')} — ${t('chat_pdf_selected_n', { n: select.selectedCount })}`,
          filename: `${fullExport.filename || 'sohbet'}_secili`,
        })}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-red-500/15 text-red-300 border border-red-500/30 hover:bg-red-500/25 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        <FileDown size={13} /> {t('chat_pdf_selected_n', { n: select.selectedCount })}
      </button>
      <button
        type="button"
        onClick={select.exit}
        className="inline-flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs text-slate-400 hover:text-slate-200"
        title={t('chat_clear')}
      >
        <X size={13} />
      </button>
    </>
  )
}

export function ChatPdfPairWrap({
  selectMode,
  checked,
  onToggle,
  children,
}: {
  selectMode: boolean
  checked: boolean
  onToggle: () => void
  children: ReactNode
}) {
  return (
    <div className={`relative ${selectMode ? 'pl-7' : ''}`}>
      {selectMode && (
        <label className="absolute left-0 top-3 z-10 flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={checked}
            onChange={onToggle}
            className="w-3.5 h-3.5 rounded border-white/30 bg-cyber-card text-blue-500 focus:ring-blue-500"
          />
        </label>
      )}
      {children}
    </div>
  )
}
