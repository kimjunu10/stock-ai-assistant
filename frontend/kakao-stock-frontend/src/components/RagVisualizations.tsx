import type { RagSource, RagVisualization } from '../types/qa'
import { RagNewsResultItem } from './RagNewsResultItem'
import { RagPriceChart, type RagPricePoint } from './RagPriceChart'

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

function newsClusterUrl(item: Record<string, unknown>, source?: RagSource) {
  const candidates = [
    item.cluster_id,
    source?.locator.cluster_id,
    source?.locator.source_pk,
    item.source_id,
    source?.sourceId,
  ]
  for (const candidate of candidates) {
    const match = String(candidate ?? '').match(/^(?:news_cluster:)?(\d+)$/)
    if (match?.[1]) return `/news?cluster=${match[1]}`
  }
  return undefined
}

function NewsResults({ sources, visualization }: { sources: RagSource[]; visualization: RagVisualization }) {
  const items = records(visualization.data.items)
  if (items.length === 0) return null
  return (
    <section className="answer-news">
      <header className="answer-section-heading">
        <div><span>관련 뉴스</span><strong>{visualization.title}</strong></div>
        <em>{items.length}건</em>
      </header>
      <div className="news-list answer-news-list">
        {items.slice(0, 6).map((item, index) => {
          const source = sources.find((candidate) => candidate.sourceId === item.source_id)
          return (
            <RagNewsResultItem
              key={`${text(item.source_id)}-${index}`}
              publishedAt={typeof item.published_at === 'string' ? item.published_at : source?.publishedAt}
              publisher={typeof item.publisher === 'string' ? item.publisher : source?.publisher}
              sentiment={sentiment(item.sentiment)}
              snippet={typeof item.snippet === 'string' ? item.snippet : undefined}
              stockCode={typeof item.stock_code === 'string' ? item.stock_code : undefined}
              title={text(item.title, '제목 없는 뉴스')}
              url={newsClusterUrl(item, source) ?? safeHref(item.url) ?? source?.url}
            />
          )
        })}
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
  const chartPoints: RagPricePoint[] = points.map((point) => ({
    tradingDay: point.trading_day as string,
    close: point.close as number,
    open: typeof point.open === 'number' ? point.open : undefined,
    high: typeof point.high === 'number' ? point.high : undefined,
    low: typeof point.low === 'number' ? point.low : undefined,
    volume: typeof point.volume === 'number' ? point.volume : undefined,
  }))
  const quote = record(visualization.data.quote)
  const period = record(visualization.data.period)
  const last = points.at(-1)
  const returnPct = typeof period.return_pct === 'number' ? period.return_pct : undefined
  const lastIsCurrent = last?.price_kind === 'current' || period.end_price_kind === 'current'
  const sampled = visualization.data.sampled === true

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
      <RagPriceChart
        label={`${text(points[0]?.trading_day)}부터 ${text(last?.trading_day)}까지의 토스증권 주가 흐름`}
        points={chartPoints}
      />
      <footer>
        <span>{text(points[0]?.trading_day)}</span>
        <span>{sampled ? '전체 기간 대표 거래일 · ' : ''}토스증권 Open API · 최저 {won(min)} · 최고 {won(max)}</span>
        <span>{text(last?.trading_day)}{lastIsCurrent ? ' 현재가' : ''}</span>
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
  const horizons = records(data.horizons).filter((item) => (
    typeof item.horizon_days === 'number' && typeof item.return_pct === 'number'
  ))
  if (horizons.length === 0) return null
  const largest = Math.max(...horizons.map((item) => Math.abs(item.return_pct as number)), 1)
  return (
    <section className="answer-event-return">
      <header className="answer-section-heading">
        <div><span>사건 영향</span><strong>{visualization.title}</strong></div>
        <em>{text(data.event_date)}</em>
      </header>
      <div className="answer-event-return__baseline">
        <span>기준 거래일</span>
        <strong>{won(data.baseline_close, data.currency)}</strong>
        <time>{text(data.baseline_trading_day)}</time>
      </div>
      <div className="answer-event-return__horizons">
        {horizons.map((item) => {
          const value = item.return_pct as number
          return (
            <article key={text(item.horizon_days)}>
              <header><span>발표 후 {text(item.horizon_days)}거래일</span><strong className={value >= 0 ? 'is-up' : 'is-down'}>{value > 0 ? '+' : ''}{value}%</strong></header>
              <div><i className={value >= 0 ? 'is-up' : 'is-down'} style={{ width: `${Math.max(8, Math.abs(value) / largest * 100)}%` }} /></div>
              <footer><span>{text(item.trading_day)}</span><span>{won(item.close, data.currency)}</span></footer>
            </article>
          )
        })}
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
  cash_dividend_per_share: '주당 현금배당',
  dividend_yield: '배당수익률',
  total_dividend_amount: '배당금 총액',
}

const DISCLOSURE_EVENT_LABELS: Record<string, string> = {
  dividend_matter: '배당 결정',
  supply_contract: '공급 계약',
  single_sales_contract: '단일판매·공급계약',
  capital_increase: '유상증자 결정',
  capital_reduction: '감자 결정',
  treasury_stock: '자기주식 결정',
  merger: '합병 결정',
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
              <header><strong>{DISCLOSURE_EVENT_LABELS[text(item.event_type, '')] ?? text(item.event_type, '공시').replaceAll('_', ' ')}</strong><time>{text(item.announced_at, '')}</time></header>
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

export function RagVisualizations({ sources = [], visualizations }: { sources?: RagSource[]; visualizations: RagVisualization[] }) {
  return (
    <div className="answer-visuals">
      {visualizations.map((visualization, index) => {
        const key = `${visualization.type}-${visualization.sourceIds.join('-')}-${index}`
        if (visualization.type === 'news_cards') return <NewsResults key={key} sources={sources} visualization={visualization} />
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
