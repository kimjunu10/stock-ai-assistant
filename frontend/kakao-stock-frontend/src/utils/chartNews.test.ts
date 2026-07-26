import { describe, expect, it } from 'vitest'
import type { NewsCluster, PriceCandle } from '../types'
import { buildNewsMoments, kstDateKey } from './chartNews'

const candle = (time: string): PriceCandle => ({
  close: 100,
  high: 101,
  low: 99,
  open: 100,
  time,
  volume: 10,
})

const cluster = (id: number, publishedAt: string): NewsCluster => ({
  articleCount: 1,
  easySummary: '',
  id,
  pressList: [],
  publishedAt,
  stockCode: '005930',
  title: `뉴스 ${id}`,
})

describe('chart news date synchronization', () => {
  it('converts UTC timestamps to the Korean market date', () => {
    expect(kstDateKey('2026-07-24T15:30:00+00:00')).toBe('2026-07-25')
  })

  it('keeps only news from the latest intraday candle date', () => {
    const moments = buildNewsMoments(
      [
        candle('2026-07-24T05:00:00+00:00'),
        candle('2026-07-24T06:00:00+00:00'),
      ],
      [
        cluster(1, '2026-07-24T05:10:00+00:00'),
        cluster(2, '2026-07-25T05:10:00+00:00'),
      ],
    )

    expect(moments).toHaveLength(1)
    expect(moments[0]?.clusters.map((item) => item.id)).toEqual([1])
  })
})
