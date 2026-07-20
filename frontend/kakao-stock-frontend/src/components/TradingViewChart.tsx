import { useEffect, useRef, useState } from 'react'
import type { Theme } from '../types'
import { Icon } from './Icon'

const TRADING_VIEW_SCRIPT =
  'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'

interface TradingViewChartProps {
  stockCode: string
  stockName: string
  theme: Theme
}

type ChartStatus = 'loading' | 'ready' | 'error'

const TRADING_VIEW_SYMBOLS: Record<string, string> = {
  '005930': 'KRX:005930',
  '000660': 'KRX:000660',
  '034020': 'KRX:034020',
  '042660': 'KRX:042660',
  '005380': 'KRX:005380',
}

export function TradingViewChart({ stockCode, stockName, theme }: TradingViewChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<ChartStatus>('loading')
  const [attempt, setAttempt] = useState(0)
  const symbol = TRADING_VIEW_SYMBOLS[stockCode] ?? `KRX:${stockCode}`

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    let active = true
    let scriptSettled = false
    setStatus('loading')

    const mount = document.createElement('div')
    mount.className = 'tradingview-widget-mount'

    const widget = document.createElement('div')
    widget.className = 'tradingview-widget-container__widget'
    widget.style.height = 'calc(100% - 30px)'
    widget.style.width = '100%'

    const copyright = document.createElement('div')
    copyright.className = 'tradingview-widget-copyright'

    const link = document.createElement('a')
    link.href = `https://www.tradingview.com/symbols/KRX-${stockCode}/`
    link.rel = 'noopener nofollow'
    link.target = '_blank'

    const linkText = document.createElement('span')
    linkText.className = 'blue-text'
    linkText.textContent = `${stockName} 차트`
    link.appendChild(linkText)

    const trademark = document.createElement('span')
    trademark.className = 'trademark'
    trademark.textContent = ' by TradingView'
    copyright.append(link, trademark)

    const script = document.createElement('script')
    script.src = TRADING_VIEW_SCRIPT
    script.type = 'text/javascript'
    script.async = true
    script.text = JSON.stringify({
      autosize: true,
      symbol,
      interval: 'D',
      range: '6M',
      timezone: 'Asia/Seoul',
      theme,
      backgroundColor: theme === 'dark' ? '#17191f' : '#ffffff',
      gridColor: theme === 'dark' ? 'rgba(255, 255, 255, 0.06)' : 'rgba(15, 23, 42, 0.06)',
      style: '1',
      locale: 'ko',
      withdateranges: true,
      hide_side_toolbar: true,
      hide_top_toolbar: true,
      hide_legend: false,
      hide_volume: false,
      allow_symbol_change: false,
      save_image: false,
      calendar: false,
      details: false,
      hotlist: false,
      watchlist: [],
      compareSymbols: [],
      studies: [],
      show_popup_button: false,
      support_host: 'https://www.tradingview.com',
    })

    const observer = new MutationObserver(() => {
      if (active && mount.querySelector('iframe')) {
        setStatus('ready')
        observer.disconnect()
      }
    })

    script.onerror = () => {
      scriptSettled = true
      if (active) {
        setStatus('error')
      } else {
        mount.remove()
      }
    }
    script.onload = () => {
      scriptSettled = true
      if (active && mount.querySelector('iframe')) {
        setStatus('ready')
      } else if (!active) {
        mount.remove()
      }
    }

    mount.append(widget, copyright, script)
    container.append(mount)
    observer.observe(mount, { childList: true, subtree: true })

    const timeoutId = window.setTimeout(() => {
      if (active && !mount.querySelector('iframe')) setStatus('error')
    }, 15000)

    return () => {
      active = false
      window.clearTimeout(timeoutId)
      observer.disconnect()
      mount.style.display = 'none'

      // The third-party async script reads its own parent while executing.
      // Keep a pending mount attached until load/error so rapid route changes
      // cannot leave document.currentScript.parentNode as null.
      if (scriptSettled) mount.remove()
    }
  }, [attempt, stockCode, stockName, symbol, theme])

  return (
    <div className="tradingview-chart-frame">
      <div
        aria-label={`${stockName} TradingView 6개월 일봉 차트`}
        className="tradingview-widget-container"
        ref={containerRef}
      />
      {status === 'loading' && (
        <div className="chart-state chart-state--loading" role="status">
          <span className="chart-loader" />
          <strong>차트를 불러오고 있어요</strong>
          <p>{symbol} · 1일봉 · 최근 6개월</p>
        </div>
      )}
      {status === 'error' && (
        <div className="chart-state chart-state--error" role="alert">
          <span className="chart-state__icon">
            <Icon name="chart" size={22} />
          </span>
          <strong>차트를 불러오지 못했어요</strong>
          <p>네트워크 연결을 확인한 뒤 다시 시도해 주세요.</p>
          <button className="secondary-button" onClick={() => setAttempt((value) => value + 1)} type="button">
            <Icon name="refresh" size={16} />
            다시 불러오기
          </button>
        </div>
      )}
    </div>
  )
}
