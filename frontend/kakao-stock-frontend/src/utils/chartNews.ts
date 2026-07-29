import type { NewsCluster, PriceCandle, Sentiment } from '../types'

export interface NewsMoment {
  key: string
  time: number
  clusters: NewsCluster[]
  sentiment: Sentiment | null
}

const NEWS_INTERVAL_MS = 30 * 60 * 1000

export function kstDateKey(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('en-CA', {
    day: '2-digit',
    month: '2-digit',
    timeZone: 'Asia/Seoul',
    year: 'numeric',
  }).format(date)
}

function dominantSentiment(clusters: NewsCluster[]) {
  const counts: Record<Sentiment, number> = { negative: 0, neutral: 0, positive: 0 }
  clusters.forEach((cluster) => {
    if (cluster.sentiment) counts[cluster.sentiment] += 1
  })
  const ordered = (Object.entries(counts) as Array<[Sentiment, number]>)
    .sort((a, b) => b[1] - a[1])
  return ordered[0][1] > 0 ? ordered[0][0] : null
}

function newsIntervalEnd(time: number) {
  // 차트 마커는 기사 시각이 속한 수집 구간의 종료 시각(정각/30분)에 고정한다.
  // 클러스터 last_active_at은 후속 기사마다 바뀌므로 원문 시각이 있을 때는 사용하지 않는다.
  return Math.ceil(time / NEWS_INTERVAL_MS) * NEWS_INTERVAL_MS
}

export function buildNewsMoments(candles: PriceCandle[], clusters: NewsCluster[]) {
  if (candles.length === 0) return []
  const candleDate = kstDateKey(candles.at(-1)?.time ?? '')
  const byMoment = new Map<string, Map<number, NewsCluster>>()

  clusters.forEach((cluster) => {
    const clusterSources = cluster.sources ?? []
    const sourcesByMoment = new Map<number, NonNullable<NewsCluster['sources']>>()
    clusterSources.forEach((source) => {
      if (kstDateKey(source.publishedAt) !== candleDate) return
      const sourceTime = new Date(source.publishedAt).getTime()
      if (Number.isNaN(sourceTime)) return
      const bucket = newsIntervalEnd(sourceTime)
      const sources = sourcesByMoment.get(bucket) ?? []
      sources.push(source)
      sourcesByMoment.set(bucket, sources)
    })

    if (sourcesByMoment.size > 0) {
      sourcesByMoment.forEach((momentSources, bucket) => {
        const sortedMomentSources = [...momentSources].sort((a, b) => (
          new Date(b.publishedAt).getTime() - new Date(a.publishedAt).getTime()
        ))
        const momentSourceIds = new Set(sortedMomentSources.map((source) => source.articleId))
        const occurrence = {
          ...cluster,
          publishedAt: sortedMomentSources[0]?.publishedAt ?? cluster.publishedAt,
          sources: [
            ...sortedMomentSources,
            ...clusterSources.filter((source) => !momentSourceIds.has(source.articleId)),
          ],
        }
        const key = String(bucket)
        const clustersInMoment = byMoment.get(key) ?? new Map<number, NewsCluster>()
        clustersInMoment.set(cluster.id, occurrence)
        byMoment.set(key, clustersInMoment)
      })
      return
    }

    if (kstDateKey(cluster.publishedAt) === candleDate) {
      const time = new Date(cluster.publishedAt).getTime()
      if (Number.isNaN(time)) return
      const bucket = newsIntervalEnd(time)
      const key = String(bucket)
      const clustersInMoment = byMoment.get(key) ?? new Map<number, NewsCluster>()
      clustersInMoment.set(cluster.id, cluster)
      byMoment.set(key, clustersInMoment)
    }
  })

  return [...byMoment.entries()]
    .map(([key, clustersInMoment]) => {
      const sortedClusters = [...clustersInMoment.values()].sort((a, b) => (
        b.articleCount - a.articleCount
        || new Date(b.publishedAt).getTime() - new Date(a.publishedAt).getTime()
      ))
      return {
        key,
        time: Number(key),
        clusters: sortedClusters,
        sentiment: dominantSentiment(sortedClusters),
      }
    })
    .sort((a, b) => a.time - b.time)
}
