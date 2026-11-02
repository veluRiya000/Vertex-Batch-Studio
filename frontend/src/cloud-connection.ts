import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { PublicConfig } from './types'

export function useCloudConnection(config: PublicConfig | undefined, localReady: boolean) {
  // Polling /config creates new objects: only connection fields invalidate a check.
  const key = JSON.stringify([config?.project, config?.bucket, config?.location,
    config?.credentials_configured, config?.credential_name, config?.authentication_mode, localReady])
  const [result, setResult] = useState<{ key?: string; state: string }>({ state: 'unchecked' })
  const revision = useRef(0)
  const inFlight = useRef<{ key: string; revision: number; promise: Promise<void> } | null>(null)
  const configured = !!config?.project && !!config.bucket &&
    (config.credentials_configured || config.authentication_mode === 'adc')
  const check = useCallback(async () => {
    const active = inFlight.current
    if (active && active.key === key && active.revision === revision.current) {
      return active.promise
    }
    const current = ++revision.current
    if (!localReady || !configured) {
      setResult({ key, state: localReady ? 'unconfigured' : 'local-offline' })
      throw new Error('请先在设置中配置 Google Cloud 连接')
    }
    setResult({ key, state: 'checking' })
    const promise = (async () => { try {
      const response = await api<{ ok: boolean }>('/cloud/check', 'POST', undefined, 35000)
      if (!response.ok) throw new Error('Google Cloud 连接检查失败')
      if (revision.current === current) setResult({ key, state: 'online' })
    } catch (error) {
      if (revision.current === current) setResult({ key, state: 'failed' })
      throw error
    } })()
    inFlight.current = { key, revision: current, promise }
    try { await promise } finally { if (inFlight.current?.promise === promise) inFlight.current = null }
  }, [key, localReady, configured])
  useEffect(() => {
    if (!localReady || !configured) return
    void check().catch(() => {})
    const timer = setInterval(() => { void check().catch(() => {}) }, 30000)
    return () => { revision.current++; clearInterval(timer) }
  }, [check, localReady, configured])
  const state = !localReady ? 'local-offline' : !config ? 'unchecked' : !configured ? 'unconfigured'
    : result.key !== key ? 'unchecked' : result.state
  const label = ({ online: '已连接', checking: '检查中', failed: '连接失败', unconfigured: '未配置',
    'local-offline': '本地服务离线', unchecked: '待检查' } as Record<string, string>)[state]
  return { state, label, check }
}
