import { NEWS_CLUSTERS, STOCKS } from '../data/mockData'
import type { AssistantContext } from '../types'
import { AppLink, type Navigate } from '../components/AppLink'
import { Icon } from '../components/Icon'
import { NewsClusterCard } from '../components/NewsClusterCard'
import { SectionHeader } from '../components/SectionHeader'
import { StockCard } from '../components/StockCard'
import { useStockMarketOverview } from '../hooks/useStockMarketOverview'

interface HomePageProps {
  onAsk: (context: AssistantContext) => void
  onNavigate: Navigate
}

export function HomePage({ onAsk, onNavigate }: HomePageProps) {
  const marketOverview = useStockMarketOverview()
  const featuredNews = [NEWS_CLUSTERS[0], NEWS_CLUSTERS[5], NEWS_CLUSTERS[9]].filter(
    (cluster) => cluster !== undefined,
  )

  return (
    <main>
      <section className="home-hero shell">
        <div className="home-hero__copy">
          <span className="hero-pill"><Icon name="news" size={15} /> 초보 투자자를 위한 뉴스 브리핑</span>
          <h1>흩어진 투자 정보,<br />한 번에 이해하세요.</h1>
          <p>뉴스는 같은 사건끼리 모아 쉽게 설명하고, 공시와 리포트는 궁금한 순간 바로 물어볼 수 있어요.</p>
          <div className="home-hero__actions">
            <AppLink className="primary-button primary-button--large" href="/stocks/005930" onNavigate={onNavigate}>
              종목 둘러보기 <Icon name="arrow-right" size={18} />
            </AppLink>
            <AppLink className="secondary-button secondary-button--large" href="/ask" onNavigate={onNavigate}>
              <Icon name="message" size={18} /> AI에게 질문
            </AppLink>
          </div>
          <div className="home-hero__trust">
            <span><Icon name="check" size={15} /> 출처가 있는 답변</span>
            <span><Icon name="check" size={15} /> 투자 추천 없음</span>
            <span><Icon name="check" size={15} /> 5개 종목 집중 분석</span>
          </div>
        </div>
        <div className="briefing-preview" aria-label="AI 뉴스 브리핑 예시">
          <div className="briefing-preview__header">
            <div>
              <span className="assistant-symbol" aria-hidden="true">M</span>
              <div><strong>오늘의 AI 브리핑</strong><span>새 소식 14건을 5개 사건으로 정리했어요</span></div>
            </div>
            <span>오전 9:30</span>
          </div>
          <div className="briefing-preview__signal">
            <span className="briefing-preview__score">3</span>
            <div><strong>긍정 신호가 조금 더 많아요</strong><p>호재 3 · 중립 1 · 악재 1</p></div>
          </div>
          <div className="briefing-preview__items">
            <article><span className="signal-dot signal-dot--positive" /><div><strong>AI 메모리 공급 확대 기대</strong><p>삼성전자 · 기사 12개 묶음</p></div><Icon name="chevron-right" size={17} /></article>
            <article><span className="signal-dot signal-dot--neutral" /><div><strong>원가 협상 결과는 더 지켜봐야 해요</strong><p>한화오션 · 기사 8개 묶음</p></div><Icon name="chevron-right" size={17} /></article>
          </div>
          <div className="briefing-preview__ask"><Icon name="message" size={17} /><span>“이 소식이 실적에는 어떤 영향이야?”</span><button aria-label="예시 질문 보내기" type="button"><Icon name="send" size={15} /></button></div>
        </div>
      </section>

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

      <section className="page-section page-section--tinted">
        <div className="shell">
          <SectionHeader
            action={<AppLink className="section-link" href="/news" onNavigate={onNavigate}>브리핑 더 보기 <Icon name="arrow-right" size={16} /></AppLink>}
            description="여러 언론사가 전한 같은 사건을 하나로 묶어 핵심만 보여드려요."
            eyebrow="오늘의 주요 사건"
            title="클릭하기 전에 이해하는 뉴스"
          />
          <div className="featured-news-grid">
            {featuredNews.map((cluster) => (
              <NewsClusterCard cluster={cluster} key={cluster.id} onAsk={onAsk} showStock />
            ))}
          </div>
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
