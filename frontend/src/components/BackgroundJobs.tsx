import React, { useState, useEffect } from 'react'
import { CheckCircle2, XCircle } from 'lucide-react'

interface BackgroundJob {
  id: string
  type: string
  status: 'running' | 'completed' | 'failed'
  message: string
  progress?: number
  started_at: string
}

const BackgroundJobs: React.FC = () => {
  const [jobs, setJobs] = useState<BackgroundJob[]>([])
  const [isExpanded, setIsExpanded] = useState(false)
  const [lastHealthCheck, setLastHealthCheck] = useState<Date | null>(null)

  // Simüle edilmiş job tracker (gerçek backend entegrasyonu için)
  useEffect(() => {
    // Health check timer
    const healthCheckInterval = setInterval(() => {
      setLastHealthCheck(new Date())
    }, 30000) // Her 30 saniye

    return () => clearInterval(healthCheckInterval)
  }, [])

  // Mutation observer - API çağrılarını dinle
  useEffect(() => {
    const originalFetch = window.fetch
    window.fetch = async (...args) => {
      const response = await originalFetch(...args)
      const url = args[0]?.toString() || ''
      
      // Sync işlemlerini yakala
      if (url.includes('/sync-vms') && response.status === 200) {
        const jobId = Date.now().toString()
        const newJob: BackgroundJob = {
          id: jobId,
          type: 'VM Sync',
          status: 'running',
          message: 'VM senkronizasyonu başlatıldı...',
          started_at: new Date().toISOString()
        }
        
        setJobs(prev => [newJob, ...prev])
        
        // 3 saniye sonra tamamlandı olarak işaretle
        setTimeout(() => {
          setJobs(prev => prev.map(j => 
            j.id === jobId ? { ...j, status: 'completed', message: 'VM sync tamamlandı' } : j
          ))
          
          // 5 saniye sonra listeden kaldır
          setTimeout(() => {
            setJobs(prev => prev.filter(j => j.id !== jobId))
          }, 5000)
        }, 3000)
      }
      
      return response
    }
    
    return () => {
      window.fetch = originalFetch
    }
  }, [])

  const runningJobs = jobs.filter(j => j.status === 'running')
  const hasJobs = jobs.length > 0

  if (!hasJobs && !lastHealthCheck) return null

  return (
    <div className="fixed bottom-0 left-0 right-0 z-40">
      {/* Expanded View */}
      {isExpanded && hasJobs && (
        <div className="bg-slate-800 border-t border-slate-700 max-h-64 overflow-y-auto">
          <div className="p-4 space-y-2">
            {jobs.map(job => (
              <div key={job.id} className={`flex items-center justify-between p-3 rounded-lg border ${
                job.status === 'running' ? 'bg-blue-500/10 border-blue-500/30' :
                job.status === 'completed' ? 'bg-green-500/10 border-green-500/30' :
                'bg-red-500/10 border-red-500/30'
              }`}>
                <div className="flex items-center gap-3">
                  {job.status === 'running' && (
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-400"></div>
                  )}
                  {job.status === 'completed' && <CheckCircle2 size={14} strokeWidth={2} className="text-green-400" />}
                  {job.status === 'failed' && <XCircle size={14} strokeWidth={2} className="text-red-400" />}
                  <div>
                    <p className={`text-sm font-medium ${
                      job.status === 'running' ? 'text-blue-400' :
                      job.status === 'completed' ? 'text-green-400' :
                      'text-red-400'
                    }`}>
                      {job.type}
                    </p>
                    <p className="text-xs text-slate-400">{job.message}</p>
                  </div>
                </div>
                <span className="text-xs text-slate-500">
                  {new Date(job.started_at).toLocaleTimeString('tr-TR')}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Status Bar */}
      <div 
        className="bg-slate-900 border-t border-slate-700 px-4 py-2 flex items-center justify-between cursor-pointer hover:bg-slate-800/50 transition-colors"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-4">
          {/* Running Jobs */}
          {runningJobs.length > 0 && (
            <div className="flex items-center gap-2">
              <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-blue-400"></div>
              <span className="text-xs text-blue-400 font-medium">
                {runningJobs.length} işlem çalışıyor
              </span>
            </div>
          )}
          
          {/* Health Check Status */}
          {lastHealthCheck && (
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></span>
              <span className="text-xs text-slate-400">
                Son kontrol: {lastHealthCheck.toLocaleTimeString('tr-TR')}
              </span>
            </div>
          )}

          {!hasJobs && !lastHealthCheck && (
            <span className="text-xs text-slate-500">Sistem aktif</span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {jobs.length > 0 && (
            <span className="text-xs text-slate-500">
              {jobs.length} job
            </span>
          )}
          <span className="text-slate-400 text-xs">
            {isExpanded ? '▼' : '▲'}
          </span>
        </div>
      </div>
    </div>
  )
}

export default BackgroundJobs
