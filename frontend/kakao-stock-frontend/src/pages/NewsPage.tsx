import { useState } from 'react'
import { NEWS_CLUSTERS, STOCKS } from '../data/mockData'
import type { AssistantContext, Sentiment } from '../types'
import { NewsClusterCard } from '../components/NewsClusterCard'

interface NewsPageProps {
  onAsk: (context: AssistantContext) => void
}

type SentimentFilter = 'all' | Sentiment

const SENTIMENT_FILTERS: { label: string; value: SentimentFilter }[] = [
  { label: '전체', value: 'all' },
  { label: '호재', value: 'positive' },
  { label: '악재', value: 'negative' },
  { label: '중립', value: 'neutral' },
]

export function NewsPage({ onAsk }: NewsPageProps) {
  const [stockCode, setStockCode] = useState('all')
  const [sentiment, setSentiment] = useState<SentimentFilter>('all')

  const filtered = NEWS_CLUSTERS.filter(
    (cluster) =>
      (stockCode === 'all' || cluster.stockCode === stockCode) &&
      (sentiment === 'all' || cluster.sentiment === sentiment),
  )

  return (
    <main className="subpage shell news-page">
      <header className="page-title page-title--row">
        <div>
          <span className="eyebrow">AI 뉴스 브리핑</span>
          <h1>같은 사건은 한 번만 읽으세요</h1>
          <p>기사를 사건별로 묶고, 주가에 미칠 신호와 그 이유를 쉬운 말로 정리했어요.</p>
        </div>
        <div className="briefing-count"><strong>{NEWS_CLUSTERS.length}</strong><span>사건 브리핑</span><small>화면 구성용 데이터</small></div>
      </header>

      <div className="filter-toolbar">
        <div className="segmented-control" aria-label="감성 필터">
          {SENTIMENT_FILTERS.map((filter) => (
            <button className={sentiment === filter.value ? 'is-active' : ''} key={filter.value} onClick={() => setSentiment(filter.value)} type="button">{filter.label}</button>
          ))}
        </div>
        <div className="stock-filter" aria-label="종목 필터">
          <button className={stockCode === 'all' ? 'is-active' : ''} onClick={() => setStockCode('all')} type="button">전체 종목</button>
          {STOCKS.map((stock) => <button className={stockCode === stock.code ? 'is-active' : ''} key={stock.code} onClick={() => setStockCode(stock.code)} type="button">{stock.name}</button>)}
        </div>
      </div>

      <div className="news-feed">
        <div className="news-feed__header"><strong>{filtered.length}개의 사건</strong><span>최신순</span></div>
        {filtered.length > 0 ? (
          filtered.map((cluster) => <NewsClusterCard cluster={cluster} key={cluster.id} onAsk={onAsk} showStock />)
        ) : (
          <div className="empty-state"><strong>조건에 맞는 브리핑이 없어요.</strong><p>다른 종목이나 신호를 선택해 보세요.</p></div>
        )}
      </div>
    </main>
  )
}
