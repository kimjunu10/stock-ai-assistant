import type { RagVisualization } from '../types/qa'
import { Icon } from './Icon'

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function records(value: unknown) {
  return Array.isArray(value) ? value.map(record) : []
}

function text(value: unknown, fallback = '—') {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : fallback
}

function won(value: unknown, currency?: unknown) {
  if (typeof value !== 'number') return '—'
  const formatted = new Intl.NumberFormat('ko-KR').format(value)
  return currency === 'KRW' || currency === '원' || currency == null ? `${formatted}원` : `${formatted} ${currency}`
}

function PriceLine({ visualization }: { visualization: RagVisualization }) {
  const points = records(visualization.data.points).filter(
    (point) => typeof point.close === 'number' && typeof point.trading_day === 'string',
  )
  if (points.length < 2) return null
  const values = points.map((point) => point.close as number)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const path = points.map((point, index) => {
    const x = 8 + (index / (points.length - 1)) * 284
    const y = 84 - (((point.close as number) - min) / span) * 68
    return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
  }).join(' ')
  const first = points[0]
  const last = points.at(-1)
  return (
    <article className="rag-viz rag-viz--line">
      <header><Icon name="chart" size={17} /><strong>{visualization.title}</strong><span>실제값</span></header>
      <svg aria-label={`${text(first?.trading_day)} ${won(first?.close)}부터 ${text(last?.trading_day)} ${won(last?.close)}까지의 실제 주가 흐름`} role="img" viewBox="0 0 300 96">
        <path className="rag-line-grid" d="M8 16H292M8 50H292M8 84H292" />
        <path className="rag-line-path" d={path} />
      </svg>
      <div className="rag-viz__range">
        <span>{text(first?.trading_day)} · {won(first?.close)}</span>
        <span>{text(last?.trading_day)} · {won(last?.close)}</span>
      </div>
    </article>
  )
}

function PriceSnapshot({ visualization }: { visualization: RagVisualization }) {
  const quote = record(visualization.data.quote)
  const period = record(visualization.data.period)
  if (Object.keys(quote).length === 0 && Object.keys(period).length === 0) return null
  return (
    <article className="rag-viz">
      <header><Icon name="chart" size={17} /><strong>{visualization.title}</strong><span>실제 시장 가격</span></header>
      <div className="rag-metric-grid">
        {typeof quote.price === 'number' && <div><small>현재가</small><strong>{won(quote.price, quote.currency)}</strong><span>{text(quote.trading_day)} 거래일</span></div>}
        {typeof period.return_pct === 'number' && <div><small>기간 수익률</small><strong>{period.return_pct > 0 ? '+' : ''}{period.return_pct}%</strong><span>{text(period.start_trading_day)} → {text(period.end_trading_day)}</span></div>}
      </div>
    </article>
  )
}

function EventReturn({ visualization }: { visualization: RagVisualization }) {
  const data = visualization.data
  if (typeof data.return_pct !== 'number') return null
  return (
    <article className="rag-viz">
      <header><Icon name="chart" size={17} /><strong>{visualization.title}</strong><span>시간적 변화 · 인과 아님</span></header>
      <div className="rag-return">
        <div><small>발표 전</small><strong>{won(data.start_close, data.currency)}</strong><span>{text(data.start_trading_day)}</span></div>
        <Icon name="arrow-right" size={18} />
        <div><small>발표 후</small><strong>{won(data.end_close, data.currency)}</strong><span>{text(data.end_trading_day)}</span></div>
        <em>{(data.return_pct as number) > 0 ? '+' : ''}{data.return_pct}%</em>
      </div>
      <p>{text(data.note, '발표 전후 실제 거래일 기준 변화입니다. 직접적인 인과관계를 뜻하지 않습니다.')}</p>
    </article>
  )
}

function FinancialSeries({ visualization }: { visualization: RagVisualization }) {
  const items = records(visualization.data.items)
  if (items.length === 0) return null
  return (
    <article className="rag-viz">
      <header><Icon name="document" size={17} /><strong>{visualization.title}</strong><span>공식 실제값</span></header>
      <div className="rag-metric-grid">
        {items.map((item, index) => (
          <div key={`${text(item.label)}-${index}`}>
            <small>{text(item.label)}</small>
            <strong>{text(item.value_display, won(item.value_won, item.unit))}</strong>
            <span>{text(item.period)} · {text(item.basis)} · {text(item.value_kind, 'actual')}</span>
          </div>
        ))}
      </div>
    </article>
  )
}

function BrokerTargets({ visualization }: { visualization: RagVisualization }) {
  const items = records(visualization.data.items)
  if (items.length === 0) return null
  return (
    <article className="rag-viz">
      <header><Icon name="chart" size={17} /><strong>{visualization.title}</strong><span>증권사 전망</span></header>
      <div className="rag-target-list">
        {items.map((item, index) => (
          <div key={`${text(item.broker)}-${text(item.report_date)}-${index}`}>
            <span><strong>{text(item.broker, '증권사')}</strong><small>{text(item.report_date)}</small></span>
            <b>{won(item.target_price, item.target_price_currency)}</b>
            <p>{text(item.investment_opinion, '투자의견 미표기')} · 전망값</p>
          </div>
        ))}
      </div>
      <p>목표주가는 증권사의 전망이며 실제 시장 가격이나 확정값이 아닙니다.</p>
    </article>
  )
}

function DisclosureMetrics({ visualization }: { visualization: RagVisualization }) {
  const items = records(visualization.data.items)
  if (items.length === 0) return null
  return (
    <article className="rag-viz">
      <header><Icon name="document" size={17} /><strong>{visualization.title}</strong><span>DART 공시</span></header>
      <div className="rag-disclosure-list">
        {items.map((item, index) => {
          const normalized = Object.entries(record(item.normalized_data)).filter(([, value]) => (
            typeof value === 'string' || typeof value === 'number'
          )).slice(0, 4)
          return (
            <div key={`${text(item.rcept_no)}-${index}`}>
              <strong>{text(item.event_type, '구조화 공시')}</strong>
              <span>{text(item.announced_at)}</span>
              {normalized.length > 0 && <dl>{normalized.map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{text(value)}</dd></div>)}</dl>}
              {typeof item.summary === 'string' && <p>{item.summary}</p>}
            </div>
          )
        })}
      </div>
    </article>
  )
}

function TermDefinition({ visualization }: { visualization: RagVisualization }) {
  return (
    <article className="rag-viz rag-viz--term">
      <header><Icon name="info" size={17} /><strong>{text(visualization.data.term, visualization.title)}</strong><span>금융용어</span></header>
      <p>{text(visualization.data.easy_definition, text(visualization.data.official_definition))}</p>
    </article>
  )
}

export function RagVisualizations({ visualizations }: { visualizations: RagVisualization[] }) {
  return (
    <div className="rag-visualizations">
      {visualizations.map((visualization, index) => {
        const key = `${visualization.type}-${visualization.sourceIds.join('-')}-${index}`
        if (visualization.type === 'price_line') return <PriceLine key={key} visualization={visualization} />
        if (visualization.type === 'price_snapshot') return <PriceSnapshot key={key} visualization={visualization} />
        if (visualization.type === 'event_return') return <EventReturn key={key} visualization={visualization} />
        if (visualization.type === 'financial_series' || visualization.type === 'financial_comparison') return <FinancialSeries key={key} visualization={visualization} />
        if (visualization.type === 'broker_targets') return <BrokerTargets key={key} visualization={visualization} />
        if (visualization.type === 'disclosure_metrics') return <DisclosureMetrics key={key} visualization={visualization} />
        if (visualization.type === 'term_definition') return <TermDefinition key={key} visualization={visualization} />
        return null
      })}
    </div>
  )
}
