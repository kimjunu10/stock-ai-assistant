import { useEffect, useState } from 'react'
import { getStock } from '../data/mockData'
import type { AssistantContext, Theme } from '../types'
import { DisclosureList, ReportList } from '../components/ResearchLists'
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
  const [visibleNewsCount, setVisibleNewsCount] = useState(3)

  useEffect(() => setVisibleNewsCount(3), [stockCode])

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

      <section className="stock-section chart-section">
        <PriceChart
          clusters={news.clusters}
          data={marketData.data}
          error={marketData.error}
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
        <div className="research-column">
          <SectionHeader description="회사가 직접 제출한 공식 문서예요." eyebrow="DART" title="최근 공시" />
          <DisclosureList items={fundamentals.disclosures} onAsk={onAsk} />
          {fundamentals.disclosureError && <p className="data-notice">{fundamentals.disclosureError}</p>}
          <button className="list-more-button" type="button">공시 전체 보기 <Icon name="arrow-right" size={16} /></button>
        </div>
        <div className="research-column">
          <SectionHeader description="증권사 분석의 핵심 논리를 모았어요." eyebrow="리서치" title="애널리스트 리포트" />
          <ReportList items={[]} onAsk={onAsk} />
          <p className="data-notice">로컬 리포트 244건은 적재 전이라 아직 표시하지 않아요.</p>
        </div>
      </section>
    </main>
  )
}
