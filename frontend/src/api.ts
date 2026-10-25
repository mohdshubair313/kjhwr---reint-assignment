import { useEffect, useState } from 'react'
import type { DashboardData, Evaluation, Forecast, Metadata, Query } from './types'

const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

async function get<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${base}${path}`, { signal, headers: { Accept: 'application/json' } })
  if (!response.ok) {
    if (response.status === 503) throw new Error('The wind dataset is temporarily unavailable. Please try again shortly.')
    if (response.status === 422) throw new Error('Choose a January 2026 decision date and a valid London cutoff time.')
    throw new Error(`We couldn’t load the wind data (HTTP ${response.status}). Please try again.`)
  }
  return response.json() as Promise<T>
}

export function useDashboard(query: Query, revision: number) {
  const key = `${query.date}|${query.cutoff}|${revision}`
  const [result, setResult] = useState<{ key: string; data?: DashboardData; error?: string }>()
  useEffect(() => {
    const controller = new AbortController()
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(20000)])
    const params = new URLSearchParams({ decision_date: query.date, cutoff: query.cutoff })
    Promise.all([
      get<Metadata>('/api/metadata', signal),
      get<Forecast>(`/api/forecast?${params}`, signal),
      get<Evaluation>(`/api/evaluation?${new URLSearchParams({ cutoff: query.cutoff })}`, signal),
    ]).then(([metadata, forecast, evaluation]) => {
      if (controller.signal.aborted) return
      if (!Array.isArray(evaluation.rows) || !Array.isArray(evaluation.days) || !evaluation.summary || !Array.isArray(forecast.rows)) {
        throw new Error('The data response was incomplete. Please reload the analysis.')
      }
      if (metadata.snapshot_id !== forecast.snapshot_id || metadata.snapshot_id !== evaluation.snapshot_id) {
        throw new Error('The dataset changed while loading. Reload to view one consistent snapshot.')
      }
      setResult({ key, data: { metadata, forecast, evaluation } })
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return
      const message = error instanceof Error ? error.message : 'An unexpected error occurred.'
      setResult({ key, error: signal.aborted ? 'Loading took too long. Check your connection and try again.' : message })
    })
    return () => controller.abort()
  }, [key, query.date, query.cutoff])
  return result?.key === key ? result : { key }
}
