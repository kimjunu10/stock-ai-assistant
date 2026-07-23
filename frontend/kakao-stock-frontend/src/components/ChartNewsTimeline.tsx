import { useEffect, useState, type SyntheticEvent } from 'react'
import { getStock } from '../data/mockData'
import type { AssistantContext, NewsCluster } from '../types'
import type { NewsMoment } from '../utils/chartNews'
import { Icon } from './Icon'
import { SentimentBadge } from './SentimentBadge'

interface ChartNewsMarkersProps {
  moments: NewsMoment[]
  onSelect: (key: string) => void
  positions: Record<string, number | null>
  selectedKey: string
}

interface ChartNewsPanelProps {
  moment: NewsMoment | undefined
  onAsk: (context: AssistantContext) => void
}

const timeFormatter = new Intl.DateTimeFormat('ko-KR', {
  hour: '2-digit',
  hour12: false,
  minute: '2-digit',
  timeZone: 'Asia/Seoul',
})

export function ChartNewsMarkers({
  moments,
  onSelect,
  positions,
  selectedKey,
}: ChartNewsMarkersProps) {
  return (
    <div className="price-chart__news-markers" aria-label="차트 시간대별 뉴스">
      {moments.map((moment) => {
        const left = positions[moment.key]
        if (left === null || left === undefined) return null
        const active = moment.key === selectedKey
        return (
          <button
            aria-label={`${timeFormatter.format(moment.time)} 뉴스 ${moment.clusters.length}건`}
            aria-pressed={active}
            className={[
              'price-chart__news-marker',
              moment.sentiment ? `is-${moment.sentiment}` : 'is-unknown',
              active ? 'is-active' : '',
            ].filter(Boolean).join(' ')}
            key={moment.key}
            onClick={() => onSelect(moment.key)}
            onFocus={() => onSelect(moment.key)}
            onMouseEnter={() => onSelect(moment.key)}
            style={{ left }}
            type="button"
          >
            <i />
            {moment.clusters.length > 1 && <b>{moment.clusters.length}</b>}
          </button>
        )
      })}
    </div>
  )
}

function TimelineStory({
  cluster,
  onAsk,
}: {
  cluster: NewsCluster
  onAsk: ChartNewsPanelProps['onAsk']
}) {
  const stock = getStock(cluster.stockCode)
  const source = cluster.sources?.[0]
  const image = cluster.sources?.find((item) => item.imageUrl)?.imageUrl ?? stock?.imageSrc
  const [imageFailed, setImageFailed] = useState(false)
  const handleImageError = (event: SyntheticEvent<HTMLImageElement>) => {
    if (!imageFailed && stock?.imageSrc && event.currentTarget.src !== new URL(stock.imageSrc, window.location.href).href) {
      event.currentTarget.src = stock.imageSrc
      event.currentTarget.classList.add('is-fallback')
      setImageFailed(true)
      return
    }
    event.currentTarget.hidden = true
  }

  return (
    <article className="chart-news-story">
      <div className="chart-news-story__image">
        {image && <img alt="" onError={handleImageError} src={image} />}
        <time>{timeFormatter.format(new Date(cluster.publishedAt))}</time>
      </div>
      <div className="chart-news-story__content">
        <div>
          {cluster.sentiment
            ? <SentimentBadge score={cluster.sentimentScore ?? undefined} sentiment={cluster.sentiment} variant="prominent" />
            : <span className="chart-news-story__pending">분석 전</span>}
          <span>
            {source?.press ? `${source.press} · ` : ''}
            기사 {cluster.articleCount}건
          </span>
        </div>
        <strong>{cluster.title}</strong>
        <button
          onClick={() => onAsk({
            stockCode: cluster.stockCode,
            sourceId: String(cluster.id),
            sourceType: 'news_cluster',
            title: cluster.title,
          })}
          type="button"
        >
          <Icon name="message" size={16} />
          이 뉴스에 질문하기
        </button>
      </div>
    </article>
  )
}

export function ChartNewsPanel({ moment, onAsk }: ChartNewsPanelProps) {
  const [visibleCount, setVisibleCount] = useState(3)

  useEffect(() => {
    setVisibleCount(3)
  }, [moment?.key])

  if (!moment) return null
  const visible = moment.clusters.slice(0, visibleCount)
  const remainingCount = Math.max(0, moment.clusters.length - visibleCount)

  return (
    <section className="chart-news-panel" aria-live="polite">
      <div className="chart-news-panel__heading">
        <div>
          <span>{timeFormatter.format(moment.time)} 전후</span>
          <h3>주가가 움직인 시간의 뉴스</h3>
        </div>
        <p>사진과 제목, 호재·악재 여부를 먼저 확인하세요.</p>
      </div>
      <div className="chart-news-panel__grid">
        {visible.map((cluster) => <TimelineStory cluster={cluster} key={cluster.id} onAsk={onAsk} />)}
      </div>
      {moment.clusters.length > 3 && (
        <button
          className="chart-news-panel__more"
          onClick={() => setVisibleCount((count) => (
            remainingCount > 0 ? Math.min(moment.clusters.length, count + 6) : 3
          ))}
          type="button"
        >
          {remainingCount > 0
            ? `뉴스 ${Math.min(6, remainingCount)}개 더보기`
            : '접기'}
          <Icon name="arrow-right" size={16} />
        </button>
      )}
    </section>
  )
}
