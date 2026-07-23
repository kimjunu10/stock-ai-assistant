import { useMemo, useState } from 'react'
import type { AssistantContext, MarketDataStatus, NewsCluster, Stock, StockIssueBrief, StockMarketData } from '../types'
import { AnimatedPrice } from './AnimatedPrice'
import { NewsClusterDetail } from './NewsClusterListItem'
import { StockAvatar } from './StockAvatar'

interface StockHeaderProps {
  isRefreshing: boolean
  marketData: StockMarketData | null
  marketDataStatus: MarketDataStatus
  newsClusters: NewsCluster[]
  onAsk: (context: AssistantContext) => void
  stock: Stock
  issueBrief: StockIssueBrief | null
}

const numberFormatter = new Intl.NumberFormat('ko-KR')

function formatSignedWon(value: number) {
  const sign = value > 0 ? '+' : ''
  return `${sign}${numberFormatter.format(value)}원`
}

function formatAsOf(value: string) {
  return new Intl.DateTimeFormat('ko-KR', {
    day: 'numeric',
    hour: '2-digit',
    hour12: false,
    minute: '2-digit',
    month: 'long',
    timeZone: 'Asia/Seoul',
  }).format(new Date(value))
}

function isTodayInSeoul(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return false
  const formatter = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul' })
  return formatter.format(date) === formatter.format(new Date())
}

export function StockHeader({ isRefreshing, issueBrief, marketData, marketDataStatus, newsClusters, onAsk, stock }: StockHeaderProps) {
  const [openCluster, setOpenCluster] = useState<NewsCluster | null>(null)
  const quote = marketData?.quote
  const direction = !quote || quote.change === 0 ? 'flat' : quote.change > 0 ? 'up' : 'down'
  const changeText = quote
    ? `어제보다 ${formatSignedWon(quote.change)} (${quote.changeRate > 0 ? '+' : ''}${quote.changeRate.toFixed(2)}%)`
    : marketDataStatus === 'loading' ? '실제 시세를 확인하고 있어요' : '시세를 불러오지 못했어요'
  const issues = useMemo(() => {
    const today = newsClusters.filter((cluster) => isTodayInSeoul(cluster.publishedAt))
    const pick = (sentiment: 'positive' | 'negative') => today.filter(
      (cluster) => cluster.sentiment === sentiment,
    )
    return { negative: pick('negative'), positive: pick('positive') }
  }, [newsClusters])

  return (
    <section className="stock-hero">
      <div className="stock-hero__overview">
        <div className="stock-hero__identity">
          <StockAvatar imageSrc={stock.imageSrc} initials={stock.initials} size="lg" />
          <div>
            <div className="stock-hero__labels">
              <span>{stock.market}</span>
              <span>{stock.sector}</span>
            </div>
            <div className="stock-hero__title">
              <h1>{stock.name}</h1>
              <span>{stock.code}</span>
            </div>
            <p>{stock.summary}</p>
          </div>
        </div>
        <div className="stock-hero__quote">
          <span className="sample-label">
            <i className={`live-dot${isRefreshing ? ' live-dot--refreshing' : ''}`} />
            {quote ? `LIVE · ${formatAsOf(quote.asOf)} 기준 · 15초 자동 갱신` : '토스증권 실제 시세'}
          </span>
          <div className="stock-hero__price-line">
            <AnimatedPrice value={quote?.price ?? null} />
            <span className={`quote-change quote-change--${direction}`}>
              {changeText}
            </span>
          </div>
        </div>
      </div>
      <div className="stock-hero__issues">
        <div className="stock-hero__issues-heading">
          <div><span>오늘의 핵심 이슈</span><strong>AI가 오늘 뉴스를 묶어 핵심만 정리했어요</strong></div>
          <time>30분마다 갱신</time>
        </div>
        <div className="stock-hero__issue-stack">
          {(['positive', 'negative'] as const).map((sentiment) => {
            const generated = issueBrief
              ? (sentiment === 'positive' ? issueBrief.positiveItems : issueBrief.negativeItems)
              : []
            const entries = generated.map((item) => ({
              cluster: item.clusterIds
                .map((clusterId) => newsClusters.find((cluster) => cluster.id === clusterId))
                .find(Boolean),
              key: `${sentiment}:${item.clusterIds.join('-')}:${item.text}`,
              text: item.text,
            }))
            return (
              <section className={`stock-hero__issue-group is-${sentiment}`} key={sentiment}>
                <div className="stock-hero__issue-title">
                  <h2><i />{sentiment === 'positive' ? '긍정 요인' : '부정 요인'}</h2>
                  <span>관련 뉴스 {issues[sentiment].length}건</span>
                </div>
                {entries.length > 0 ? (
                  <ul>
                    {entries.map((entry) => (
                      <li key={entry.key}>
                        <button
                          aria-disabled={!entry.cluster}
                          onClick={() => entry.cluster && setOpenCluster(entry.cluster)}
                          type="button"
                        >
                          <span aria-hidden="true" />
                          <strong>{entry.text}</strong>
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : <p>{issueBrief ? '뚜렷한 이슈가 없어요.' : '핵심 이슈를 정리하고 있어요.'}</p>}
              </section>
            )
          })}
        </div>
      </div>
      {openCluster && <NewsClusterDetail cluster={openCluster} onAsk={onAsk} onClose={() => setOpenCluster(null)} />}
    </section>
  )
}
