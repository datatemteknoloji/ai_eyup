import { RESOURCE_ACCENT, ResourceBarsChart } from '../../components/dashboard/ResourceCharts'
import type { Landscape } from './types'

/** Küme kaynakları ve depolama doluluğu. Sanallaştırma/OpenShift sayfalarındaki host grafiğiyle aynı bileşen. */
export function ResourceCharts({ land }: { land: Landscape }) {
  const clusterRows = land.clusters.map((row) => ({
    name: row.name === row.environment ? `${row.kind} · ${row.name}` : `${row.kind} · ${row.environment} · ${row.name}`,
    cpu: row.cpu,
    memory: row.memory,
  }))
  const storeRows = land.datastores.map((row) => ({ name: `${row.environment} · ${row.name}`, usage: row.usage }))
  if (!clusterRows.length && !storeRows.length) return null
  return (
    <section id="kaynaklar" className="grid grid-cols-1 xl:grid-cols-2 gap-3">
      {clusterRows.length > 0 && (
        <ResourceBarsChart
          title="Küme kaynakları"
          note="Doluluk ortam ve küme bazındadır. İlk 10 küme."
          rows={clusterRows}
          labelWidth={150}
          maxLabel={26}
          height={Math.max(200, clusterRows.length * 56)}
          series={[
            { key: 'cpu', label: 'İşlemci', color: RESOURCE_ACCENT.cpu },
            { key: 'memory', label: 'Bellek', color: RESOURCE_ACCENT.memory },
          ]}
        />
      )}
      {storeRows.length > 0 && (
        <div>
          <ResourceBarsChart
            title="Depolama doluluğu"
            note="İlk 10 depolama alanı. Host toplamları birbirine eklenmez."
            rows={storeRows}
            labelWidth={150}
            maxLabel={26}
            threshold={85}
            height={Math.max(200, storeRows.length * 36)}
            series={[{ key: 'usage', label: 'Doluluk', color: RESOURCE_ACCENT.disk }]}
          />
          <ul className="text-sm mt-2 px-1 space-y-1">
            {land.datastores.slice(0, 5).map((row) => (
              <li key={`${row.environment}-${row.name}`} className="flex justify-between gap-2">
                <span>{row.environment} · {row.name}</span>
                <span>{row.usageLabel} · boş {row.free}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
