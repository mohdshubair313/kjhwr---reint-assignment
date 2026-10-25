import type { EvaluationPoint } from './types'

const number = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 1 })
export const fmt = (value: number | null | undefined) => value == null ? '—' : number.format(value)
export const signed = (value: number | null | undefined) => value == null ? '—' : `${value > 0 ? '+' : ''}${fmt(value)}`
export const percent = (value: number) => `${new Intl.NumberFormat('en-GB', { maximumFractionDigits: 1 }).format(value * 100)}%`
export const hour = (value: string) => new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/London', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value))
export const dateLabel = (value: string, year = false) => new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/London', day: 'numeric', month: 'short', ...(year ? { year: 'numeric' } : {}) }).format(new Date(value.length === 10 ? `${value}T12:00:00Z` : value))
export const publication = (value: string | null) => value ? `${dateLabel(value)} · ${hour(value)} GMT` : 'Unavailable'

export function downloadRows(rows: EvaluationPoint[], cutoff: string, snapshot: string, name: string) {
  const headers = ['decision_date', 'cutoff_london', 'delivery_start_utc', 'delivery_end_utc', 'forecast_publish_time_utc', 'forecast_mw', 'actual_mw', 'error_mw', 'energy_error_mwh', 'paired', 'quality_flags', 'snapshot_id']
  const quote = (value: unknown) => `"${String(value ?? '').replaceAll('"', '""')}"`
  const values = rows.map(row => [row.decision_date, cutoff, row.start_time, row.end_time, row.forecast_publish_time, row.forecast_mw, row.actual_mw, row.error_mw, row.energy_error_mwh, row.paired, row.quality_flags.join('; '), snapshot])
  const csv = [headers, ...values].map(row => row.map(quote).join(',')).join('\r\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `reint-${name}-${cutoff.replace(':', '')}.csv`
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
