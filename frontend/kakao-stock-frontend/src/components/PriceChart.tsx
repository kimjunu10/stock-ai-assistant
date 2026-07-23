import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  type Time,
} from 'lightweight-charts'
import type {
  AssistantContext,
  MarketDataStatus,
  NewsCluster,
  StockMarketData,
  Theme,
} from '../types'
import { buildNewsMoments } from '../utils/chartNews'
import {
  ChartNewsMarkers,
  ChartNewsPanel,
} from './ChartNewsTimeline'
import { Icon } from './Icon'
import { LoadingDots } from './LoadingDots'

interface PriceChartProps {
  clusters: NewsCluster[]
  data: StockMarketData | null
  error: string
  onAsk: (context: AssistantContext) => void
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

function intradayChartTime(value: string | number) {
  const milliseconds = typeof value === 'number' ? value : new Date(value).getTime()
  // lightweight-charts는 Unix timestamp를 UTC 축으로 표시하므로 KST(+09:00)를 보정한다.
  return (Math.floor(milliseconds / 1000) + 9 * 60 * 60) as Time
}

export function PriceChart({
  clusters,
  data,
  error,
  onAsk,
  onRetry,
  status,
  stockName,
  theme,
}: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [range, setRange] = useState<'intraday' | 'daily'>('intraday')
  const moments = useMemo(
    () => buildNewsMoments(data?.intradayCandles ?? [], clusters),
    [clusters, data?.intradayCandles],
  )
  const [selectedMomentKey, setSelectedMomentKey] = useState('')
  const [markerPositions, setMarkerPositions] = useState<Record<string, number | null>>({})

  useEffect(() => {
    if (moments.length === 0) {
      setSelectedMomentKey('')
      return
    }
    if (!moments.some((moment) => moment.key === selectedMomentKey)) {
      setSelectedMomentKey(moments.at(-1)?.key ?? '')
    }
  }, [moments, selectedMomentKey])

  useEffect(() => {
    const container = containerRef.current
    if (!container || !data || status !== 'ready') return

    const isDark = theme === 'dark'
    const isIntraday = range === 'intraday'
    const candles = isIntraday && data.intradayCandles.length > 0
      ? data.intradayCandles
      : data.candles
    const toChartTime = (value: string) => (
      isIntraday ? intradayChartTime(value) : value
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
      localization: { locale: 'ko-KR' },
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
    candleSeries.setData(candles.map((candle) => ({
      close: candle.close,
      high: candle.high,
      low: candle.low,
      open: candle.open,
      time: toChartTime(candle.time),
    })))

    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: isDark ? 'rgba(151,161,176,0.28)' : 'rgba(151,161,176,0.34)',
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    })
    volumeSeries.priceScale().applyOptions({ scaleMargins: { bottom: 0, top: 0.82 } })
    volumeSeries.setData(candles.map((candle) => ({
      color: isDark ? 'rgba(151,161,176,0.28)' : 'rgba(151,161,176,0.34)',
      time: toChartTime(candle.time),
      value: candle.volume,
    })))

    const updateMarkerPositions = () => {
      if (!isIntraday) {
        setMarkerPositions({})
        return
      }
      const width = container.clientWidth
      setMarkerPositions(Object.fromEntries(moments.map((moment) => {
        const coordinate = chart.timeScale().timeToCoordinate(intradayChartTime(moment.time))
        const visible = coordinate !== null && coordinate >= 12 && coordinate <= width - 12
        return [moment.key, visible ? coordinate : null]
      })))
    }

    const resizeObserver = new ResizeObserver(updateMarkerPositions)
    resizeObserver.observe(container)
    chart.timeScale().subscribeVisibleTimeRangeChange(updateMarkerPositions)
    if (isIntraday && candles.length > 0) {
      const latestTime = new Date(candles.at(-1)?.time ?? '').getTime()
      const twoHours = 2 * 60 * 60 * 1000
      const edgePadding = 5 * 60 * 1000
      chart.timeScale().setVisibleRange({
        from: intradayChartTime(latestTime - twoHours - edgePadding),
        to: intradayChartTime(latestTime),
      })
    } else {
      chart.timeScale().fitContent()
    }
    const animationFrame = requestAnimationFrame(updateMarkerPositions)

    return () => {
      cancelAnimationFrame(animationFrame)
      resizeObserver.disconnect()
      chart.timeScale().unsubscribeVisibleTimeRangeChange(updateMarkerPositions)
      chart.remove()
    }
  }, [data, moments, range, status, theme])

  const selectedMoment = moments.find((moment) => moment.key === selectedMomentKey)

  return (
    <div className="price-chart-experience">
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
        {range === 'intraday' && status === 'ready' && (
          <div className="price-chart__news-track">
            <ChartNewsMarkers
              moments={moments}
              onSelect={setSelectedMomentKey}
              positions={markerPositions}
              selectedKey={selectedMomentKey}
            />
          </div>
        )}
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
      {range === 'intraday' && <ChartNewsPanel moment={selectedMoment} onAsk={onAsk} />}
    </div>
  )
}
