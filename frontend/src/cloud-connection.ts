import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { PublicConfig } from './types'

export function useCloudConnection(config: PublicConfig | undefined, localReady: boolean) {
  const [result, setResult] = useState<{ config?: PublicConfig; state: string }>({ state: 'unchecked' })
  const revision = useRef(0)
  const inFlight = useRef<{ config?: PublicConfig; revision: number; promise: Promise<void> } | null>(null)
  const configured = !!config?.project && !!config.bucket &&
    (config.credentials_configured || config.authentication_mode === 'adc')
  const check = useCallback(async () => {
    const active = inFlight.current
    if (active && active.config === config && active.revision === revision.current) {
      return active.promise
    }
    const current = ++revision.current
    if (!localReady || !configured) {
      setResult({ config, state: localReady ? 'unconfigured' : 'local-offline' })
      throw new Error('请先在设置中配置 Google Cloud 连接')
    }
    setResult({ config, state: 'checking' })
    const promise = (async () => { try {
      const response = await api<{ ok: boolean }>('/cloud/check', 'POST')
      if (!response.ok) throw new Error('Google Cloud 连接检查失败')
      if (revision.current === current) setResult({ config, state: 'online' })
    } catch (error) {
      if (revision.current === current) setResult({ config, state: config?.credentials_configured ? 'failed' : 'unconfigured' })
      throw error
    } })()
    inFlight.current = { config, revision: current, promise }
    try { await promise } finally { if (inFlight.current?.promise === promise) inFlight.current = null }
  }, [config, localReady, configured])
  useEffect(() => {
    if (!localReady || !configured) return
    void check().catch(() => {})
    const timer = setInterval(() => { void check().catch(() => {}) }, 30000)
    return () => { revision.current++; clearInterval(timer) }
  }, [check, localReady, configured])
  const state = !localReady ? 'local-offline' : !config ? 'unchecked' : !configured ? 'unconfigured'
    : result.config !== config ? 'unchecked' : result.state
  const label = ({ online: '已连接', checking: '检查中', failed: '连接失败', unconfigured: '未配置',
    'local-offline': '本地服务离线', unchecked: '待检查' } as Record<string, string>)[state]
  return { state, label, check }
}
