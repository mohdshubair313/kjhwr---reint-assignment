import { Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { dateLabel, fmt, hour } from '../format'
import type { DailyEvaluation, EvaluationPoint } from '../types'

const axis = { fontSize: 11, fill: '#586952', fontFamily: 'DM Sans Variable, sans-serif' }
const tooltipStyle = { border: '1px solid #dce5de', borderRadius: 10, boxShadow: '0 8px 28px #173d3412', fontSize: 12 }
const margin = { top: 12, right: 12, bottom: 6, left: 0 }
const valueFormat = (value: unknown) => `${fmt(value == null ? null : Number(value))} MW`

export function GenerationChart({ rows, showActuals }: { rows: EvaluationPoint[]; showActuals: boolean }) {
  return <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 280 }}>
    <ComposedChart data={rows} margin={margin} accessibilityLayer>
      <defs><linearGradient id="forecastFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#2a8c6b" stopOpacity={0.15} /><stop offset="100%" stopColor="#2a8c6b" stopOpacity={0.01} /></linearGradient></defs>
      <CartesianGrid stroke="#edf0ed" vertical={false} strokeDasharray="3 4" />
      <XAxis dataKey="start_time" tickFormatter={hour} tick={axis} axisLine={false} tickLine={false} minTickGap={30} dy={10} />
      <YAxis tick={axis} tickFormatter={v => `${Number(v) / 1000}k`} axisLine={false} tickLine={false} width={48} domain={[0, 'auto']} />
      <Tooltip formatter={valueFormat} labelFormatter={v => `${hour(String(v))} GMT · ${dateLabel(String(v))}`} contentStyle={tooltipStyle} />
      <Area dataKey="forecast_mw" name="Forecast" type="linear" stroke="#238362" strokeWidth={2.5} fill="url(#forecastFill)" connectNulls={false} isAnimationActive={false} />
      {showActuals && <Line dataKey="actual_mw" name="Actual" type="linear" stroke="#344e59" strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls={false} isAnimationActive={false} />}
    </ComposedChart>
  </ResponsiveContainer>
}

export function MonthChart({ days }: { days: DailyEvaluation[] }) {
  const data = days.map(day => ({ day: day.decision_date, mae: day.metrics.mae_mw, rmse: day.metrics.rmse_mw }))
  return <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 280 }}>
    <ComposedChart data={data} margin={margin} accessibilityLayer>
      <CartesianGrid stroke="#edf0ed" vertical={false} strokeDasharray="3 4" />
      <XAxis dataKey="day" tickFormatter={v => String(Number(String(v).slice(-2)))} tick={axis} axisLine={false} tickLine={false} minTickGap={20} dy={10} />
      <YAxis tick={axis} tickFormatter={v => `${Number(v) / 1000}k`} axisLine={false} tickLine={false} width={48} />
      <Tooltip formatter={valueFormat} labelFormatter={v => `Decision: ${dateLabel(String(v))}`} contentStyle={tooltipStyle} />
      <Bar dataKey="mae" name="MAE" fill="#75ab91" radius={[3, 3, 0, 0]} maxBarSize={20} isAnimationActive={false} />
      <Line dataKey="rmse" name="RMSE" stroke="#344e59" strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls={false} isAnimationActive={false} />
    </ComposedChart>
  </ResponsiveContainer>
}

export function ErrorChart({ rows, days, monthly }: { rows: EvaluationPoint[]; days: DailyEvaluation[]; monthly: boolean }) {
  const data = monthly ? days.map(d => ({ label: d.decision_date, error: d.metrics.bias_mw })) : rows.map(row => ({ label: row.start_time, error: row.error_mw }))
  return <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 200 }}>
    <BarChart data={data} margin={margin} accessibilityLayer>
      <CartesianGrid stroke="#edf0ed" vertical={false} strokeDasharray="3 4" />
      <XAxis dataKey="label" tickFormatter={v => monthly ? String(Number(String(v).slice(-2))) : hour(String(v))} tick={axis} axisLine={false} tickLine={false} minTickGap={25} dy={8} />
      <YAxis tick={axis} tickFormatter={v => `${Number(v) / 1000}k`} axisLine={false} tickLine={false} width={48} />
      <Tooltip formatter={valueFormat} labelFormatter={v => monthly ? `Decision: ${dateLabel(String(v))}` : `${hour(String(v))} GMT`} contentStyle={tooltipStyle} cursor={{ fill: '#f2f4f0' }} />
      <ReferenceLine y={0} stroke="#a5b2aa" />
      <Bar dataKey="error" name={monthly ? 'Daily bias' : 'Forecast − actual'} maxBarSize={22} radius={3} isAnimationActive={false}>
        {data.map(row => <Cell key={row.label} fill={(row.error ?? 0) >= 0 ? '#b57c3a' : '#527f98'} />)}
      </Bar>
    </BarChart>
  </ResponsiveContainer>
}
