import { useEffect, useRef, useState } from 'react'
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  type IChartApi,
  type Time,
} from 'lightweight-charts'
import { fetchStockMarketData } from '../api/marketData'
import type { StockMarketData } from '../types'

export function RagMarketChart({ stockCode }: { stockCode: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const [data, setData] = useState<StockMarketData | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    fetchStockMarketData(stockCode, controller.signal)
      .then(setData)
      .catch(() => setData(null))
    return () => controller.abort()
  }, [stockCode])

  useEffect(() => {
    const container = containerRef.current
    if (!container || !data || data.candles.length < 2) return
    const styles = getComputedStyle(document.documentElement)
    const canvas = styles.getPropertyValue('--surface').trim() || '#ffffff'
    const muted = styles.getPropertyValue('--muted').trim() || '#6b7280'
    const line = styles.getPropertyValue('--line').trim() || '#eceef2'
    const chart = createChart(container, {
      autoSize: true,
      height: 260,
      layout: {
        attributionLogo: false,
        background: { color: canvas, type: ColorType.Solid },
        fontFamily: 'Pretendard Variable, Pretendard, sans-serif',
        fontSize: 11,
        textColor: muted,
      },
      grid: {
        horzLines: { color: line },
        vertLines: { color: 'transparent' },
      },
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: { bottom: 0.22, top: 0.08 },
      },
      timeScale: {
        borderVisible: false,
        rightOffset: 3,
        timeVisible: false,
      },
    })
    chartRef.current = chart
    const candles = chart.addSeries(CandlestickSeries, {
      borderDownColor: '#4c83f3',
      borderUpColor: '#f05c68',
      downColor: '#4c83f3',
      priceLineVisible: false,
      upColor: '#f05c68',
      wickDownColor: '#4c83f3',
      wickUpColor: '#f05c68',
    })
    candles.setData(data.candles.map((item) => ({
      close: item.close,
      high: item.high,
      low: item.low,
      open: item.open,
      time: item.time as Time,
    })))
    const volume = chart.addSeries(HistogramSeries, {
      color: 'rgba(148, 163, 184, .25)',
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    })
    volume.priceScale().applyOptions({ scaleMargins: { bottom: 0, top: 0.84 } })
    volume.setData(data.candles.map((item) => ({
      time: item.time as Time,
      value: item.volume,
    })))
    chart.timeScale().fitContent()
    return () => {
      chartRef.current = null
      chart.remove()
    }
  }, [data])

  if (!data || data.candles.length < 2) return null
  return (
    <div className="answer-market-chart">
      <header><strong>6개월 주가 흐름</strong><span>일봉 · {data.source}</span></header>
      <div aria-label={`${stockCode} 6개월 일봉 차트`} ref={containerRef} role="img" />
    </div>
  )
}
