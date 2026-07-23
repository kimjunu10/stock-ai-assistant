import { useMemo, useState, type SyntheticEvent } from 'react'
import { getStock, STOCKS } from '../data/mockData'
import type { AssistantContext, NewsCluster, StockIssueBrief } from '../types'
import { AppLink, type Navigate } from './AppLink'
import { Icon } from './Icon'
import { LoadingDots } from './LoadingDots'
import { NewsClusterDetail } from './NewsClusterListItem'
import { SentimentBadge } from './SentimentBadge'
import { StockAvatar } from './StockAvatar'

interface Props {
  clusters: NewsCluster[]
  error: string
  issueBriefs: Record<string, StockIssueBrief | null>
  issueBriefsLoading: boolean
  isLoading: boolean
  onAsk: (context: AssistantContext) => void
  onNavigate: Navigate
}

const SEOUL_DATE = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Seoul',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

function timestamp(value: string) {
  const parsed = new Date(value).getTime()
  return Number.isNaN(parsed) ? 0 : parsed
}

function importanceScore(cluster: NewsCluster, newestAt: number) {
  const publishedAt = timestamp(cluster.publishedAt)
  const ageHours = publishedAt ? Math.max(0, (newestAt - publishedAt) / 3_600_000) : 24
  const recency = Math.max(0, 12 - ageHours)
  const articleWeight = Math.min(cluster.articleCount, 60) * 0.8
  const pressWeight = Math.min(cluster.pressList.length, 45) * 1.3
  const relevanceWeight = cluster.kind === 'company' ? 8 : cluster.kind === 'market' ? 3 : 0
  const confidenceWeight = (cluster.sentiment === 'positive' || cluster.sentiment === 'negative')
    && (cluster.sentimentScore ?? 0) >= 0.75 ? 2 : 0
  return articleWeight + pressWeight + relevanceWeight + recency + confidenceWeight
}

function pickBriefingClusters(clusters: NewsCluster[]) {
  if (clusters.length === 0) return []
  const datedClusters = clusters.filter((cluster) => timestamp(cluster.publishedAt) > 0)
  const newestAt = Math.max(...datedClusters.map((cluster) => timestamp(cluster.publishedAt)), Date.now())
  const newestDate = SEOUL_DATE.format(newestAt)
  const sameDay = clusters.filter((cluster) => {
    const publishedAt = timestamp(cluster.publishedAt)
    return publishedAt > 0 && SEOUL_DATE.format(publishedAt) === newestDate
  })
  const pool = sameDay.length >= 3 ? sameDay : clusters
  const ranked = [...pool].sort((left, right) => (
    importanceScore(right, newestAt) - importanceScore(left, newestAt)
    || timestamp(right.publishedAt) - timestamp(left.publishedAt)
  ))
  const selected: NewsCluster[] = []
  const stockCounts = new Map<string, number>()

  for (const cluster of ranked) {
    if ((stockCounts.get(cluster.stockCode) ?? 0) >= 1) continue
    selected.push(cluster)
    stockCounts.set(cluster.stockCode, (stockCounts.get(cluster.stockCode) ?? 0) + 1)
    if (selected.length === 3) break
  }
  if (selected.length < 3) {
    for (const cluster of ranked) {
      if (selected.some((item) => item.id === cluster.id)) continue
      selected.push(cluster)
      if (selected.length === 3) break
    }
  }
  return selected
}

function firstSentences(value: string, count = 2) {
  return value
    .replace(/\*\*/g, '')
    .replace(/^\s*(쉽게\s*말(?:해|하면)|이\s*기사는)\s*[:,]?\s*/u, '')
    .split(/(?<=[.!?])\s+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, count)
    .join(' ')
}

function BriefingMeta({ cluster }: { cluster: NewsCluster }) {
  const stock = getStock(cluster.stockCode)
  return (
    <span className="home-briefing__meta">
      {stock && <StockAvatar imageSrc={stock.imageSrc} initials={stock.initials} size="sm" />}
      <strong>{stock?.name ?? cluster.stockCode}</strong>
      {cluster.sentiment && <SentimentBadge score={cluster.sentimentScore ?? undefined} sentiment={cluster.sentiment} />}
    </span>
  )
}

export function HomeBriefing({
  clusters,
  error,
  issueBriefs,
  issueBriefsLoading,
  isLoading,
  onAsk,
  onNavigate,
}: Props) {
  const [openCluster, setOpenCluster] = useState<NewsCluster | null>(null)
  const [selectedStockCode, setSelectedStockCode] = useState(STOCKS[0].code)
  const briefingClusters = useMemo(() => pickBriefingClusters(clusters), [clusters])
  const lead = briefingClusters[0]
  const sideStories = briefingClusters.slice(1)
  const leadStock = lead ? getStock(lead.stockCode) : undefined
  const leadImage = lead?.sources?.find((source) => source.imageUrl)?.imageUrl ?? leadStock?.imageSrc
  const selectedBrief = issueBriefs[selectedStockCode]

  const handleImageError = (event: SyntheticEvent<HTMLImageElement>) => {
    if (leadStock?.imageSrc && event.currentTarget.src !== new URL(leadStock.imageSrc, window.location.href).href) {
      event.currentTarget.src = leadStock.imageSrc
      event.currentTarget.classList.add('is-fallback')
      return
    }
    event.currentTarget.hidden = true
  }

  return (
    <>
      <section className="home-briefing shell" aria-labelledby="home-briefing-title">
        <header className="home-briefing__header">
          <div>
            <span className="home-briefing__kicker"><Icon name="sparkles" size={16} /> 3분 브리핑</span>
            <h1 id="home-briefing-title">오늘의 주요 소식</h1>
          </div>
        </header>

        <section className="home-briefing__summary" aria-label="종목별 오늘의 핵심 변화">
          <div className="home-briefing__stock-tabs" role="tablist">
            {STOCKS.map((stock) => (
              <button
                aria-selected={selectedStockCode === stock.code}
                className={selectedStockCode === stock.code ? 'is-active' : ''}
                key={stock.code}
                onClick={() => setSelectedStockCode(stock.code)}
                role="tab"
                type="button"
              >
                <StockAvatar imageSrc={stock.imageSrc} initials={stock.initials} size="sm" />
                {stock.name}
              </button>
            ))}
          </div>
          <div className="home-briefing__signals">
            <article className="home-briefing__signal home-briefing__signal--positive">
              <header><span><i /> 좋아진 점</span></header>
              {issueBriefsLoading && <LoadingDots label="핵심 변화 불러오는 중" />}
              {!issueBriefsLoading && (selectedBrief?.positiveItems.length ?? 0) === 0 && (
                <div className="home-briefing__no-signal"><strong>아직 뚜렷한 변화가 없어요</strong></div>
              )}
              {!issueBriefsLoading && selectedBrief?.positiveItems.slice(0, 3).map((item) => <p key={`${selectedStockCode}:positive:${item.text}`}>{item.text}</p>)}
            </article>
            <article className="home-briefing__signal home-briefing__signal--negative">
              <header><span><i /> 주의할 점</span></header>
              {issueBriefsLoading && <LoadingDots label="핵심 변화 불러오는 중" />}
              {!issueBriefsLoading && (selectedBrief?.negativeItems.length ?? 0) === 0 && (
                <div className="home-briefing__no-signal"><strong>아직 주의할 변화가 없어요</strong></div>
              )}
              {!issueBriefsLoading && selectedBrief?.negativeItems.slice(0, 3).map((item) => <p key={`${selectedStockCode}:negative:${item.text}`}>{item.text}</p>)}
            </article>
          </div>
        </section>

        <div className="home-briefing__event-heading">
          <div><strong>이 흐름을 만든 주요 사건</strong><span>기사 수와 언론사 수, 최신성을 함께 봤어요.</span></div>
          <AppLink className="section-link" href="/news" onNavigate={onNavigate}>모든 사건 보기 <Icon name="arrow-right" size={16} /></AppLink>
        </div>

        {isLoading && <div className="home-briefing__empty"><LoadingDots label="오늘의 중요 소식을 고르는 중" /></div>}
        {!isLoading && error && <div className="home-briefing__empty">{error}</div>}
        {!isLoading && !error && !lead && <div className="home-briefing__empty">아직 정리된 뉴스가 없어요.</div>}

        {lead && (
          <div className="home-briefing__grid">
            <button className="home-briefing__lead" onClick={() => setOpenCluster(lead)} type="button">
              <span className="home-briefing__lead-image">
                {leadImage && <img alt="" onError={handleImageError} src={leadImage} />}
                <span>가장 중요한 소식</span>
              </span>
              <span className="home-briefing__lead-copy">
                <BriefingMeta cluster={lead} />
                <strong>{lead.title}</strong>
                <span>{firstSentences(lead.easySummary)}</span>
                <small>기사 {lead.articleCount}건 · 언론사 {lead.pressList.length}곳</small>
              </span>
            </button>

            <div className="home-briefing__side">
              {sideStories.map((cluster, index) => (
                <button className="home-briefing__story" key={cluster.id} onClick={() => setOpenCluster(cluster)} type="button">
                  <span className="home-briefing__rank">0{index + 2}</span>
                  <span>
                    <BriefingMeta cluster={cluster} />
                    <strong>{cluster.title}</strong>
                    <span>{firstSentences(cluster.easySummary, 1)}</span>
                    <small>기사 {cluster.articleCount}건 · 언론사 {cluster.pressList.length}곳</small>
                  </span>
                  <Icon name="chevron-right" size={18} />
                </button>
              ))}
            </div>
          </div>
        )}
      </section>
      {openCluster && <NewsClusterDetail cluster={openCluster} onAsk={onAsk} onClose={() => setOpenCluster(null)} />}
    </>
  )
}
