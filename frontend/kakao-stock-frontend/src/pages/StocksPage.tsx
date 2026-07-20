import { NEWS_CLUSTERS, STOCKS } from '../data/mockData'
import { AppLink, type Navigate } from '../components/AppLink'
import { Icon } from '../components/Icon'
import { SentimentBadge } from '../components/SentimentBadge'
import { StockAvatar } from '../components/StockAvatar'

interface StocksPageProps {
  onNavigate: Navigate
}

export function StocksPage({ onNavigate }: StocksPageProps) {
  return (
    <main className="subpage shell">
      <header className="page-title">
        <span className="eyebrow">분석 종목</span>
        <h1>다섯 기업을 깊게 봅니다</h1>
        <p>너무 많은 종목보다, 뉴스·공시·리포트가 충분히 쌓이는 5개 기업에 집중해요.</p>
      </header>

      <div className="stock-table-card">
        <div className="stock-table-card__head">
          <span>종목</span><span>전일 종가</span><span>최근 뉴스 신호</span><span>핵심 정보</span><span />
        </div>
        {STOCKS.map((stock) => {
          const latestNews = NEWS_CLUSTERS.find((cluster) => cluster.stockCode === stock.code)
          return (
            <AppLink className="stock-table-row" href={`/stocks/${stock.code}`} key={stock.code} onNavigate={onNavigate}>
              <div className="stock-table-row__identity">
                <StockAvatar imageSrc={stock.imageSrc} initials={stock.initials} />
                <div><strong>{stock.name}</strong><span>{stock.code} · {stock.sector}</span></div>
              </div>
              <div className="stock-table-row__quote"><strong>{stock.price}</strong><span className={`quote-change quote-change--${stock.direction}`}>{stock.changeRate}</span></div>
              <div>{latestNews && <SentimentBadge sentiment={latestNews.sentiment} />}</div>
              <p>{latestNews?.title ?? '새로운 주요 뉴스가 없어요.'}</p>
              <Icon name="chevron-right" size={18} />
            </AppLink>
          )
        })}
      </div>

      <aside className="data-note">
        <Icon name="info" size={18} />
        <div><strong>이 화면의 가격은 UI 구성용 샘플입니다.</strong><p>실제 서비스에서는 금융위원회 주식시세정보 API의 데이터 기준일과 전일 종가 기준 문구가 함께 표시됩니다.</p></div>
      </aside>
    </main>
  )
}
