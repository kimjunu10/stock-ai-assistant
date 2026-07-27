import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'
import { useRagConversation } from '../hooks/useRagConversation'
import type { RagContext, StockContextErrorCode } from '../types/qa'
import { Icon } from './Icon'
import { RagAnswer } from './RagAnswer'
import { RagSources } from './RagSources'
import { RagVisualizations } from './RagVisualizations'

interface RagConversationProps {
  context: RagContext
  contextControl?: ReactNode
  emptyTitle?: string
  variant: 'page' | 'panel'
  onStockContextError?: (code: StockContextErrorCode | null) => void
}

function contextLabel(context: RagContext) {
  const stock = context.stockName ?? context.stockCode
  if (context.sourceType === 'news_event') return `${stock ? `${stock} · ` : ''}현재 뉴스 기준`
  if (context.sourceType === 'dart_document' || context.sourceType === 'structured_disclosure') return `${stock ? `${stock} · ` : ''}현재 공시 기준`
  if (context.sourceType === 'research_report') return `${stock ? `${stock} · ` : ''}현재 리포트${context.page ? ` ${context.page}페이지` : ''} 기준`
  return stock ? `${stock} 기준` : '전체 자료 기준'
}

function RagLoadingState({ label }: { label: string }) {
  return (
    <div className="rag-loading-state" role="status">
      <span aria-hidden="true" className="rag-loading-state__dots">
        <i />
        <i />
        <i />
      </span>
      <span>{label || '답변을 준비하고 있어요'}</span>
    </div>
  )
}

export function RagConversation({
  context,
  contextControl,
  emptyTitle,
  variant,
  onStockContextError,
}: RagConversationProps) {
  const [input, setInput] = useState(context.selectedText ?? '')
  const { abort, messages, phase, progress, retry, send, stockContextError } = useRagConversation(context)
  const scrollRef = useRef<HTMLDivElement>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const lastUserRef = useRef<HTMLElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const active = phase === 'connecting' || phase === 'running' || phase === 'streaming'

  useEffect(() => {
    if (!context.selectedText) return
    setInput(context.selectedText)
    const frame = window.requestAnimationFrame(() => {
      const inputElement = inputRef.current
      if (!inputElement) return
      inputElement.focus()
      inputElement.setSelectionRange(inputElement.value.length, inputElement.value.length)
    })
    return () => window.cancelAnimationFrame(frame)
  }, [context.selectedText])

  useEffect(() => {
    onStockContextError?.(stockContextError)
  }, [onStockContextError, stockContextError])

  useEffect(() => {
    if (messages.length > 0) {
      const frame = window.requestAnimationFrame(() => {
        endRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
      })
      return () => window.cancelAnimationFrame(frame)
    }
  }, [messages.length])

  useEffect(() => {
    if (phase !== 'streaming' && phase !== 'completed') return
    const frame = window.requestAnimationFrame(() => {
      lastUserRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [phase])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!input.trim() || active) return
    void send(input)
    setInput('')
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  return (
    <div className={`rag-conversation rag-conversation--${variant}${messages.length === 0 ? ' is-empty' : ' is-active'}`}>
      <div aria-live="polite" className="rag-thread" ref={scrollRef}>
        {variant === 'panel' && <div className="rag-context-badge"><span>{contextLabel(context)}</span></div>}
        {context.title && <div className="rag-context-title"><strong>{context.title}</strong>{context.selectedText && <q>{context.selectedText}</q>}</div>}

        {messages.length === 0 ? (
          <div className="rag-empty">
            <h1>{emptyTitle ?? `${context.stockName ?? '선택한 종목'}에 대해 무엇이 궁금한가요?`}</h1>
            <p>주가 흐름부터 뉴스, 공시, 증권사 리포트까지 근거와 함께 확인해 보세요.</p>
          </div>
        ) : (
          <div className="rag-messages">
            {messages.map((message, index) => (
              <article
                className={`rag-message rag-message--${message.role}${message.state ? ` is-${message.state}` : ''}`}
                key={message.id}
                ref={message.role === 'user' && index === messages.length - 2 ? lastUserRef : undefined}
              >
                <div>
                  {message.text
                    ? message.role === 'assistant' ? <RagAnswer text={message.text} /> : <p>{message.text}</p>
                    : message.state === 'pending' && <RagLoadingState label={progress} />}
                  {message.role === 'assistant' && <RagVisualizations sources={message.sources} visualizations={message.visualizations} />}
                  {message.role === 'assistant' && <RagSources sources={message.sources.filter((source) => !message.visualizations.some(
                    (visualization) => visualization.type === 'news_cards' && visualization.sourceIds.includes(source.sourceId),
                  ))} stockCode={context.stockCode} />}
                  {message.warnings.length > 0 && <div className="rag-warnings">{message.warnings.map((warning) => <p key={warning}><Icon name="info" size={13} />{warning}</p>)}</div>}
                  {(message.state === 'aborted' || (message.state === 'error' && !message.errorCode)) && <button className="rag-retry" onClick={retry} type="button"><Icon name="refresh" size={14} /> 다시 시도</button>}
                </div>
              </article>
            ))}
          </div>
        )}
        <div aria-hidden="true" className="rag-thread-end" ref={endRef} />
      </div>

      <form className="rag-composer" onSubmit={submit}>
        <div>
          {contextControl}
          <textarea
            aria-label={`${context.stockName ?? context.stockCode ?? ''} AI 질문 입력`}
            disabled={active}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="AI에게 질문해 보세요"
            ref={inputRef}
            rows={1}
            value={input}
          />
          {active
            ? <button aria-label="답변 생성 중단" className="rag-stop" onClick={abort} type="button"><span /></button>
            : <button aria-label="질문 보내기" disabled={!input.trim()} type="submit"><Icon name="send" size={17} /></button>}
        </div>
      </form>
    </div>
  )
}
