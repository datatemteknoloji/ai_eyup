import React from 'react'
import {
  BarChart3, Zap, Shield, Server, TrendingUp, AlertTriangle,
  Activity, RefreshCw, CheckCircle2, Cpu, Layers, Target, Radar,
} from 'lucide-react'
import type { PlatformKey } from '../config/platformAiops'

export type ReportCatalogItem = {
  type: string
  title: string
  icon: React.ReactNode
  color: string
  desc: string
}

export const PLATFORM_REPORT_LABELS: Record<PlatformKey, string> = {
  linux: 'Linux Altyapı Raporları',
  windows: 'Windows Altyapı Raporları',
  virt: 'Sanallaştırma Altyapı Raporları',
  exadata: 'Exadata Altyapı Raporları',
}

export const PLATFORM_REPORT_SUBTITLES: Record<PlatformKey, string> = {
  linux: 'Linux sunucu envanteri, kapasite, operasyon ve risk raporları',
  windows: 'Windows sunucu olayları, güvenlik ve yama durumu raporları',
  virt: 'Hypervisor, VM kapasitesi, risk ve operasyon raporları',
  exadata: 'Rack, compute node ve cell bazlı Exadata raporları',
}

const VIRT_CATALOG: ReportCatalogItem[] = [
  { type: 'executive_summary', title: 'Executive Summary', icon: <BarChart3 size={18} />, color: 'blue', desc: 'Genel sağlık, kapasite, risk ve SLA durumu tek ekranda' },
  { type: 'capacity', title: 'Kapasite Raporu', icon: <Server size={18} />, color: 'purple', desc: 'CPU, RAM, storage kapasitesi ve doluluk tahmini' },
  { type: 'risk', title: 'Risk Dashboard', icon: <AlertTriangle size={18} />, color: 'red', desc: 'Kritik host, datastore, cluster ve HA/DR riskler' },
  { type: 'vm_health', title: 'VM Sağlık Skoru', icon: <Zap size={18} />, color: 'green', desc: 'Her VM\'in performans, backup ve alarm bazlı sağlık puanı' },
  { type: 'resource_usage', title: 'Kaynak Tahsis Raporu', icon: <Cpu size={18} />, color: 'amber', desc: 'En çok CPU, RAM ve disk tahsis edilen VM\'ler' },
  { type: 'security_compliance', title: 'Güvenlik & Uyumluluk', icon: <Shield size={18} />, color: 'teal', desc: 'VMware Tools, patch, versiyon uyumluluk takibi' },
  { type: 'consolidation', title: 'Konsolidasyon Raporu', icon: <RefreshCw size={18} />, color: 'orange', desc: 'Boşta, kapalı veya gereksiz çalışan VM ve kaynaklar' },
  { type: 'operations', title: 'Operasyon Raporu', icon: <BarChart3 size={18} />, color: 'indigo', desc: 'Olay sayıları, event tipleri, günlük trend' },
  { type: 'forecast', title: 'Kapasite Tahmin', icon: <TrendingUp size={18} />, color: 'cyan', desc: '3, 6 ve 12 aylık büyüme tahmini' },
  { type: 'sla', title: 'Erişilebilirlik Raporu', icon: <CheckCircle2 size={18} />, color: 'green', desc: 'Olay yoğunluğundan tahmini erişilebilirlik' },
  { type: 'riskiest_assets', title: 'En Riskli Varlıklar', icon: <Target size={18} />, color: 'red', desc: 'Kesinti oluşturma ihtimali yüksek host ve VM\'ler' },
]

const LINUX_CATALOG: ReportCatalogItem[] = [
  { type: 'executive_summary', title: 'Executive Summary', icon: <BarChart3 size={18} />, color: 'blue', desc: 'Linux envanter özeti, sağlık skoru ve aktif alarmlar' },
  { type: 'capacity', title: 'Kapasite Raporu', icon: <Server size={18} />, color: 'purple', desc: 'CPU, RAM ve disk kullanımı — yüksek tüketimli sunucular' },
  { type: 'operations', title: 'Operasyon Raporu', icon: <Activity size={18} />, color: 'indigo', desc: '30 günlük log ve olay trendleri' },
  { type: 'risk', title: 'Risk Dashboard', icon: <AlertTriangle size={18} />, color: 'red', desc: 'En çok alarm üreten Linux sunucular' },
  { type: 'performance', title: 'Performans Raporu', icon: <Zap size={18} />, color: 'yellow', desc: 'Metrik anomalileri ve darboğaz adayları' },
  { type: 'patch_status', title: 'Yama Durumu', icon: <RefreshCw size={18} />, color: 'orange', desc: 'OS sürümü, kernel envanteri ve bekleyen paketler' },
  { type: 'security', title: 'Güvenlik Denetimi', icon: <Shield size={18} />, color: 'teal', desc: 'Firewall/SELinux durumu ve başarısız SSH girişleri' },
  { type: 'sla', title: 'Erişilebilirlik (SLA)', icon: <CheckCircle2 size={18} />, color: 'green', desc: 'Olay yoğunluğundan tahmini erişilebilirlik' },
  { type: 'monitoring_coverage', title: 'İzleme Kapsamı', icon: <Radar size={18} />, color: 'cyan', desc: 'AI Ready ve Node Exporter kapsamı — eksik sunucular' },
]

const WINDOWS_CATALOG: ReportCatalogItem[] = [
  { type: 'executive_summary', title: 'Executive Summary', icon: <BarChart3 size={18} />, color: 'blue', desc: 'Windows envanter ve olay özeti' },
  { type: 'operations', title: 'Operasyon Raporu', icon: <Activity size={18} />, color: 'indigo', desc: 'Event Log trendleri ve olay tipleri' },
  { type: 'risk', title: 'Risk Dashboard', icon: <AlertTriangle size={18} />, color: 'red', desc: 'Yüksek olay yoğunluğuna sahip sunucular' },
  { type: 'security', title: 'Güvenlik Özeti', icon: <Shield size={18} />, color: 'teal', desc: 'Kimlik doğrulama olayları ve Windows Defender durumu' },
  { type: 'patch_status', title: 'Yama Durumu', icon: <RefreshCw size={18} />, color: 'orange', desc: 'Bekleyen güncelleme sayısı ve reboot gerekliliği' },
  { type: 'sla', title: 'Erişilebilirlik (SLA)', icon: <CheckCircle2 size={18} />, color: 'green', desc: 'Olay yoğunluğundan tahmini erişilebilirlik' },
  { type: 'monitoring_coverage', title: 'İzleme Kapsamı', icon: <Radar size={18} />, color: 'cyan', desc: 'AI Ready ve Windows Exporter kapsamı — eksik sunucular' },
]

const EXADATA_CATALOG: ReportCatalogItem[] = [
  { type: 'executive_summary', title: 'Executive Summary', icon: <BarChart3 size={18} />, color: 'blue', desc: 'Rack, compute node ve cell envanter özeti' },
  { type: 'capacity', title: 'Kapasite Raporu', icon: <Server size={18} />, color: 'purple', desc: 'Node CPU/RAM kapasitesi' },
  { type: 'operations', title: 'Operasyon Raporu', icon: <Activity size={18} />, color: 'indigo', desc: 'Exadata olay trendleri' },
  { type: 'risk', title: 'Risk Dashboard', icon: <AlertTriangle size={18} />, color: 'red', desc: 'Sağlıksız rack ve aktif alarmlar' },
  { type: 'node_health', title: 'Node Sağlık', icon: <Layers size={18} />, color: 'green', desc: 'Compute node ve cell durumları' },
]

export const PLATFORM_REPORT_CATALOGS: Record<PlatformKey, ReportCatalogItem[]> = {
  linux: LINUX_CATALOG,
  windows: WINDOWS_CATALOG,
  virt: VIRT_CATALOG,
  exadata: EXADATA_CATALOG,
}

export function reportsApiBase(platform: PlatformKey): string {
  return platform === 'virt'
    ? '/hypervisors/reports'
    : `/platform-reports/${platform}`
}
