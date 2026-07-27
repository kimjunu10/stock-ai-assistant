import { useEffect, useRef } from 'react'
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  createChart,
  type Time,
} from 'lightweight-charts'

export interface RagPricePoint {
  tradingDay: string
  close: number
  open?: number
  high?: number
  low?: number
  volume?: number
}

interface RagPriceChartProps {
  label: string
  points: RagPricePoint[]
}

const wonFormatter = new Intl.NumberFormat('ko-KR', {
  currency: 'KRW',
  maximumFractionDigits: 0,
  style: 'currency',
})

function hasOhlc(point: RagPricePoint) {
  return (
    typeof point.open === 'number'
    && typeof point.high === 'number'
    && typeof point.low === 'number'
    && point.open > 0
    && point.high > 0
    && point.low > 0
  )
}

export function RagPriceChart({ label, points }: RagPriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container || points.length < 2 || typeof ResizeObserver === 'undefined') return

    const styles = getComputedStyle(document.documentElement)
    const surface = styles.getPropertyValue('--surface').trim() || '#ffffff'
    const muted = styles.getPropertyValue('--muted').trim() || '#6b7280'
    const line = styles.getPropertyValue('--line').trim() || '#edf0f3'
    const rising = points.at(-1)!.close >= points[0]!.close
    const chart = createChart(container, {
      autoSize: true,
      layout: {
        attributionLogo: false,
        background: { color: surface, type: ColorType.Solid },
        fontFamily: 'Pretendard Variable, Pretendard, sans-serif',
        fontSize: 12,
        textColor: muted,
      },
      grid: {
        horzLines: { color: line },
        vertLines: { color: 'transparent' },
      },
      localization: { locale: 'ko-KR' },
      rightPriceScale: {
        borderColor: line,
        scaleMargins: { bottom: 0.2, top: 0.1 },
      },
      timeScale: {
        borderColor: line,
        rightOffset: 1,
        secondsVisible: false,
        timeVisible: false,
      },
      crosshair: {
        horzLine: { color: muted, labelBackgroundColor: '#191919' },
        vertLine: { color: muted, labelBackgroundColor: '#191919' },
      },
    })

    if (points.every(hasOhlc)) {
      const candleSeries = chart.addSeries(CandlestickSeries, {
        borderDownColor: '#3182f6',
        borderUpColor: '#f04452',
        downColor: '#3182f6',
        priceLineColor: rising ? '#f04452' : '#3182f6',
        priceFormat: {
          formatter: (price: number) => wonFormatter.format(price),
          minMove: 1,
          type: 'custom',
        },
        upColor: '#f04452',
        wickDownColor: '#3182f6',
        wickUpColor: '#f04452',
      })
      candleSeries.setData(points.map((point) => ({
        close: point.close,
        high: point.high!,
        low: point.low!,
        open: point.open!,
        time: point.tradingDay as Time,
      })))
    } else {
      const lineSeries = chart.addSeries(LineSeries, {
        color: rising ? '#f04452' : '#3182f6',
        lineWidth: 3,
        priceFormat: {
          formatter: (price: number) => wonFormatter.format(price),
          minMove: 1,
          type: 'custom',
        },
      })
      lineSeries.setData(points.map((point) => ({
        time: point.tradingDay as Time,
        value: point.close,
      })))
    }

    const volumePoints = points.filter(
      (point): point is RagPricePoint & { volume: number } => (
        typeof point.volume === 'number' && point.volume > 0
      ),
    )
    if (volumePoints.length === points.length) {
      const volumeSeries = chart.addSeries(HistogramSeries, {
        color: 'rgba(151,161,176,.3)',
        priceFormat: { type: 'volume' },
        priceScaleId: '',
      })
      volumeSeries.priceScale().applyOptions({ scaleMargins: { bottom: 0, top: 0.84 } })
      volumeSeries.setData(volumePoints.map((point) => ({
        color: 'rgba(151,161,176,.3)',
        time: point.tradingDay as Time,
        value: point.volume,
      })))
    }

    if (points.length <= 4) {
      chart.timeScale().setVisibleLogicalRange({ from: -1.5, to: points.length + 0.5 })
    } else {
      chart.timeScale().fitContent()
    }

    return () => chart.remove()
  }, [points])

  return <div aria-label={label} className="answer-price-chart__canvas" ref={containerRef} role="img" />
}
