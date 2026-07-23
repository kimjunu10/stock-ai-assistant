import { useState } from 'react'
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

export function StockHeader({ isRefreshing, issueBrief, marketData, marketDataStatus, newsClusters, onAsk, stock }: StockHeaderProps) {
  const [openCluster, setOpenCluster] = useState<NewsCluster | null>(null)
  const quote = marketData?.quote
  const direction = !quote || quote.change === 0 ? 'flat' : quote.change > 0 ? 'up' : 'down'
  const changeText = quote
    ? `어제보다 ${formatSignedWon(quote.change)} (${quote.changeRate > 0 ? '+' : ''}${quote.changeRate.toFixed(2)}%)`
    : marketDataStatus === 'loading' ? '실제 시세를 확인하고 있어요' : '시세를 불러오지 못했어요'
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
        <h2 className="stock-hero__issues-heading">오늘의 핵심</h2>
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
                <h3><i />{sentiment === 'positive' ? '좋아진 점' : '주의할 점'}</h3>
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
                ) : <p>{issueBrief ? '뚜렷한 변화가 없어요.' : '정리하고 있어요.'}</p>}
              </section>
            )
          })}
        </div>
      </div>
      {openCluster && <NewsClusterDetail cluster={openCluster} onAsk={onAsk} onClose={() => setOpenCluster(null)} />}
    </section>
  )
}
