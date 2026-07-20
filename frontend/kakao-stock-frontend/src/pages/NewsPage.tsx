import { useState } from 'react'
import { STOCKS } from '../data/mockData'
import type { AssistantContext } from '../types'
import { NewsClusterCard } from '../components/NewsClusterCard'
import { useNewsClusters } from '../hooks/useNewsClusters'

interface NewsPageProps {
  onAsk: (context: AssistantContext) => void
}

export function NewsPage({ onAsk }: NewsPageProps) {
  const [stockCode, setStockCode] = useState('all')
  const news = useNewsClusters({ limit: 50 })

  const filtered = news.clusters.filter(
    (cluster) => stockCode === 'all' || cluster.stockCode === stockCode,
  )

  return (
    <main className="subpage shell news-page">
      <header className="page-title page-title--row">
        <div>
          <span className="eyebrow">AI 뉴스 브리핑</span>
          <h1>같은 사건은 한 번만 읽으세요</h1>
          <p>여러 언론사의 기사를 사건별로 묶고, 확인된 사실과 원문을 함께 보여드려요.</p>
        </div>
        <div className="briefing-count"><strong>{news.clusters.length}</strong><span>사건 브리핑</span><small>Supabase 실제 데이터</small></div>
      </header>

      <div className="filter-toolbar">
        <div className="stock-filter" aria-label="종목 필터">
          <button className={stockCode === 'all' ? 'is-active' : ''} onClick={() => setStockCode('all')} type="button">전체 종목</button>
          {STOCKS.map((stock) => <button className={stockCode === stock.code ? 'is-active' : ''} key={stock.code} onClick={() => setStockCode(stock.code)} type="button">{stock.name}</button>)}
        </div>
      </div>

      <div className="news-feed">
        <div className="news-feed__header"><strong>{filtered.length}개의 사건</strong><span>최신순</span></div>
        {news.isLoading ? (
          <div className="empty-state"><strong>실제 뉴스 브리핑을 불러오는 중이에요.</strong></div>
        ) : news.error ? (
          <div className="empty-state"><strong>뉴스를 불러오지 못했어요.</strong><p>{news.error}</p><button className="text-button" onClick={news.retry} type="button">다시 시도</button></div>
        ) : filtered.length > 0 ? (
          filtered.map((cluster) => <NewsClusterCard cluster={cluster} key={cluster.id} onAsk={onAsk} showStock />)
        ) : (
          <div className="empty-state"><strong>조건에 맞는 브리핑이 없어요.</strong><p>뉴스 사건 정리가 생성되면 이곳에 표시됩니다.</p></div>
        )}
      </div>
    </main>
  )
}
