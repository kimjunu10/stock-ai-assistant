import { DISCLOSURES, FINANCIALS, REPORTS, getStock, getStockNews } from '../data/mockData'
import type { AssistantContext, Theme } from '../types'
import { DisclosureList, ReportList } from '../components/ResearchLists'
import { FinancialCard } from '../components/FinancialCard'
import { Icon } from '../components/Icon'
import { NewsClusterCard } from '../components/NewsClusterCard'
import { SectionHeader } from '../components/SectionHeader'
import { StockHeader } from '../components/StockHeader'
import { TradingViewChart } from '../components/TradingViewChart'

interface StockDetailPageProps {
  onAsk: (context: AssistantContext) => void
  stockCode: string
  theme: Theme
}

export function StockDetailPage({ onAsk, stockCode, theme }: StockDetailPageProps) {
  const stock = getStock(stockCode)

  if (!stock) {
    return <div className="not-found shell"><span>404</span><h1>분석 대상이 아닌 종목이에요.</h1><p>현재는 지정된 5개 종목만 제공하고 있어요.</p></div>
  }

  const news = getStockNews(stockCode)
  const financials = FINANCIALS[stockCode] ?? []
  const disclosures = DISCLOSURES.filter((item) => item.stockCode === stockCode)
  const reports = REPORTS.filter((item) => item.stockCode === stockCode)

  return (
    <main className="stock-page shell">
      <StockHeader onAsk={onAsk} stock={stock} />

      <section className="stock-section chart-section">
        <TradingViewChart
          stockCode={stock.code}
          stockName={stock.name}
          theme={theme}
        />
      </section>

      <section className="stock-section stock-news-section">
        <SectionHeader
          action={<span className="section-meta">뉴스 마커는 추후 별도 가격 API 연동 후 제공</span>}
          description="차트와 섞지 않고, 같은 종목의 주요 사건을 아래에서 확인하세요."
          eyebrow="차트 아래 주요 뉴스"
          title={`${stock.name}에 지금 중요한 소식`}
        />
        <div className="stock-news-list">
          {news.map((cluster) => <NewsClusterCard cluster={cluster} compact key={cluster.id} onAsk={onAsk} />)}
        </div>
      </section>

      <section className="stock-section">
        <SectionHeader
          action={<span className="source-label"><Icon name="check" size={14} /> DART 공식 수치</span>}
          description="최근 분기의 핵심 항목과 전년 같은 기간 대비 변화를 봅니다."
          eyebrow="핵심 재무"
          title="숫자로 보는 회사"
        />
        <div className="financial-grid">
          {financials.map((item) => <FinancialCard item={item} key={item.account} />)}
        </div>
      </section>

      <section className="stock-section research-section">
        <div className="research-column">
          <SectionHeader description="회사가 직접 제출한 공식 문서예요." eyebrow="DART" title="최근 공시" />
          <DisclosureList items={disclosures} onAsk={onAsk} />
          <button className="list-more-button" type="button">공시 전체 보기 <Icon name="arrow-right" size={16} /></button>
        </div>
        <div className="research-column">
          <SectionHeader description="증권사 분석의 핵심 논리를 모았어요." eyebrow="리서치" title="애널리스트 리포트" />
          <ReportList items={reports} onAsk={onAsk} />
          <button className="list-more-button" type="button">리포트 전체 보기 <Icon name="arrow-right" size={16} /></button>
        </div>
      </section>
    </main>
  )
}
