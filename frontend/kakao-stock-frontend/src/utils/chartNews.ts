import type { NewsCluster, PriceCandle, Sentiment } from '../types'

export interface NewsMoment {
  key: string
  time: number
  clusters: NewsCluster[]
  sentiment: Sentiment | null
}

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

function dominantSentiment(clusters: NewsCluster[]) {
  const counts: Record<Sentiment, number> = { negative: 0, neutral: 0, positive: 0 }
  clusters.forEach((cluster) => {
    if (cluster.sentiment) counts[cluster.sentiment] += 1
  })
  const ordered = (Object.entries(counts) as Array<[Sentiment, number]>)
    .sort((a, b) => b[1] - a[1])
  return ordered[0][1] > 0 ? ordered[0][0] : null
}

export function buildNewsMoments(candles: PriceCandle[], clusters: NewsCluster[]) {
  if (candles.length === 0) return []
  const candleDate = kstDateKey(candles.at(-1)?.time ?? '')
  const byMoment = new Map<string, Omit<NewsMoment, 'sentiment'>>()

  clusters.forEach((cluster) => {
    if (kstDateKey(cluster.publishedAt) !== candleDate) return
    const time = new Date(cluster.publishedAt).getTime()
    if (Number.isNaN(time)) return
    const bucket = Math.floor(time / (30 * 60 * 1000)) * 30 * 60 * 1000
    const key = String(bucket)
    const current = byMoment.get(key)
    if (current) current.clusters.push(cluster)
    else byMoment.set(key, { clusters: [cluster], key, time: bucket })
  })

  return [...byMoment.values()]
    .map((moment) => ({ ...moment, sentiment: dominantSentiment(moment.clusters) }))
    .sort((a, b) => a.time - b.time)
}
