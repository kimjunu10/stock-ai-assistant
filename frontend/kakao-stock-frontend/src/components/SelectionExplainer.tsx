import { useEffect, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from './Icon'
import { LoadingDots } from './LoadingDots'
import type { SelectionAnchor } from './selectionAnchor'

function explanationParagraphs(value: string) {
  const clean = (item: string) => item
    .replace(/^[-•]\s*/, '')
    .replace(/^(뜻|여기서는|쉽게 말하면|핵심은)\s*:\s*/u, '')
    .trim()
  const lines = value.split(/\n+/).map((item) => ({
    isBullet: /^[-•]\s*/.test(item.trim()) && !/^[-•]\s*(뜻|여기서는)\s*:/u.test(item.trim()),
    text: clean(item.trim()),
  })).filter((item) => Boolean(item.text))
  if (lines.length > 1) return lines.slice(0, 2)
  return value
    .replace(/\s+/g, ' ')
    .trim()
    .split(/(?<=[.!?])\s+/)
    .map((item) => ({ isBullet: false, text: clean(item) }))
    .filter((item) => Boolean(item.text))
    .slice(0, 2)
}

interface SelectionExplainerProps {
  anchor: SelectionAnchor
  error: string
  explanation: string
  isLoading: boolean
  onAsk?: () => void
  onClose: () => void
  onRequest: () => void
}

export function SelectionExplainer({ anchor, error, explanation, isLoading, onAsk, onClose, onRequest }: SelectionExplainerProps) {
  const popoverClass = `selection-explainer__popover is-${anchor.horizontal} is-${anchor.vertical}`
  const showExplanation = isLoading || Boolean(explanation) || Boolean(error)
  const positionStyle = {
    '--selection-height': `${anchor.height}px`,
    left: anchor.left,
    top: anchor.top,
  } as CSSProperties

  useEffect(() => {
    if (showExplanation) return
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (event.isComposing || target?.matches('input, textarea, [contenteditable="true"]')) return
      if (event.key.toLowerCase() === 'e') {
        event.preventDefault()
        onRequest()
      } else if (event.key === 'Enter' && onAsk) {
        event.preventDefault()
        onAsk()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onAsk, onRequest, showExplanation])

  return createPortal(
    <div className="selection-explainer" style={positionStyle}>
      {!showExplanation && (
        <div className={`selection-explainer__actions is-${anchor.horizontal} is-${anchor.actionVertical}`}>
          <button onClick={onRequest} onMouseDown={(event) => event.preventDefault()} type="button">
            <span><Icon name="sparkles" size={18} />설명</span><kbd>E</kbd>
          </button>
          {onAsk && (
            <button onClick={onAsk} onMouseDown={(event) => event.preventDefault()} type="button">
              <span><Icon name="message" size={18} />AI에게 질문</span><kbd>Enter</kbd>
            </button>
          )}
        </div>
      )}
      {showExplanation && (
        <section aria-label="선택한 문구 AI 쉬운 설명" className={popoverClass}>
          <header><span>AI 쉬운 설명</span><button aria-label="쉬운 설명 닫기" onClick={onClose} type="button">닫기</button></header>
          <blockquote>“{anchor.text}”</blockquote>
          {isLoading ? <div className="selection-explainer__loading"><LoadingDots label="쉬운 설명 생성 중" /></div> : (
            <div className={error ? 'selection-explainer__answer is-error' : 'selection-explainer__answer'}>
              {explanationParagraphs(explanation || error).map((paragraph, index) => (
                <div className={`selection-explainer__point${paragraph.isBullet && !error ? ' is-bullet' : ''}`} key={`${index}:${paragraph.text}`}>
                  {paragraph.isBullet && !error && <i />}
                  <p>{paragraph.text}</p>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>,
    document.body,
  )
}
