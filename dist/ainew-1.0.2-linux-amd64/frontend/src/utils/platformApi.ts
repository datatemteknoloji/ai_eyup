import type { PlatformKey } from '../config/platformAiops'

export function appendPlatform(params: URLSearchParams, platform?: PlatformKey) {
  if (platform) params.set('platform', platform)
  return params
}

export function platformQuery(platform?: PlatformKey) {
  return platform ? `platform=${platform}` : ''
}

export type PlatformAiopsProps = {
  platform?: PlatformKey
}
