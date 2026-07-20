import { STOCKS } from '../data/mockData'
import { AppLink, type Navigate } from '../components/AppLink'
import { Icon } from '../components/Icon'
import { StockAvatar } from '../components/StockAvatar'
import { AnimatedPrice } from '../components/AnimatedPrice'
import { useStockMarketOverview } from '../hooks/useStockMarketOverview'
import { useNewsClusters } from '../hooks/useNewsClusters'

interface StocksPageProps {
  onNavigate: Navigate
}

export function StocksPage({ onNavigate }: StocksPageProps) {
  const marketOverview = useStockMarketOverview()
  const news = useNewsClusters({ limit: 50 })

  return (
    <main className="subpage shell">
      <header className="page-title">
        <span className="eyebrow">분석 종목</span>
        <h1>다섯 기업을 깊게 봅니다</h1>
        <p>너무 많은 종목보다, 뉴스·공시·리포트가 충분히 쌓이는 5개 기업에 집중해요.</p>
      </header>

      <div className="stock-table-card">
        <div className="stock-table-card__head">
          <span>종목</span><span>현재가</span><span>분류 예정</span><span>최근 뉴스</span><span />
        </div>
        {STOCKS.map((stock) => {
          const latestNews = news.clusters.find((cluster) => cluster.stockCode === stock.code)
          const quote = marketOverview.quotes[stock.code]
          const direction = quote ? (quote.change === 0 ? 'flat' : quote.change > 0 ? 'up' : 'down') : stock.direction
          const changeRate = quote
            ? `${quote.changeRate > 0 ? '+' : ''}${quote.changeRate.toFixed(2)}%`
            : stock.changeRate
          return (
            <AppLink className="stock-table-row" href={`/stocks/${stock.code}`} key={stock.code} onNavigate={onNavigate}>
              <div className="stock-table-row__identity">
                <StockAvatar imageSrc={stock.imageSrc} initials={stock.initials} />
                <div><strong>{stock.name}</strong><span>{stock.code} · {stock.sector}</span></div>
              </div>
              <div className="stock-table-row__quote">
                <AnimatedPrice fallback={stock.price} value={quote?.price ?? null} />
                <span className={`quote-change quote-change--${direction}`}>{changeRate}</span>
              </div>
              <div aria-label="호재 악재 분류 모델 연결 예정" />
              <p>{latestNews?.title ?? '새로운 주요 뉴스가 없어요.'}</p>
              <Icon name="chevron-right" size={18} />
            </AppLink>
          )
        })}
      </div>

      <aside className="data-note">
        <Icon name="info" size={18} />
        <div>
          <strong><i className={`live-dot${marketOverview.isRefreshing ? ' live-dot--refreshing' : ''}`} /> 토스증권 실제 시세 · 15초 자동 갱신</strong>
          <p>{marketOverview.error || '현재가와 전일 대비 등락률이 자동으로 업데이트됩니다.'}</p>
        </div>
      </aside>
    </main>
  )
}
