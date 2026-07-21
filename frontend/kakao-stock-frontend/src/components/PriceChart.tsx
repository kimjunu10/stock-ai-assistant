import { useEffect, useRef, useState } from 'react'
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  type Time,
} from 'lightweight-charts'
import type { MarketDataStatus, StockMarketData, Theme } from '../types'
import { Icon } from './Icon'
import { LoadingDots } from './LoadingDots'

interface PriceChartProps {
  data: StockMarketData | null
  error: string
  onRetry: () => void
  status: MarketDataStatus
  stockName: string
  theme: Theme
}

const wonFormatter = new Intl.NumberFormat('ko-KR', {
  currency: 'KRW',
  maximumFractionDigits: 0,
  style: 'currency',
})

export function PriceChart({ data, error, onRetry, status, stockName, theme }: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [range, setRange] = useState<'intraday' | 'daily'>('intraday')

  useEffect(() => {
    const container = containerRef.current
    if (!container || !data || status !== 'ready') return

    const isDark = theme === 'dark'
    const isIntraday = range === 'intraday'
    const candles = isIntraday && data.intradayCandles.length > 0
      ? data.intradayCandles
      : data.candles
    const toChartTime = (value: string) => (
      isIntraday ? Math.floor(new Date(value).getTime() / 1000) : value
    ) as Time
    const chart = createChart(container, {
      autoSize: true,
      layout: {
        attributionLogo: true,
        background: { color: isDark ? '#17191f' : '#ffffff', type: ColorType.Solid },
        fontFamily: 'Pretendard Variable, Pretendard, sans-serif',
        fontSize: 12,
        textColor: isDark ? '#aeb4bf' : '#6b7280',
      },
      grid: {
        horzLines: { color: isDark ? 'rgba(255,255,255,0.055)' : 'rgba(15,23,42,0.055)' },
        vertLines: { color: isDark ? 'rgba(255,255,255,0.035)' : 'rgba(15,23,42,0.035)' },
      },
      localization: {
        locale: 'ko-KR',
      },
      rightPriceScale: {
        borderColor: isDark ? '#2b2f38' : '#edf0f3',
        scaleMargins: { bottom: 0.22, top: 0.08 },
      },
      timeScale: {
        borderColor: isDark ? '#2b2f38' : '#edf0f3',
        rightOffset: 4,
        secondsVisible: false,
        timeVisible: isIntraday,
      },
      crosshair: {
        horzLine: { color: isDark ? '#747b87' : '#9aa1ad', labelBackgroundColor: '#191919' },
        vertLine: { color: isDark ? '#747b87' : '#9aa1ad', labelBackgroundColor: '#191919' },
      },
    })

    const candleSeries = chart.addSeries(CandlestickSeries, {
      borderDownColor: '#3182f6',
      borderUpColor: '#f04452',
      downColor: '#3182f6',
      priceLineColor: data.quote.change >= 0 ? '#f04452' : '#3182f6',
      priceFormat: {
        formatter: (price: number) => wonFormatter.format(price),
        minMove: 1,
        type: 'custom',
      },
      upColor: '#f04452',
      wickDownColor: '#3182f6',
      wickUpColor: '#f04452',
    })
    candleSeries.setData(
      candles.map((candle) => ({
        close: candle.close,
        high: candle.high,
        low: candle.low,
        open: candle.open,
        time: toChartTime(candle.time),
      })),
    )

    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: isDark ? 'rgba(151,161,176,0.28)' : 'rgba(151,161,176,0.34)',
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    })
    volumeSeries.priceScale().applyOptions({ scaleMargins: { bottom: 0, top: 0.82 } })
    volumeSeries.setData(
      candles.map((candle) => ({
        color: isDark ? 'rgba(151,161,176,0.28)' : 'rgba(151,161,176,0.34)',
        time: toChartTime(candle.time),
        value: candle.volume,
      })),
    )

    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [data, range, status, theme])

  return (
    <div className="price-chart-frame">
      <div className="price-chart__meta">
        <div className="chart-range-tabs" role="tablist" aria-label="차트 기간">
          <button
            aria-selected={range === 'intraday'}
            className={range === 'intraday' ? 'active' : ''}
            onClick={() => setRange('intraday')}
            role="tab"
            type="button"
          >오늘 · 1분</button>
          <button
            aria-selected={range === 'daily'}
            className={range === 'daily' ? 'active' : ''}
            onClick={() => setRange('daily')}
            role="tab"
            type="button"
          >6개월 · 일봉</button>
        </div>
        <span><i className="live-dot" /> {range === 'intraday' ? '15초마다 갱신' : '수정주가'} · {data?.source ?? '토스증권 Open API'}</span>
      </div>
      <div
        aria-label={`${stockName} 실제 원화 ${range === 'intraday' ? '오늘 1분봉' : '6개월 일봉'} 차트`}
        className="price-chart__canvas"
        ref={containerRef}
      />
      {status === 'loading' && (
        <div className="chart-state chart-state--loading" role="status">
          <LoadingDots label="주가 차트 불러오는 중" />
        </div>
      )}
      {status === 'error' && (
        <div className="chart-state chart-state--error" role="alert">
          <span className="chart-state__icon"><Icon name="chart" size={22} /></span>
          <strong>차트를 불러오지 못했어요</strong>
          <p>{error}</p>
          <button className="secondary-button" onClick={onRetry} type="button">
            <Icon name="refresh" size={16} />
            다시 불러오기
          </button>
        </div>
      )}
    </div>
  )
}
