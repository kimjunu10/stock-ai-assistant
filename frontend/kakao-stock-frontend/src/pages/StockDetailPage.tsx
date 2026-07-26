import { useEffect, useMemo, useState } from 'react'
import { getStock } from '../data/mockData'
import type { AssistantContext, Theme } from '../types'
import { ReportList } from '../components/ResearchLists'
import { FinancialCard } from '../components/FinancialCard'
import { Icon } from '../components/Icon'
import { NewsClusterListItem } from '../components/NewsClusterListItem'
import { LoadingDots } from '../components/LoadingDots'
import { SectionHeader } from '../components/SectionHeader'
import { StockHeader } from '../components/StockHeader'
import { PriceChart } from '../components/PriceChart'
import { CompanySnapshot } from '../components/CompanySnapshot'
import { useStockMarketData } from '../hooks/useStockMarketData'
import { useStockFundamentals } from '../hooks/useStockFundamentals'
import { useNewsClusters } from '../hooks/useNewsClusters'
import { useResearchReports } from '../hooks/useResearchReports'
import { kstDateKey } from '../utils/chartNews'

interface StockDetailPageProps {
  assistantOpen: boolean
  onAssistantClose: () => void
  onAsk: (context: AssistantContext) => void
  stockCode: string
  theme: Theme
}

export function StockDetailPage({ assistantOpen, onAssistantClose, onAsk, stockCode, theme }: StockDetailPageProps) {
  const stock = getStock(stockCode)
  const marketData = useStockMarketData(stockCode)
  const fundamentals = useStockFundamentals(stockCode)
  const news = useNewsClusters({ limit: 50, stockCode })
  const reports = useResearchReports(stockCode)
  const chartPublishedDate = useMemo(
    () => kstDateKey(marketData.data?.intradayCandles.at(-1)?.time ?? ''),
    [marketData.data?.intradayCandles],
  )
  const {
    clusters: chartNewsClusters,
    error: chartNewsError,
    hasMore: chartNewsHasMore,
    isLoading: isChartNewsLoading,
    isLoadingMore: isChartNewsLoadingMore,
    loadMore: loadMoreChartNews,
  } = useNewsClusters({
    enabled: Boolean(chartPublishedDate),
    limit: 50,
    publishedDate: chartPublishedDate || undefined,
    stockCode,
  })
  const [visibleNewsCount, setVisibleNewsCount] = useState(3)

  useEffect(() => setVisibleNewsCount(3), [stockCode])
  useEffect(() => {
    if (
      chartPublishedDate
      && chartNewsHasMore
      && !chartNewsError
      && !isChartNewsLoading
      && !isChartNewsLoadingMore
    ) {
      loadMoreChartNews()
    }
  }, [
    chartNewsError,
    chartNewsHasMore,
    chartPublishedDate,
    isChartNewsLoading,
    isChartNewsLoadingMore,
    loadMoreChartNews,
  ])

  if (!stock) {
    return <div className="not-found shell"><span>404</span><h1>분석 대상이 아닌 종목이에요.</h1><p>현재는 지정된 5개 종목만 제공하고 있어요.</p></div>
  }

  if (marketData.status === 'loading' || news.isLoading) {
    return (
      <main className="stock-page-loading shell">
        <div className="stock-page-loading__mark">
          <span />
          <span />
        </div>
        <strong>{stock.name} 핵심 정보를 준비하고 있어요</strong>
        <p>실시간 주가와 오늘의 뉴스 흐름을 함께 불러오는 중입니다.</p>
        <LoadingDots label={`${stock.name} 종목 상세 불러오는 중`} />
      </main>
    )
  }

  return (
    <main className="stock-page shell">
      <StockHeader
        isRefreshing={marketData.isRefreshing}
        marketData={marketData.data}
        marketDataStatus={marketData.status}
        newsClusters={news.clusters}
        onAsk={onAsk}
        stock={stock}
        issueBrief={news.issueBrief}
      />
      <button
        className="stock-rag-launcher"
        onClick={() => onAsk({
          stockCode: stock.code,
          sourceType: 'stock',
          sourceId: stock.code,
          title: `${stock.name} 전체 자료`,
        })}
        type="button"
      >
        <strong>AI에게 질문하기</strong>
        <small>뉴스·공시·리포트·주가를 함께 확인해요</small>
        <Icon name="arrow-right" size={17} />
      </button>

      <section className="stock-section chart-section">
        <PriceChart
          clusters={chartNewsClusters}
          data={marketData.data}
          error={marketData.error}
          newsError={chartNewsError}
          newsStatus={isChartNewsLoading ? 'loading' : 'ready'}
          onAsk={onAsk}
          onRetry={marketData.retry}
          status={marketData.status}
          stockName={stock.name}
          theme={theme}
        />
      </section>

      <section className="stock-section stock-news-section">
        <SectionHeader
          action={<span className="section-meta">{news.total > 0 ? `전체 ${news.total}개 사건` : '뉴스 사건'}</span>}
          description="여러 기사를 하나의 사건으로 묶어, 지금 알아야 할 소식부터 보여드려요."
          eyebrow="중요한 소식"
          title={`${stock.name}에 지금 중요한 소식`}
        />
        <div className="stock-news-list">
          {news.isLoading && <div className="stock-news-loading"><LoadingDots label={`${stock.name} 뉴스 불러오는 중`} /></div>}
          {news.clusters.slice(0, visibleNewsCount).map((cluster) => <NewsClusterListItem assistantOpen={assistantOpen} cluster={cluster} key={cluster.id} onAssistantClose={onAssistantClose} onAsk={onAsk} />)}
          {!news.isLoading && news.clusters.length === 0 && (
            <p className="data-notice">{news.error || '아직 생성된 뉴스 사건 정리가 없어요.'}</p>
          )}
        </div>
        {(visibleNewsCount < news.clusters.length || news.hasMore) && (
          <button
            className="stock-news-more"
            disabled={news.isLoadingMore}
            onClick={() => {
              if (visibleNewsCount + 5 > news.clusters.length && news.hasMore) news.loadMore()
              setVisibleNewsCount((count) => count + 5)
            }}
            type="button"
          >
            {news.isLoadingMore ? '소식 불러오는 중' : '중요한 소식 더보기'}
            <Icon name="arrow-right" size={16} />
          </button>
        )}
      </section>

      <section className="stock-section">
        <SectionHeader
          action={<span className="source-label"><Icon name="check" size={14} /> DART 공식 수치</span>}
          description="DB에 수집된 최근 DART 보고기간의 핵심 항목과 전년 같은 기간 대비 변화를 봅니다."
          eyebrow="핵심 재무"
          title="숫자로 보는 회사"
        />
        <CompanySnapshot
          marketData={marketData.data}
          profile={fundamentals.companyProfile}
          stock={stock}
        />
        <div className="financial-grid">
          {fundamentals.financials.map((item) => <FinancialCard item={item} key={item.account} />)}
        </div>
        {fundamentals.companyProfileError && <p className="data-notice">{fundamentals.companyProfileError}</p>}
        {fundamentals.financialError && <p className="data-notice">{fundamentals.financialError}</p>}
      </section>

      <section className="stock-section research-section">
        <div className="research-column research-column--wide">
          <SectionHeader
            action={<span className="section-meta">{reports.total > 0 ? `전체 ${reports.total}개` : 'PDF 리포트'}</span>}
            description="Supabase에 보관된 최신 증권사 원문을 종목별·발행일순으로 확인하고 내려받을 수 있어요."
            eyebrow="리서치"
            title={`${stock.name} 증권사 리포트`}
          />
          {reports.isLoading && <div className="stock-news-loading"><LoadingDots label={`${stock.name} 리포트 불러오는 중`} /></div>}
          {!reports.isLoading && reports.items.length > 0 && <ReportList items={reports.items} onAsk={onAsk} />}
          {!reports.isLoading && reports.items.length === 0 && (
            <p className="data-notice">{reports.error || '저장된 증권사 리포트가 아직 없어요.'}</p>
          )}
          {reports.hasMore && (
            <button
              className="list-more-button"
              disabled={reports.isLoadingMore}
              onClick={reports.loadMore}
              type="button"
            >
              {reports.isLoadingMore ? '리포트 불러오는 중' : '리포트 더보기'}
              <Icon name="arrow-right" size={16} />
            </button>
          )}
        </div>
      </section>
    </main>
  )
}
