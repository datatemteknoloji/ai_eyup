/**
 * Exadata Altyapı Analizi — Exadata compute/cell sunucularına bağlı Linux hostlar üzerinden AI analiz.
 */
import Chat from './Chat'

export default function ExadataChat() {
  return (
    <div className="space-y-2">
      <div className="mx-4 px-4 py-2 rounded-xl bg-orange-500/10 border border-orange-500/25 text-sm text-orange-200">
        <span className="font-semibold">Exadata Altyapı Analizi</span>
        <span className="text-orange-200/70 ml-2">— compute node ve cell&apos;e bağlı Linux sunucular üzerinden sorgulama</span>
      </div>
      <Chat />
    </div>
  )
}
