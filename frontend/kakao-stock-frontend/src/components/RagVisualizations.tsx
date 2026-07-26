import type { RagVisualization } from '../types/qa'
import { Icon } from './Icon'
import { RagNewsResultItem } from './RagNewsResultItem'

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
  return currency === 'KRW' || currency === '원' || currency == null
    ? `${formatted}원`
    : `${formatted} ${currency}`
}

function safeHref(value: unknown) {
  if (typeof value !== 'string') return undefined
  try {
    const url = new URL(value, window.location.origin)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : undefined
  } catch {
    return undefined
  }
}

function sentiment(value: unknown) {
  return value === 'positive' || value === 'negative' || value === 'neutral' ? value : undefined
}

function NewsResults({ visualization }: { visualization: RagVisualization }) {
  const items = records(visualization.data.items)
  if (items.length === 0) return null
  return (
    <section className="answer-news">
      <header className="answer-section-heading">
        <div><span>관련 뉴스</span><strong>{visualization.title}</strong></div>
        <em>{items.length}건</em>
      </header>
      <div className="news-list answer-news-list">
        {items.slice(0, 6).map((item, index) => (
          <RagNewsResultItem
            key={`${text(item.source_id)}-${index}`}
            publishedAt={typeof item.published_at === 'string' ? item.published_at : undefined}
            publisher={typeof item.publisher === 'string' ? item.publisher : undefined}
            sentiment={sentiment(item.sentiment)}
            snippet={typeof item.snippet === 'string' ? item.snippet : undefined}
            stockCode={typeof item.stock_code === 'string' ? item.stock_code : undefined}
            title={text(item.title, '제목 없는 뉴스')}
            url={safeHref(item.url)}
          />
        ))}
      </div>
    </section>
  )
}

function PriceChart({ visualization }: { visualization: RagVisualization }) {
  const points = records(visualization.data.points).filter(
    (point) => typeof point.close === 'number' && typeof point.trading_day === 'string',
  )
  if (points.length < 2) return null
  const values = points.map((point) => point.close as number)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const coords = points.map((point, index) => ({
    x: 10 + (index / (points.length - 1)) * 580,
    y: 154 - (((point.close as number) - min) / span) * 120,
  }))
  const path = coords.map((point, index) => (
    `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`
  )).join(' ')
  const area = `${path} L 590 166 L 10 166 Z`
  const quote = record(visualization.data.quote)
  const period = record(visualization.data.period)
  const last = points.at(-1)
  const returnPct = typeof period.return_pct === 'number' ? period.return_pct : undefined

  return (
    <section className="answer-price-chart">
      <header>
        <div><span>주가</span><strong>{visualization.title}</strong></div>
        <div className="answer-price-chart__quote">
          <strong>{won(quote.price ?? last?.close, quote.currency)}</strong>
          {returnPct !== undefined && (
            <em className={returnPct >= 0 ? 'is-up' : 'is-down'}>
              {returnPct > 0 ? '+' : ''}{returnPct}%
            </em>
          )}
        </div>
      </header>
      <svg aria-label={`${text(points[0]?.trading_day)}부터 ${text(last?.trading_day)}까지의 주가 흐름`} role="img" viewBox="0 0 600 176">
        <defs>
          <linearGradient id="answer-price-area" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="var(--brand)" stopOpacity=".22" />
            <stop offset="1" stopColor="var(--brand)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path className="answer-price-chart__grid" d="M10 34H590M10 94H590M10 154H590" />
        <path className="answer-price-chart__area" d={area} />
        <path className="answer-price-chart__line" d={path} />
      </svg>
      <footer>
        <span>{text(points[0]?.trading_day)}</span>
        <span>최저 {won(min)} · 최고 {won(max)}</span>
        <span>{text(last?.trading_day)}</span>
      </footer>
    </section>
  )
}

function PriceSnapshot({ visualization }: { visualization: RagVisualization }) {
  const quote = record(visualization.data.quote)
  const period = record(visualization.data.period)
  if (Object.keys(quote).length === 0 && Object.keys(period).length === 0) return null
  return (
    <section className="answer-metrics">
      <header className="answer-section-heading">
        <div><span>시장 데이터</span><strong>{visualization.title}</strong></div>
      </header>
      <div>
        {typeof quote.price === 'number' && <article><small>현재가</small><strong>{won(quote.price, quote.currency)}</strong><span>{text(quote.trading_day)}</span></article>}
        {typeof period.return_pct === 'number' && <article><small>기간 수익률</small><strong>{period.return_pct > 0 ? '+' : ''}{period.return_pct}%</strong><span>{text(period.start_trading_day)} → {text(period.end_trading_day)}</span></article>}
      </div>
    </section>
  )
}

function EventReturn({ visualization }: { visualization: RagVisualization }) {
  const data = visualization.data
  if (typeof data.return_pct !== 'number') return null
  return (
    <section className="answer-event-return">
      <header className="answer-section-heading">
        <div><span>주가 변화</span><strong>{visualization.title}</strong></div>
        <em className={(data.return_pct as number) >= 0 ? 'is-up' : 'is-down'}>
          {(data.return_pct as number) > 0 ? '+' : ''}{data.return_pct}%
        </em>
      </header>
      <div>
        <article><small>발표 전</small><strong>{won(data.start_close, data.currency)}</strong><span>{text(data.start_trading_day)}</span></article>
        <Icon name="arrow-right" size={19} />
        <article><small>발표 후</small><strong>{won(data.end_close, data.currency)}</strong><span>{text(data.end_trading_day)}</span></article>
      </div>
      <p>발표 전후 거래일의 가격 변화이며 직접적인 인과관계를 뜻하지 않습니다.</p>
    </section>
  )
}

function FinancialMetrics({ visualization }: { visualization: RagVisualization }) {
  const items = records(visualization.data.items)
  if (items.length === 0) return null
  return (
    <section className="answer-metrics">
      <header className="answer-section-heading">
        <div><span>DART</span><strong>{visualization.title}</strong></div>
        <em>공식 실적</em>
      </header>
      <div>
        {items.map((item, index) => (
          <article key={`${text(item.label)}-${index}`}>
            <small>{text(item.label)}</small>
            <strong>{text(item.value_display, won(item.value_won, item.unit))}</strong>
            <span>{[item.period, item.basis].filter((value) => typeof value === 'string' && value).join(' · ')}</span>
          </article>
        ))}
      </div>
    </section>
  )
}

function BrokerTargets({ visualization }: { visualization: RagVisualization }) {
  const items = records(visualization.data.items)
  if (items.length === 0) return null
  return (
    <section className="answer-broker-targets">
      <header className="answer-section-heading">
        <div><span>리서치</span><strong>{visualization.title}</strong></div>
        <em>전망</em>
      </header>
      <div>
        {items.map((item, index) => (
          <article key={`${text(item.broker)}-${text(item.report_date)}-${index}`}>
            <span><strong>{text(item.broker, '증권사')}</strong><small>{text(item.report_date)}</small></span>
            <b>{won(item.target_price, item.target_price_currency)}</b>
            <em>{text(item.investment_opinion, '의견 미표기')}</em>
          </article>
        ))}
      </div>
      <p>증권사 전망치이며 실제 가격이나 확정 실적이 아닙니다.</p>
    </section>
  )
}

const DISCLOSURE_LABELS: Record<string, string> = {
  contract_amount: '계약금액',
  contract_counterparty: '계약상대',
  contract_end_date: '계약 종료일',
  contract_start_date: '계약 시작일',
  decision_amount: '결정금액',
  ratio_to_revenue: '매출 대비',
}

function DisclosureMetrics({ visualization }: { visualization: RagVisualization }) {
  const items = records(visualization.data.items)
  if (items.length === 0) return null
  return (
    <section className="answer-disclosures">
      <header className="answer-section-heading">
        <div><span>DART</span><strong>{visualization.title}</strong></div>
      </header>
      <div>
        {items.map((item, index) => {
          const normalized = Object.entries(record(item.normalized_data)).filter(([, value]) => (
            typeof value === 'string' || typeof value === 'number'
          )).slice(0, 4)
          return (
            <article key={`${text(item.rcept_no)}-${index}`}>
              <header><strong>{text(item.event_type, '공시')}</strong><time>{text(item.announced_at, '')}</time></header>
              {normalized.length > 0 && <dl>{normalized.map(([key, value]) => <div key={key}><dt>{DISCLOSURE_LABELS[key] ?? key.replaceAll('_', ' ')}</dt><dd>{text(value)}</dd></div>)}</dl>}
              {typeof item.summary === 'string' && <p>{item.summary}</p>}
            </article>
          )
        })}
      </div>
    </section>
  )
}

function TermDefinition({ visualization }: { visualization: RagVisualization }) {
  return (
    <aside className="answer-term">
      <span>용어</span>
      <div><strong>{text(visualization.data.term, visualization.title)}</strong><p>{text(visualization.data.easy_definition, text(visualization.data.official_definition))}</p></div>
    </aside>
  )
}

function EventTimeline({ visualization }: { visualization: RagVisualization }) {
  const events = records(visualization.data.events)
  if (events.length === 0) return null
  return (
    <section className="answer-timeline">
      <header className="answer-section-heading">
        <div><span>흐름</span><strong>{visualization.title}</strong></div>
      </header>
      <ol>
        {events.map((event, index) => {
          const href = safeHref(event.url)
          const body = <><time>{text(event.at).slice(0, 10)}</time><span>{event.kind === 'disclosure' ? '공시' : '뉴스'}</span><strong>{text(event.title, '제목 없음')}</strong></>
          return <li key={`${text(event.source_id)}-${index}`}>{href ? <a href={href} rel="noreferrer" target="_blank">{body}</a> : <div>{body}</div>}</li>
        })}
      </ol>
    </section>
  )
}

export function RagVisualizations({ visualizations }: { visualizations: RagVisualization[] }) {
  return (
    <div className="answer-visuals">
      {visualizations.map((visualization, index) => {
        const key = `${visualization.type}-${visualization.sourceIds.join('-')}-${index}`
        if (visualization.type === 'news_cards') return <NewsResults key={key} visualization={visualization} />
        if (visualization.type === 'price_line') return <PriceChart key={key} visualization={visualization} />
        if (visualization.type === 'price_snapshot') return <PriceSnapshot key={key} visualization={visualization} />
        if (visualization.type === 'event_return') return <EventReturn key={key} visualization={visualization} />
        if (visualization.type === 'financial_series' || visualization.type === 'financial_comparison') return <FinancialMetrics key={key} visualization={visualization} />
        if (visualization.type === 'broker_targets') return <BrokerTargets key={key} visualization={visualization} />
        if (visualization.type === 'disclosure_metrics') return <DisclosureMetrics key={key} visualization={visualization} />
        if (visualization.type === 'term_definition') return <TermDefinition key={key} visualization={visualization} />
        if (visualization.type === 'event_timeline') return <EventTimeline key={key} visualization={visualization} />
        return null
      })}
    </div>
  )
}
