import { STOCKS } from '../data/mockData'
import type { AssistantContext } from '../types'
import { AppLink, type Navigate } from '../components/AppLink'
import { HomeBriefing } from '../components/HomeBriefing'
import { Icon } from '../components/Icon'
import { SectionHeader } from '../components/SectionHeader'
import { StockCard } from '../components/StockCard'
import { useStockMarketOverview } from '../hooks/useStockMarketOverview'
import { useNewsClusters } from '../hooks/useNewsClusters'
import { useStockIssueBriefs } from '../hooks/useStockIssueBriefs'

interface HomePageProps {
  onAsk: (context: AssistantContext) => void
  onNavigate: Navigate
}

export function HomePage({ onAsk, onNavigate }: HomePageProps) {
  const marketOverview = useStockMarketOverview()
  const news = useNewsClusters({ limit: 24 })
  const issueBriefs = useStockIssueBriefs()

  return (
    <main>
      <HomeBriefing
        clusters={news.clusters}
        error={news.error}
        issueBriefs={issueBriefs.briefs}
        issueBriefsLoading={issueBriefs.isLoading}
        isLoading={news.isLoading}
        onAsk={onAsk}
        onNavigate={onNavigate}
      />

      <section className="page-section shell">
        <SectionHeader
          action={<AppLink className="section-link" href="/stocks" onNavigate={onNavigate}>전체 보기 <Icon name="arrow-right" size={16} /></AppLink>}
          description="서비스가 집중해서 추적하는 국내 대표 기업이에요."
          eyebrow="분석 종목"
          title="5개 종목을 한눈에"
        />
        <div className="stock-card-grid">
          {STOCKS.map((stock) => <StockCard key={stock.code} onNavigate={onNavigate} quote={marketOverview.quotes[stock.code]} stock={stock} />)}
        </div>
      </section>

      <section className="how-it-works shell page-section">
        <SectionHeader
          description="숫자 계산과 분류는 전용 도구가 맡고, AI는 근거 안에서 쉽게 설명해요."
          eyebrow="신뢰할 수 있는 흐름"
          title="정보가 답변이 되기까지"
        />
        <div className="process-grid">
          <article><span>01</span><Icon name="news" size={23} /><h3>같은 사건 묶기</h3><p>여러 기사를 사건 단위로 모아 중복을 줄여요.</p></article>
          <article><span>02</span><Icon name="chart" size={23} /><h3>신호와 숫자 확인</h3><p>감성 분류기와 공식 데이터로 라벨과 수치를 확인해요.</p></article>
          <article><span>03</span><Icon name="document" size={23} /><h3>근거 안에서 설명</h3><p>찾아온 뉴스·공시·리포트를 벗어나지 않고 답해요.</p></article>
        </div>
      </section>
    </main>
  )
}
