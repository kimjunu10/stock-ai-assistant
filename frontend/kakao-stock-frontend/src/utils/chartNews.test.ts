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

const cluster = (
  id: number,
  publishedAt: string,
  sourceTimes: string[] = [],
): NewsCluster => ({
  articleCount: 1,
  easySummary: '',
  id,
  pressList: [],
  publishedAt,
  sources: sourceTimes.map((sourceTime, index) => ({
    articleId: id * 100 + index,
    description: '',
    press: '테스트뉴스',
    publishedAt: sourceTime,
    title: `원문 ${index + 1}`,
    url: `https://example.com/${id}/${index}`,
  })),
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

  it('places articles at the end of their 30-minute collection interval', () => {
    const moments = buildNewsMoments(
      [candle('2026-07-29T02:30:00+00:00')],
      [
        cluster(1, '2026-07-29T02:20:00+00:00', ['2026-07-29T00:26:00+00:00']),
        cluster(2, '2026-07-29T02:20:00+00:00', ['2026-07-29T00:36:00+00:00']),
      ],
    )

    expect(moments.map((moment) => new Date(moment.time).toISOString())).toEqual([
      '2026-07-29T00:30:00.000Z',
      '2026-07-29T01:00:00.000Z',
    ])
    expect(moments.map((moment) => moment.clusters.map((item) => item.id))).toEqual([
      [1],
      [2],
    ])
  })

  it('shows later articles as follow-ups without repeating the cluster summary title', () => {
    const moments = buildNewsMoments(
      [candle('2026-07-29T02:30:00+00:00')],
      [
        cluster(
          1,
          '2026-07-29T02:20:00+00:00',
          [
            '2026-07-29T00:26:00+00:00',
            '2026-07-29T00:36:00+00:00',
            '2026-07-29T01:36:00+00:00',
          ],
        ),
      ],
    )

    expect(moments.map((moment) => new Date(moment.time).toISOString())).toEqual([
      '2026-07-29T00:30:00.000Z',
      '2026-07-29T01:00:00.000Z',
      '2026-07-29T02:00:00.000Z',
    ])
    expect(moments.every((moment) => moment.clusters[0]?.id === 1)).toBe(true)
    expect(moments.map((moment) => moment.clusters[0]?.timelineKind)).toEqual([
      'initial',
      'follow_up',
      'follow_up',
    ])
    expect(moments.map((moment) => moment.clusters[0]?.timelineTitle)).toEqual([
      '뉴스 1',
      '원문 2',
      '원문 3',
    ])
    expect(moments.map((moment) => moment.clusters[0]?.publishedAt)).toEqual([
      '2026-07-29T00:26:00+00:00',
      '2026-07-29T00:36:00+00:00',
      '2026-07-29T01:36:00+00:00',
    ])
    expect(moments.map((moment) => moment.clusters[0]?.sources?.[0]?.publishedAt)).toEqual([
      '2026-07-29T00:26:00+00:00',
      '2026-07-29T00:36:00+00:00',
      '2026-07-29T01:36:00+00:00',
    ])
  })

  it('does not count a cluster twice when multiple articles land in one interval', () => {
    const moments = buildNewsMoments(
      [candle('2026-07-29T02:30:00+00:00')],
      [
        cluster(
          1,
          '2026-07-29T02:20:00+00:00',
          ['2026-07-29T00:31:00+00:00', '2026-07-29T00:59:00+00:00'],
        ),
      ],
    )

    expect(moments).toHaveLength(1)
    expect(moments[0]?.clusters.map((item) => item.id)).toEqual([1])
    expect(moments[0]?.clusters[0]?.publishedAt).toBe('2026-07-29T00:59:00+00:00')
    expect(moments[0]?.clusters[0]?.sources?.[0]?.publishedAt).toBe(
      '2026-07-29T00:59:00+00:00',
    )
  })

  it('keeps an exact interval boundary at that completed collection interval', () => {
    const moments = buildNewsMoments(
      [candle('2026-07-29T02:30:00+00:00')],
      [cluster(1, '2026-07-29T02:20:00+00:00', ['2026-07-29T00:30:00+00:00'])],
    )

    expect(new Date(moments[0]?.time ?? 0).toISOString()).toBe('2026-07-29T00:30:00.000Z')
  })
})
