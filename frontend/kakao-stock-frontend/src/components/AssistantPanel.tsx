import { getStock } from '../data/mockData'
import type { AssistantContext } from '../types'
import type { RagContext, RagSourceType } from '../types/qa'
import { Icon } from './Icon'
import { RagConversation } from './RagConversation'

interface AssistantPanelProps {
  context: AssistantContext | null
  onClose: () => void
  open: boolean
}

const SOURCE_TYPES: Record<AssistantContext['sourceType'], RagSourceType | undefined> = {
  news_cluster: 'news_event',
  disclosure: 'dart_document',
  report: 'research_report',
  stock: undefined,
}

export function AssistantPanel({ context, onClose, open }: AssistantPanelProps) {
  const stock = context ? getStock(context.stockCode) : undefined
  const dockedToNews = context?.presentation === 'news_detail'
  const ragContext: RagContext = {
    stockCode: context?.stockCode,
    stockName: stock?.name,
    sourceType: context ? SOURCE_TYPES[context.sourceType] : undefined,
    sourceId: context?.sourceId,
    documentId: context?.documentId,
    page: context?.page,
    title: context?.title,
    selectedText: context?.selectedText,
  }

  return (
    <>
      {open && !dockedToNews && <button aria-label="AI 패널 닫기" className="panel-scrim" onClick={onClose} type="button" />}
      <aside aria-hidden={!open} aria-label="문서에 관해 AI에게 질문" className={`assistant-panel${dockedToNews ? ' assistant-panel--news' : ''}${open ? ' is-open' : ''}`}>
        <header className="assistant-panel__header">
          <div>
            <span className="assistant-symbol" aria-hidden="true">M</span>
            <div>
              <strong>Moa AI</strong>
              <span>자료를 찾아 근거와 함께 답해요</span>
            </div>
          </div>
          <button aria-label="패널 닫기" className="icon-button" onClick={onClose} type="button">
            <Icon name="close" size={19} />
          </button>
        </header>
        {context && <RagConversation context={ragContext} key={`${context.sourceType}:${context.sourceId}`} variant="panel" />}
      </aside>
    </>
  )
}
