import { useEffect, useState } from 'react'
import { STOCKS } from '../data/mockData'
import type { AssistantContext, NewsCluster } from '../types'
import { NewsClusterDetail, NewsClusterListItem } from '../components/NewsClusterListItem'
import { LoadingDots } from '../components/LoadingDots'
import { Icon } from '../components/Icon'
import { useNewsClusters } from '../hooks/useNewsClusters'
import { fetchNewsClusters } from '../api/news'

interface NewsPageProps {
  assistantOpen: boolean
  onAssistantClose: () => void
  onAsk: (context: AssistantContext) => void
}

export function NewsPage({ assistantOpen, onAssistantClose, onAsk }: NewsPageProps) {
  const [stockCode, setStockCode] = useState('all')
  const [publishedDate, setPublishedDate] = useState('')
  const [linkedCluster, setLinkedCluster] = useState<NewsCluster | null>(null)
  const news = useNewsClusters({
    limit: 20,
    publishedDate: publishedDate || undefined,
    stockCode: stockCode === 'all' ? undefined : stockCode,
  })
  useEffect(() => {
    const value = new URLSearchParams(window.location.search).get('cluster')
    const clusterId = value && /^\d+$/.test(value) ? Number(value) : null
    if (!clusterId) return
    const controller = new AbortController()
    fetchNewsClusters(controller.signal, { clusterId, limit: 1 })
      .then((response) => setLinkedCluster(response.clusters[0] ?? null))
      .catch(() => setLinkedCluster(null))
    return () => controller.abort()
  }, [])

  const closeLinkedCluster = () => {
    setLinkedCluster(null)
    const url = new URL(window.location.href)
    url.searchParams.delete('cluster')
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
    if (assistantOpen) onAssistantClose()
  }
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul' }).format(new Date())
  const selectedDateLabel = publishedDate
    ? new Intl.DateTimeFormat('ko-KR', {
      day: 'numeric',
      month: 'long',
      timeZone: 'Asia/Seoul',
      year: 'numeric',
    }).format(new Date(`${publishedDate}T12:00:00+09:00`))
    : '날짜 선택'
  const moveDate = (days: number) => {
    const base = publishedDate ? new Date(`${publishedDate}T12:00:00+09:00`) : new Date(`${today}T12:00:00+09:00`)
    base.setDate(base.getDate() + days)
    setPublishedDate(new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul' }).format(base))
  }

  return (
    <main className="subpage shell news-page">
      <header className="page-title page-title--row">
        <div>
          <span className="eyebrow">뉴스 브리핑</span>
          <h1>오늘 나온 뉴스를 사건별로 정리했어요</h1>
          <p>여러 언론사의 기사를 사건별로 묶고, 확인된 사실과 원문을 함께 보여드려요.</p>
        </div>
      </header>

      <div className="filter-toolbar">
        <div className="stock-filter" aria-label="종목 필터">
          <button className={stockCode === 'all' ? 'is-active' : ''} onClick={() => setStockCode('all')} type="button">전체 종목</button>
          {STOCKS.map((stock) => <button className={stockCode === stock.code ? 'is-active' : ''} key={stock.code} onClick={() => setStockCode(stock.code)} type="button">{stock.name}</button>)}
        </div>
        <div className="news-date-filter" aria-label="날짜 필터">
          <div className="news-date-filter__presets">
            <button className={!publishedDate ? 'is-active' : ''} onClick={() => setPublishedDate('')} type="button">전체 기간</button>
            <button className={publishedDate === today ? 'is-active' : ''} onClick={() => setPublishedDate(today)} type="button">오늘</button>
          </div>
          <div className="news-date-filter__picker">
            <button aria-label="이전 날짜" disabled={!publishedDate} onClick={() => moveDate(-1)} type="button">‹</button>
            <label>
              <Icon name="calendar" size={16} />
              <span>{selectedDateLabel}</span>
              <input
                aria-label="뉴스 날짜 선택"
                max={today}
                onChange={(event) => setPublishedDate(event.target.value)}
                type="date"
                value={publishedDate}
              />
            </label>
            <button aria-label="다음 날짜" disabled={!publishedDate || publishedDate >= today} onClick={() => moveDate(1)} type="button">›</button>
          </div>
        </div>
      </div>

      <div className="news-feed">
        <div className="news-feed__header">
          <strong>{publishedDate ? `${publishedDate.replaceAll('-', '. ')} 뉴스 ${news.total}개` : `뉴스 ${news.total}개`}</strong>
          <span>최신순</span>
        </div>
        {news.isLoading ? (
          <div className="empty-state empty-state--loading"><LoadingDots label="뉴스 불러오는 중" /></div>
        ) : news.error ? (
          <div className="empty-state"><strong>뉴스를 불러오지 못했어요.</strong><p>{news.error}</p><button className="text-button" onClick={news.retry} type="button">다시 시도</button></div>
        ) : news.clusters.length > 0 ? (
          <>
            <div className="news-list">
              {news.clusters.map((cluster) => <NewsClusterListItem assistantOpen={assistantOpen} cluster={cluster} key={cluster.id} onAssistantClose={onAssistantClose} onAsk={onAsk} />)}
            </div>
            {news.hasMore && (
              <button className="list-more-button" disabled={news.isLoadingMore} onClick={news.loadMore} type="button">
                {news.isLoadingMore ? <LoadingDots label="뉴스 더 불러오는 중" /> : `뉴스 20개 더보기 (${news.clusters.length}/${news.total})`}
              </button>
            )}
          </>
        ) : (
          <div className="empty-state"><strong>조건에 맞는 브리핑이 없어요.</strong><p>뉴스 사건 정리가 생성되면 이곳에 표시됩니다.</p></div>
        )}
      </div>
      {linkedCluster && (
        <NewsClusterDetail
          assistantOpen={assistantOpen}
          cluster={linkedCluster}
          onAsk={onAsk}
          onClose={closeLinkedCluster}
        />
      )}
    </main>
  )
}
