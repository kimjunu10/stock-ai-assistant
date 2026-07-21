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
  const news = useNewsClusters({ limit: 10, stockCode })

  if (!stock) {
    return <div className="not-found shell"><span>404</span><h1>분석 대상이 아닌 종목이에요.</h1><p>현재는 지정된 5개 종목만 제공하고 있어요.</p></div>
  }

  return (
    <main className="stock-page shell">
      <StockHeader
        isRefreshing={marketData.isRefreshing}
        marketData={marketData.data}
        marketDataStatus={marketData.status}
        onAsk={onAsk}
        stock={stock}
      />

      <section className="stock-section chart-section">
        <PriceChart
          data={marketData.data}
          error={marketData.error}
          onRetry={marketData.retry}
          status={marketData.status}
          stockName={stock.name}
          theme={theme}
        />
      </section>

      <section className="stock-section stock-news-section">
        <SectionHeader
          action={<span className="section-meta">뉴스 마커는 후속 기능으로 제공</span>}
          description="차트와 섞지 않고, 같은 종목의 주요 사건을 아래에서 확인하세요."
          eyebrow="차트 아래 주요 뉴스"
          title={`${stock.name}에 지금 중요한 소식`}
        />
        <div className="stock-news-list">
          {news.isLoading && <div className="stock-news-loading"><LoadingDots label={`${stock.name} 뉴스 불러오는 중`} /></div>}
          {news.clusters.map((cluster) => <NewsClusterListItem assistantOpen={assistantOpen} cluster={cluster} key={cluster.id} onAssistantClose={onAssistantClose} onAsk={onAsk} />)}
          {!news.isLoading && news.clusters.length === 0 && (
            <p className="data-notice">{news.error || '아직 생성된 뉴스 사건 정리가 없어요.'}</p>
          )}
        </div>
      </section>

      <section className="stock-section">
        <SectionHeader
          action={<span className="source-label"><Icon name="check" size={14} /> DART 공식 수치</span>}
          description="DB에 수집된 최근 DART 보고기간의 핵심 항목과 전년 같은 기간 대비 변화를 봅니다."
          eyebrow="핵심 재무"
          title="숫자로 보는 회사"
        />
        <div className="financial-grid">
          {fundamentals.financials.map((item) => <FinancialCard item={item} key={item.account} />)}
        </div>
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
