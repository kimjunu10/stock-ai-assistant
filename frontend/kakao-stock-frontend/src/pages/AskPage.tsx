import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { Icon } from '../components/Icon'
import { RagConversation } from '../components/RagConversation'
import { StockAvatar } from '../components/StockAvatar'
import { STOCKS } from '../data/mockData'
import type { StockContextErrorCode } from '../types/qa'

function StockPicker({
  attention,
  buttonRef,
  onChange,
  value,
}: {
  attention?: boolean
  buttonRef?: RefObject<HTMLButtonElement | null>
  onChange: (stockCode: string) => void
  value: string
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const selected = STOCKS.find((item) => item.code === value) ?? STOCKS[0]

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', close)
    window.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('mousedown', close)
      window.removeEventListener('keydown', closeOnEscape)
    }
  }, [open])

  if (!selected) return null
  return (
    <div className="ask-stock-picker" ref={rootRef}>
      <button
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label="질문할 종목"
        className={`ask-stock-picker__trigger${attention ? ' stock-select--attention' : ''}`}
        onClick={() => setOpen((current) => !current)}
        ref={buttonRef}
        type="button"
      >
        <StockAvatar imageSrc={selected.imageSrc} initials={selected.initials} size="sm" />
        <strong>{selected.name}</strong>
        <Icon name="chevron-right" size={15} />
      </button>
      {open && (
        <div aria-label="질문할 종목" className="ask-stock-picker__menu" role="listbox">
          {STOCKS.map((stock) => (
            <button
              aria-selected={stock.code === value}
              key={stock.code}
              onClick={() => {
                onChange(stock.code)
                setOpen(false)
              }}
              role="option"
              type="button"
            >
              <StockAvatar imageSrc={stock.imageSrc} initials={stock.initials} size="sm" />
              <span>{stock.name}</span>
              {stock.code === value && <Icon name="check" size={15} />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function AskPage() {
  const [stockCode, setStockCode] = useState(STOCKS[0]?.code ?? '005930')
  const [highlightStockSelect, setHighlightStockSelect] = useState(false)
  const stockSelectRef = useRef<HTMLButtonElement>(null)
  const stock = STOCKS.find((item) => item.code === stockCode) ?? STOCKS[0]
  const handleStockContextError = useCallback((code: StockContextErrorCode | null) => {
    const shouldHighlight = code === 'STOCK_CONTEXT_MISMATCH'
    setHighlightStockSelect(shouldHighlight)
    if (shouldHighlight) stockSelectRef.current?.focus()
  }, [])
  const handleStockChange = useCallback((code: string) => {
    setHighlightStockSelect(false)
    setStockCode(code)
  }, [])

  return (
    <main className="ask-page">
      <section className="global-chat">
        {stock && (
          <RagConversation
            context={{ stockCode: stock.code, stockName: stock.name }}
            contextControl={(
              <StockPicker
                attention={highlightStockSelect}
                buttonRef={stockSelectRef}
                onChange={handleStockChange}
                value={stockCode}
              />
            )}
            emptyTitle={`${stock.name}에 대해 무엇이 궁금한가요?`}
            key={stock.code}
            onStockContextError={handleStockContextError}
            variant="page"
          />
        )}
      </section>
    </main>
  )
}
