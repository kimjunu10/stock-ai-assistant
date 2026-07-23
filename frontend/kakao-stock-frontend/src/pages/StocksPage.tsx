import { STOCKS } from '../data/mockData'
import { AppLink, type Navigate } from '../components/AppLink'
import { Icon } from '../components/Icon'
import { StockAvatar } from '../components/StockAvatar'
import { AnimatedPrice } from '../components/AnimatedPrice'
import { SentimentBadge } from '../components/SentimentBadge'
import { useStockMarketOverview } from '../hooks/useStockMarketOverview'
import { useNewsClusters } from '../hooks/useNewsClusters'

interface StocksPageProps {
  onNavigate: Navigate
}

function formatRelativeTime(value: string) {
  const timestamp = new Date(value).getTime()
  if (Number.isNaN(timestamp)) return ''
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60_000))
  if (minutes < 1) return '방금 전'
  if (minutes < 60) return `${minutes}분 전`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}시간 전`
  const date = new Date(timestamp)
  return `${date.getMonth() + 1}월 ${date.getDate()}일`
}

export function StocksPage({ onNavigate }: StocksPageProps) {
  const marketOverview = useStockMarketOverview()
  const news = useNewsClusters({ limit: 50 })

  return (
    <main className="subpage shell">
      <header className="stocks-page__header">
        <div>
          <h1>종목 둘러보기</h1>
          <p>현재 주가와 최근 핵심 뉴스를 한눈에 확인하세요.</p>
        </div>
        <span className="stocks-page__live">
          <i className={`live-dot${marketOverview.isRefreshing ? ' live-dot--refreshing' : ''}`} />
          실시간 시세 · 15초 갱신
        </span>
      </header>

      <div className="stock-overview-grid">
        {STOCKS.map((stock) => {
          const latestNews = news.clusters.find((cluster) => cluster.stockCode === stock.code)
          const quote = marketOverview.quotes[stock.code]
          const direction = quote ? (quote.change === 0 ? 'flat' : quote.change > 0 ? 'up' : 'down') : stock.direction
          const changeRate = quote
            ? `${quote.changeRate > 0 ? '+' : ''}${quote.changeRate.toFixed(2)}%`
            : stock.changeRate
          return (
            <AppLink className="stock-overview-card" href={`/stocks/${stock.code}`} key={stock.code} onNavigate={onNavigate}>
              <div className="stock-overview-card__top">
                <div className="stock-overview-card__identity">
                  <StockAvatar imageSrc={stock.imageSrc} initials={stock.initials} size="lg" />
                  <div>
                    <strong>{stock.name}</strong>
                    <span>{stock.code} · {stock.sector}</span>
                  </div>
                </div>
                <div className="stock-overview-card__quote">
                  <AnimatedPrice fallback={stock.price} value={quote?.price ?? null} />
                  <span className={`quote-change quote-change--${direction}`}>{changeRate}</span>
                </div>
              </div>
              <div className="stock-overview-card__news">
                <div className="stock-overview-card__news-meta">
                  <span>최근 핵심 뉴스</span>
                  <span>
                    {latestNews?.sentiment && (
                      <SentimentBadge
                        sentiment={latestNews.sentiment}
                        variant="compact"
                      />
                    )}
                    {latestNews && <time>{formatRelativeTime(latestNews.publishedAt)}</time>}
                  </span>
                </div>
                <strong>{latestNews?.title ?? '새로운 주요 뉴스가 없어요.'}</strong>
              </div>
              <div className="stock-overview-card__footer">
                <span>종목 상세 보기</span>
                <Icon name="arrow-right" size={17} />
              </div>
            </AppLink>
          )
        })}
      </div>
      {marketOverview.error && <p className="stocks-page__error">{marketOverview.error}</p>}
    </main>
  )
}
