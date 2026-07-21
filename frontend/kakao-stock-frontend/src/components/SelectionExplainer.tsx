import { createPortal } from 'react-dom'
import { LoadingDots } from './LoadingDots'
import type { SelectionAnchor } from './selectionAnchor'

function explanationParagraphs(value: string) {
  const explicit = value.split(/\n\s*\n/).map((item) => item.trim()).filter(Boolean)
  if (explicit.length > 1) return explicit.slice(0, 3)
  const sentences = value.replace(/\s+/g, ' ').trim().split(/(?<=[.!?])\s+/).filter(Boolean).slice(0, 3)
  if (sentences.length <= 2) return sentences.length ? [sentences.join(' ')] : []
  return [sentences[0], sentences.slice(1).join(' ')]
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
  return createPortal(
    <div className="selection-explainer" style={{ left: anchor.left, top: anchor.top }}>
      {!showExplanation && (
        <div className={`selection-explainer__actions is-${anchor.horizontal}`}>
          <button onClick={onRequest} onMouseDown={(event) => event.preventDefault()} type="button">설명</button>
          {onAsk && <button onClick={onAsk} onMouseDown={(event) => event.preventDefault()} type="button">AI에게 질문</button>}
        </div>
      )}
      {showExplanation && (
        <section aria-label="선택한 문구 AI 쉬운 설명" className={popoverClass}>
          <header><span>AI 쉬운 설명</span><button aria-label="쉬운 설명 닫기" onClick={onClose} type="button">닫기</button></header>
          <blockquote>“{anchor.text}”</blockquote>
          {isLoading ? <div className="selection-explainer__loading"><LoadingDots label="쉬운 설명 생성 중" /></div> : (
            <div className={error ? 'selection-explainer__answer is-error' : 'selection-explainer__answer'}>
              {explanationParagraphs(explanation || error).map((paragraph, index) => <p key={`${index}:${paragraph}`}>{paragraph}</p>)}
            </div>
          )}
        </section>
      )}
    </div>,
    document.body,
  )
}
