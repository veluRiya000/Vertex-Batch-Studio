import { renderHook, waitFor, act, cleanup } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from './api'
import { useCloudConnection } from './cloud-connection'
import type { PublicConfig } from './types'
vi.mock('./api', () => ({ api: vi.fn() }))
afterEach(() => { cleanup(); vi.mocked(api).mockReset() })
const config = { project: 'demo', bucket: 'bucket', credentials_configured: true } as PublicConfig

it('本地服务正常也不把未配置状态显示成云端已连接', () => {
  const { result } = renderHook(() => useCloudConnection({ ...config, credentials_configured: false }, true))
  expect(result.current.state).toBe('unconfigured')
  expect(api).not.toHaveBeenCalled()
})
it('只有云端检查成功才显示绿灯，断开本地服务立即移除绿灯', async () => {
  vi.mocked(api).mockResolvedValue({ ok: true })
  const { result, rerender } = renderHook(({ ready }) => useCloudConnection(config, ready), { initialProps: { ready: true } })
  await waitFor(() => expect(result.current.state).toBe('online'))
  rerender({ ready: false })
  expect(result.current.state).toBe('local-offline')
})
it('云端检查失败显示失败，不能使用本地健康状态代替', async () => {
  vi.mocked(api).mockRejectedValue(new Error('offline'))
  const { result } = renderHook(() => useCloudConnection(config, true))
  await waitFor(() => expect(result.current.state).toBe('failed'))
})
it('换凭证后忽略旧检查的成功响应', async () => {
  let resolve!: (value: unknown) => void
  vi.mocked(api).mockImplementation(() => new Promise(done => { resolve = done }))
  const { result, rerender } = renderHook(({ value }) => useCloudConnection(value, true), { initialProps: { value: config } })
  await waitFor(() => expect(result.current.state).toBe('checking'))
  rerender({ value: { ...config, credentials_configured: false } })
  await act(async () => resolve({ ok: true }))
  expect(result.current.state).toBe('unconfigured')
})
