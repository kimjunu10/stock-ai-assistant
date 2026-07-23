import { useEffect, useMemo, useState } from 'react'
import type { AssistantContext, NewsCluster, PriceCandle } from '../types'
import { Icon } from './Icon'

interface ChartNewsTimelineProps {
  candles: PriceCandle[]
  clusters: NewsCluster[]
  onAsk: (context: AssistantContext) => void
  stockName: string
}

interface NewsMoment {
  key: string
  time: number
  clusters: NewsCluster[]
}

const timeFormatter = new Intl.DateTimeFormat('ko-KR', {
  hour: '2-digit',
  hour12: false,
  minute: '2-digit',
  timeZone: 'Asia/Seoul',
})

function kstDateKey(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('en-CA', {
    day: '2-digit',
    month: '2-digit',
    timeZone: 'Asia/Seoul',
    year: 'numeric',
  }).format(date)
}

export function ChartNewsTimeline({
  candles,
  clusters,
  onAsk,
  stockName,
}: ChartNewsTimelineProps) {
  const moments = useMemo(() => {
    if (candles.length === 0) return []
    const candleDate = kstDateKey(candles.at(-1)?.time ?? '')
    const byMoment = new Map<string, NewsMoment>()

    clusters.forEach((cluster) => {
      if (kstDateKey(cluster.publishedAt) !== candleDate) return
      const time = new Date(cluster.publishedAt).getTime()
      if (Number.isNaN(time)) return
      // 가까운 뉴스가 겹치지 않도록 30분 단위로 묶고, 상세에는 각 기사 시각을 그대로 표시한다.
      const bucket = Math.floor(time / (30 * 60 * 1000)) * 30 * 60 * 1000
      const key = String(bucket)
      const current = byMoment.get(key)
      if (current) current.clusters.push(cluster)
      else byMoment.set(key, { clusters: [cluster], key, time: bucket })
    })

    return [...byMoment.values()].sort((a, b) => a.time - b.time)
  }, [candles, clusters])
  const [selectedKey, setSelectedKey] = useState('')
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    if (moments.length === 0) {
      setSelectedKey('')
      return
    }
    if (!moments.some((moment) => moment.key === selectedKey)) {
      setSelectedKey(moments.at(-1)?.key ?? '')
    }
  }, [moments, selectedKey])

  if (candles.length === 0) return null
  const start = new Date(candles[0].time).getTime()
  const end = new Date(candles.at(-1)?.time ?? candles[0].time).getTime()
  const selected = moments.find((moment) => moment.key === selectedKey)
  const visibleClusters = expanded ? selected?.clusters : selected?.clusters.slice(0, 3)

  return (
    <div className="chart-news-timeline">
      <div className="chart-news-timeline__heading">
        <div>
          <span>오늘의 뉴스 흐름</span>
          <strong>주가가 움직인 시간에 어떤 소식이 있었는지 확인하세요.</strong>
        </div>
        <span>{moments.length > 0 ? `${moments.reduce((sum, item) => sum + item.clusters.length, 0)}개 사건` : '오늘 연결된 뉴스 없음'}</span>
      </div>
      <div className="chart-news-timeline__rail" aria-label={`${stockName} 오늘 뉴스 타임라인`}>
        <span className="chart-news-timeline__line" />
        {moments.map((moment) => {
          const position = end === start ? 50 : Math.min(98, Math.max(2, (moment.time - start) / (end - start) * 100))
          const active = moment.key === selectedKey
          return (
            <button
              aria-label={`${timeFormatter.format(moment.time)} 뉴스 ${moment.clusters.length}건`}
              aria-pressed={active}
              className={`chart-news-timeline__marker${active ? ' is-active' : ''}`}
              key={moment.key}
              onClick={() => {
                setSelectedKey(moment.key)
                setExpanded(false)
              }}
              onFocus={() => setSelectedKey(moment.key)}
              onMouseEnter={() => setSelectedKey(moment.key)}
              style={{ left: `${position}%` }}
              type="button"
            >
              <i />
              <span>{timeFormatter.format(moment.time)}</span>
              {moment.clusters.length > 1 && <b>{moment.clusters.length}</b>}
            </button>
          )
        })}
      </div>
      {selected && visibleClusters && (
        <div className="chart-news-timeline__panel">
          <div className="chart-news-timeline__panel-head">
            <strong>{timeFormatter.format(selected.time)} 전후 주요 뉴스</strong>
            <span>원을 누르면 이 시간대 소식이 바뀌어요.</span>
          </div>
          <div className="chart-news-timeline__stories">
            {visibleClusters.map((cluster) => (
              <article key={cluster.id}>
                <time>{timeFormatter.format(new Date(cluster.publishedAt))}</time>
                <div>
                  <strong>{cluster.title}</strong>
                  <p>{cluster.easySummary}</p>
                </div>
                <button
                  onClick={() => onAsk({
                    stockCode: cluster.stockCode,
                    sourceId: String(cluster.id),
                    sourceType: 'news_cluster',
                    title: cluster.title,
                  })}
                  type="button"
                >
                  <Icon name="message" size={15} />
                  AI에게 질문
                </button>
              </article>
            ))}
          </div>
          {(selected.clusters.length > 3 || expanded) && (
            <button
              className="chart-news-timeline__more"
              onClick={() => setExpanded((value) => !value)}
              type="button"
            >
              {expanded ? '간단히 보기' : `${selected.clusters.length - 3}개 더보기`}
              <Icon name="arrow-right" size={15} />
            </button>
          )}
        </div>
      )}
    </div>
  )
}
