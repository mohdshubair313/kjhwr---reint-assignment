import { lazy, Suspense, useState } from 'react'
import type { FormEvent } from 'react'
import { Activity, ArrowDownToLine, ArrowRight, ArrowUpRight, BarChart3, BookOpen, CalendarDays, Check, CheckCheck, ChevronDown, ChevronRight, CircleHelp, Clock3, Database, FileCheck2, Leaf, LoaderCircle, RefreshCw, ShieldCheck, TrendingUp, TriangleAlert, Wind } from 'lucide-react'
import { useDashboard } from './api'
import { dateLabel, downloadRows, fmt, hour, percent, publication, signed } from './format'
import type { DashboardData, Metrics, Query } from './types'
import './App.css'

const GenerationChart = lazy(() => import('./components/Charts').then(m => ({ default: m.GenerationChart })))
const MonthChart = lazy(() => import('./components/Charts').then(m => ({ default: m.MonthChart })))
const ErrorChart = lazy(() => import('./components/Charts').then(m => ({ default: m.ErrorChart })))
type View = 'day' | 'month'

function initialQuery(): Query {
  const params = new URLSearchParams(window.location.search)
  const date = params.get('date') ?? '2026-01-15'
  const cutoff = params.get('cutoff') ?? '09:00'
  return { date: /^2026-01-(0[1-9]|[12][0-9]|3[01])$/.test(date) ? date : '2026-01-15', cutoff: /^([01][0-9]|2[0-3]):[0-5][0-9]$/.test(cutoff) ? cutoff : '09:00' }
}

function StatCards({ metrics }: { metrics: Metrics }) {
  const stats = [
    { label: 'Mean absolute error', value: fmt(metrics.mae_mw), unit: 'MW', description: 'Typical forecast miss', icon: Activity, title: 'Average size of the error, regardless of direction.' },
    { label: 'Forecast bias', value: signed(metrics.bias_mw), unit: 'MW', description: metrics.bias_mw == null ? 'No paired observations' : metrics.bias_mw > 0 ? 'Wind overforecast on average' : metrics.bias_mw < 0 ? 'Wind underforecast on average' : 'No average directional error', icon: TrendingUp, title: 'Forecast minus actual. Positive means overforecasting.' },
    { label: 'Root mean square error', value: fmt(metrics.rmse_mw), unit: 'MW', description: 'More weight on larger misses', icon: BarChart3, title: 'Square root of the average squared error.' },
    { label: 'Matched data coverage', value: percent(metrics.coverage), unit: '', description: `${metrics.paired_hours} of ${metrics.expected_hours} delivery hours`, icon: ShieldCheck, title: 'Hours with a forecast and both actual half-hours.' },
  ]
  return <div className="stats-grid">{stats.map((stat, i) => <article className={`stat-card ${i === 0 ? 'stat-featured' : ''}`} key={stat.label}>
    <div className="stat-label"><span>{stat.label}</span><stat.icon size={16} aria-hidden="true" /></div>
    <div className="stat-value" title={stat.title}>{stat.value}<span>{stat.unit}</span></div>
    <p>{i === 3 && metrics.coverage === 1 && <Check size={13} aria-hidden="true" />}{stat.description}</p>
  </article>)}</div>
}

function ChartLoading() { return <div className="chart-loading" role="status"><LoaderCircle size={20} className="spin" /> Loading chart…</div> }

function Dashboard({ data, query, view, onSelectDay }: { data: DashboardData; query: Query; view: View; onSelectDay: (date: string) => void }) {
  const [showActuals, setShowActuals] = useState(true)
  const monthly = view === 'month'
  const { evaluation, forecast, metadata } = data
  const day = evaluation.days.find(d => d.decision_date === query.date)
  const rows = monthly ? evaluation.rows : evaluation.rows.filter(row => row.decision_date === query.date)
  const metrics = monthly ? evaluation.summary : day?.metrics
  if (!metrics || rows.length === 0) return <section className="message-panel" role="status"><Database /><h2>No delivery intervals available</h2><p>Try another decision date or reload the dataset.</p></section>
  const publications = [...new Set(forecast.rows.map(row => row.forecast_publish_time).filter((v): v is string => v !== null))].sort()
  const ages = forecast.rows.map(row => row.forecast_age_hours).filter((v): v is number => v !== null)
  const hasForecast = monthly ? metrics.forecast_hours > 0 : forecast.forecast_hours > 0
  const hasActual = metrics.actual_hours > 0
  const rangeLabel = monthly ? '1–31 January decisions' : `${dateLabel(forecast.delivery_date)} delivery`
  return <div className="dashboard-content" data-testid="dashboard">
    <div className="section-caption"><span><span className="live-dot" />{monthly ? 'MONTHLY PERFORMANCE' : 'DELIVERY-DAY PERFORMANCE'}</span><span>{rangeLabel} <span className="caption-separator">/</span> Retrospective evaluation</span></div>
    <StatCards metrics={metrics} />
    {metrics.coverage < 1 && <div className="quality-notice" role="status"><TriangleAlert size={18} /><div><strong>{metrics.paired_hours === 0 ? 'No complete forecast–actual pairs' : 'Some delivery hours are incomplete'}</strong><p>Metrics use {metrics.paired_hours} of {metrics.expected_hours} hours. Missing values stay blank and chart gaps are not filled.</p></div></div>}
    <div className="analysis-grid">
      <section className="panel main-chart">
        <div className="panel-heading"><div><span className="eyebrow">{monthly ? 'THE MONTH AT A GLANCE' : 'THE DELIVERY PICTURE'}</span><h2>{monthly ? 'How accuracy changed' : 'Wind forecast vs actual'}</h2><p>{monthly ? `Daily errors · ${query.cutoff} London decision cutoff` : `${dateLabel(forecast.delivery_date, true)} · Hourly generation · MW`}</p></div><span className="panel-icon"><Wind size={20} /></span></div>
        <div className="chart-toolbar"><div className="legend"><span><i className="legend-line green" />{monthly ? 'MAE' : 'Forecast'}</span><span><i className="legend-line dark" />{monthly ? 'RMSE' : 'Actual'}</span></div>{!monthly && <label className="toggle-label"><input type="checkbox" checked={showActuals} onChange={e => setShowActuals(e.target.checked)} /><span className="toggle-track" />Show actuals</label>}</div>
        <div className="chart-space" role="region" aria-label={monthly ? 'Daily accuracy chart in megawatts' : 'Hourly wind generation chart in megawatts'}>
          {(monthly ? metrics.paired_hours > 0 : hasForecast || (hasActual && showActuals)) ? <Suspense fallback={<ChartLoading />}>{monthly ? <MonthChart days={evaluation.days} /> : <GenerationChart rows={rows} showActuals={showActuals} />}</Suspense> : <div className="chart-empty"><Wind /><p>{monthly ? 'No paired observations to calculate daily accuracy.' : 'No generation series available for this view.'}</p></div>}
        </div>
        <div className="chart-footnote"><Clock3 size={13} /><span>{monthly ? 'Horizontal axis: January decision date. Each decision targets the next day.' : 'All times GMT · Actuals shown retrospectively, after delivery.'}</span></div>
      </section>
      <aside className="briefing panel">
        <div className="briefing-top"><span className="eyebrow">{monthly ? 'JANUARY IN CONTEXT' : 'AT THE DECISION DESK'}</span><span className="leaf-badge"><Leaf size={16} /></span></div>
        <h2>{monthly ? 'The bigger picture.' : 'Know what was known.'}</h2>
        <p className="briefing-intro">{monthly ? 'One consistent cutoff. Every delivery hour. A transparent view of forecast accuracy.' : 'Only forecasts published by your decision cutoff are eligible for this delivery day.'}</p>
        <dl className="briefing-facts">
          <div><dt>{monthly ? 'Decision window' : 'Decision cutoff'}</dt><dd>{monthly ? '1–31 Jan 2026' : `${dateLabel(query.date)} · ${query.cutoff} GMT`}</dd></div>
          <div><dt>{monthly ? 'Delivery window' : 'Forecast publication'}</dt><dd>{monthly ? '2 Jan – 1 Feb 2026' : publications.length === 1 ? publication(publications[0]) : publications.length ? `${publications.length} publication vintages` : 'No eligible forecast'}</dd></div>
          <div><dt>{monthly ? 'Cutoff each day' : 'Age at decision'}</dt><dd>{monthly ? `${query.cutoff} GMT` : ages.length ? `${fmt(Math.min(...ages))}${Math.min(...ages) !== Math.max(...ages) ? `–${fmt(Math.max(...ages))}` : ''} hours` : 'Unavailable'}</dd></div>
        </dl>
        {!monthly && forecast.mixed_forecast_vintages && <p className="inline-warning">Some hours use older publications. See the data table for details.</p>}
        <div className="assumption-note"><CircleHelp size={16} /><p>The cutoff is a pilot assumption, not a verified market deadline.</p></div>
      </aside>
    </div>
    <div className="analysis-grid secondary-grid">
      <section className="panel error-panel">
        <div className="panel-heading"><div><span className="eyebrow">UNDERSTAND THE DIRECTION</span><h2>{monthly ? 'Daily forecast bias' : 'Where the forecast missed'}</h2><p>Forecast minus actual · MW</p></div><div className="legend compact"><span><i className="legend-square amber" />Overforecast</span><span><i className="legend-square blue" />Underforecast</span></div></div>
        <div className="error-chart-space">{metrics.paired_hours ? <Suspense fallback={<ChartLoading />}><ErrorChart rows={rows} days={evaluation.days} monthly={monthly} /></Suspense> : <div className="chart-empty"><Activity /><p>No paired observations to calculate errors.</p></div>}</div>
      </section>
      <section className="panel context-panel"><span className="eyebrow">BEYOND THE AVERAGE</span><h2>Size. Direction. Context.</h2><div className="context-metric"><span>P90 absolute error</span><strong>{fmt(metrics.p90_absolute_error_mw)} <small>MW</small></strong><p>The 90th percentile of historical absolute errors.</p></div><div className="context-metric"><span>Net energy error</span><strong>{signed(metrics.signed_energy_error_mwh)} <small>MWh</small></strong><p>Signed errors can cancel. Read alongside MAE.</p></div><a href="#methodology" className="text-link">How we calculate these <ArrowUpRight size={14} /></a></section>
    </div>
    <details className="panel data-details" key={view}>
      <summary><div className="summary-title"><FileCheck2 size={18} /><div><h2>{monthly ? 'Daily performance ledger' : 'Inspect the hourly data'}</h2><p>{monthly ? '31 decision days · Select a day to replay its forecast' : 'Publication times, values and data-quality flags'}</p></div></div><span className="summary-action">View data <ChevronDown size={16} /></span></summary>
      <div className="table-scroll" role="region" tabIndex={0} aria-label={monthly ? 'Daily performance table, scroll horizontally if needed' : 'Hourly data table, scroll horizontally if needed'}>
        {monthly ? <table><caption className="sr-only">Daily forecast accuracy for January 2026 decisions</caption><thead><tr><th>Decision date</th><th>Delivery date</th><th>MAE (MW)</th><th>Bias (MW)</th><th>RMSE (MW)</th><th>Coverage</th><th><span className="sr-only">Replay</span></th></tr></thead><tbody>{evaluation.days.map(d => <tr key={d.decision_date}><td>{dateLabel(d.decision_date)}</td><td>{dateLabel(d.delivery_date)}</td><td>{fmt(d.metrics.mae_mw)}</td><td>{signed(d.metrics.bias_mw)}</td><td>{fmt(d.metrics.rmse_mw)}</td><td>{d.metrics.paired_hours}/{d.metrics.expected_hours} hours</td><td><button className="table-button" onClick={() => onSelectDay(d.decision_date)} aria-label={`Replay ${dateLabel(d.decision_date)}`}>Replay <ArrowUpRight size={13} /></button></td></tr>)}</tbody></table>
          : <table><caption className="sr-only">Hourly forecast and actual generation for {forecast.delivery_date}</caption><thead><tr><th>Delivery (GMT)</th><th>Forecast (MW)</th><th>Actual (MW)</th><th>Error (MW)</th><th>Forecast published (GMT)</th><th>Quality</th></tr></thead><tbody>{rows.map(row => <tr key={row.start_time}><td>{hour(row.start_time)}–{hour(row.end_time)}</td><td>{fmt(row.forecast_mw)}</td><td>{fmt(row.actual_mw)}</td><td>{signed(row.error_mw)}</td><td>{publication(row.forecast_publish_time)}</td><td>{row.quality_flags.length ? row.quality_flags.map(flag => flag.replaceAll('_', ' ')).join(' · ') : <span className="quality-good"><Check size={12} /> Complete</span>}</td></tr>)}</tbody></table>}
      </div>
    </details>
    <section id="methodology" className="methodology panel"><details><summary><div className="summary-title"><BookOpen size={18} /><div><h2>Transparent by design</h2><p>Methodology, assumptions & data provenance</p></div></div><ChevronDown size={18} /></summary><div className="methodology-content"><div><h3>How to read this analysis</h3><ul>{metadata.methodology.map(text => <li key={text}>{text}</li>)}</ul></div><div id="sources"><h3>From source to screen</h3><p>Source: Elexon Insights · WINDFOR forecasts and FUELHH wind actuals.</p><p>This snapshot contains {fmt(metadata.record_counts.forecast_records)} forecasts and {fmt(metadata.record_counts.actual_records)} actual records.</p><p>Actuals use the latest publication retained in the snapshot. Historical results are not a prediction interval or a procurement recommendation.</p><div className="source-links"><a href="https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream" target="_blank" rel="noreferrer">WINDFOR documentation <ArrowUpRight size={14} /></a><a href="https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream" target="_blank" rel="noreferrer">FUELHH documentation <ArrowUpRight size={14} /></a></div><dl className="provenance"><dt>Dataset acquired</dt><dd>{[...new Set(metadata.sources.map(s => (s.retrieved_at ?? s.retrieved_date)?.slice(0, 10)).filter((v): v is string => !!v))].map(d => dateLabel(d, true)).join(', ') || 'Not recorded'}</dd><dt>Snapshot reference</dt><dd className="snapshot-hash">{metadata.snapshot_id}</dd></dl></div></div></details></section>
    <footer className="page-footer"><span><Leaf size={13} /> Elexon wind data. Considered decisions.</span><span>January 2026 pilot <span>·</span> Europe/London</span></footer>
  </div>
}

function App() {
  const [query, setQuery] = useState<Query>(initialQuery)
  const [draft, setDraft] = useState<Query>(query)
  const [view, setView] = useState<View>('day')
  const [revision, setRevision] = useState(0)
  const state = useDashboard(query, revision)
  const loading = !state.data && !state.error
  function apply(event: FormEvent) {
    event.preventDefault()
    setQuery({ ...draft })
    window.history.replaceState(null, '', `?${new URLSearchParams({ date: draft.date, cutoff: draft.cutoff })}`)
  }
  function replay(date: string) {
    setQuery({ ...query, date }); setDraft({ ...query, date }); setView('day')
    window.history.replaceState(null, '', `?${new URLSearchParams({ date, cutoff: query.cutoff })}`)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  function methodology() {
    const node = document.querySelector<HTMLDetailsElement>('#methodology > details')
    if (node) { node.open = true; node.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
  }
  const exportRows = state.data ? view === 'month' ? state.data.evaluation.rows : state.data.evaluation.rows.filter(r => r.decision_date === query.date) : []
  const dirty = draft.date !== query.date || draft.cutoff !== query.cutoff
  return <div className="app-shell">
    <a className="skip-link" href="#main">Skip to analysis</a>
    <aside className="sidebar">
      <a href="/" className="brand" aria-label="REint home"><span className="brand-mark"><Wind size={27} strokeWidth={1.7} /></span><span>reint<span className="brand-dot">.</span></span></a>
      <p className="brand-subtitle">ENERGY INTELLIGENCE</p>
      <div className="nav-label">WORKSPACE</div>
      <nav aria-label="Workspace"><button aria-label="Decision replay" className={view === 'day' ? 'nav-item active' : 'nav-item'} onClick={() => setView('day')} aria-current={view === 'day' ? 'page' : undefined}><Wind size={18} /><span>Decision replay</span><ChevronRight size={14} className="nav-arrow" /></button><button aria-label="January review" className={view === 'month' ? 'nav-item active' : 'nav-item'} onClick={() => setView('month')} aria-current={view === 'month' ? 'page' : undefined}><BarChart3 size={18} /><span>January review</span><ChevronRight size={14} className="nav-arrow" /></button><button aria-label="Methodology" className="nav-item" onClick={methodology} disabled={!state.data}><BookOpen size={18} /><span>Methodology</span></button></nav>
      <div className="sidebar-study"><div className="study-symbol"><Wind size={34} strokeWidth={1} /><span>01 / 2026</span></div><h3>A month in focus.</h3><p>National wind forecasts.<br />A clearer day-ahead picture.</p><span className="study-divider" /><div><span>31 decision days</span><span className="tiny-dot" /></div></div>
      <div className="sidebar-footer"><span className="desk-avatar"><Leaf size={19} /></span><div><strong>UK energy desk</strong><span>National wind · Elexon</span></div></div>
    </aside>
    <div className="workspace">
      <header className="topbar"><div className="breadcrumb"><span>Workspace</span><ChevronRight size={13} /><strong>Wind intelligence</strong></div><span className="historical-badge"><span />Historical analysis</span></header>
      <main id="main">
        <div className="page-heading"><div><div className="eyebrow page-eyebrow"><span />DAY-AHEAD INTELLIGENCE</div><h1>A clearer view of wind.</h1><p>Explore what was forecast. Understand what followed.</p></div><button className="button export-button" disabled={!state.data} onClick={() => state.data && downloadRows(exportRows, query.cutoff, state.data.metadata.snapshot_id, view === 'month' ? 'january-2026' : query.date)}><ArrowDownToLine size={16} />Export CSV</button></div>
        <div className="view-tabs" role="group" aria-label="Analysis view"><button className={view === 'day' ? 'selected' : ''} aria-pressed={view === 'day'} onClick={() => setView('day')}><Wind size={16} />Decision replay</button><button className={view === 'month' ? 'selected' : ''} aria-pressed={view === 'month'} onClick={() => setView('month')}><BarChart3 size={16} />January review</button><span className="tabs-note"><CalendarDays size={14} /> January 2026</span></div>
        <form className="filter-panel" onSubmit={apply} aria-label="Decision filters"><div className="filter-description"><span className="filter-icon"><CalendarDays size={19} /></span><div><strong>{view === 'month' ? 'Review the full month' : 'Revisit a decision'}</strong><p>{view === 'month' ? '1–31 Jan decisions · 2 Jan–1 Feb delivery' : 'Your decision date sets next-day delivery'}</p></div></div><div className="filter-inputs"><label>Decision date<input type="date" min="2026-01-01" max="2026-01-31" value={draft.date} required disabled={view === 'month'} onChange={e => setDraft({ ...draft, date: e.target.value })} /></label><label>Decision cutoff <span>(GMT)</span><input type="time" value={draft.cutoff} required step={60} onChange={e => setDraft({ ...draft, cutoff: e.target.value })} /></label><button className="button button-primary" type="submit" disabled={loading}>{loading ? <LoaderCircle size={15} className="spin" /> : <ArrowRight size={16} />}Apply{dirty ? ' changes' : ''}</button></div></form>
        <div className="scope-note"><CircleHelp size={13} /><span>Historical replay · Configurable cutoff assumption · Actuals are retrospective</span>{dirty && <strong>Changes not yet applied</strong>}</div>
        {loading && <section className="loading-state" aria-busy="true" role="status"><div className="loading-caption"><LoaderCircle size={18} className="spin" />Loading verified wind data…</div><div className="stats-grid">{[1, 2, 3, 4].map(i => <div className="skeleton skeleton-card" key={i} />)}</div><div className="skeleton skeleton-chart" /></section>}
        {state.error && <section className="message-panel" role="alert"><TriangleAlert size={30} /><h2>We couldn’t load this analysis</h2><p>{state.error}</p><button className="button button-primary" onClick={() => setRevision(v => v + 1)}><RefreshCw size={15} />Try again</button></section>}
        {state.data && <Dashboard data={state.data} query={query} view={view} onSelectDay={replay} />}
        <div className="integrity-strip"><CheckCheck size={14} /><span>Latest eligible forecast. Consistent comparisons. Traceable data.</span></div>
      </main>
    </div>
  </div>
}

export default App
