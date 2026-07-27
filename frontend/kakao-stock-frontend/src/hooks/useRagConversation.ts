import { useCallback, useEffect, useRef, useState } from 'react'
import {
  normalizeSources,
  normalizeVisualizations,
  QaStreamError,
  stockContextErrorCode,
  streamQa,
} from '../api/qa'
import type {
  QaStreamEvent,
  RagContext,
  RagMessage,
  RagPhase,
  StockContextErrorCode,
} from '../types/qa'

function publicWarnings(value: unknown) {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string').slice(0, 5)
    : []
}

export function useRagConversation(context: RagContext) {
  const [messages, setMessages] = useState<RagMessage[]>([])
  const [phase, setPhase] = useState<RagPhase>('idle')
  const [progress, setProgress] = useState('')
  const [stockContextError, setStockContextError] = useState<StockContextErrorCode | null>(null)
  const activeController = useRef<AbortController | null>(null)
  const lastQuestion = useRef('')

  useEffect(() => () => activeController.current?.abort(), [])

  const updateAssistant = useCallback((id: string, update: (message: RagMessage) => RagMessage) => {
    setMessages((current) => current.map((message) => message.id === id ? update(message) : message))
  }, [])

  const send = useCallback(async (rawQuestion: string) => {
    const question = rawQuestion.trim()
    if (!question) return
    activeController.current?.abort()
    const controller = new AbortController()
    activeController.current = controller
    lastQuestion.current = question
    setStockContextError(null)
    const idBase = `${Date.now()}-${Math.random().toString(36).slice(2)}`
    const assistantId = `${idBase}-assistant`
    setMessages((current) => [
      ...current,
      { id: `${idBase}-user`, role: 'user', text: question, sources: [], visualizations: [], warnings: [] },
      {
        id: assistantId,
        role: 'assistant',
        text: '',
        sources: [],
        visualizations: [],
        warnings: [],
        state: 'pending',
      },
    ])
    setPhase('connecting')
    setProgress('자료 연결 중')

    const handleEvent = (event: QaStreamEvent) => {
      if (event.event === 'agent_start') {
        setPhase('running')
        setProgress('질문에 맞는 자료를 찾는 중')
      } else if (event.event === 'tool_start') {
        // 백엔드는 동기 invoke 완료 후 도구 이벤트를 한꺼번에 내보낸다. 따라서 도구별
        // 라벨을 순서대로 재생하면 실제 진행처럼 보이는 허위 상태가 된다(제한사항).
        // 실제 실시간 스트리밍 전까지는 일반 진행 라벨만 표시한다.
        setPhase('running')
        setProgress('근거 자료 확인 중')
      } else if (event.event === 'sources') {
        updateAssistant(assistantId, (message) => ({
          ...message,
          sources: normalizeSources(event.data.sources),
          visualizations: normalizeVisualizations(event.data.visualizations),
          warnings: publicWarnings(event.data.warnings),
        }))
      } else if (event.event === 'delta') {
        const text = typeof event.data.text === 'string' ? event.data.text : ''
        setPhase('streaming')
        setProgress('답변 작성 중')
        updateAssistant(assistantId, (message) => ({ ...message, text: message.text + text }))
      } else if (event.event === 'done') {
        setPhase('completed')
        setProgress('')
        updateAssistant(assistantId, (message) => ({
          ...message,
          state: 'complete',
          visualizations: message.visualizations.length > 0
            ? message.visualizations
            : normalizeVisualizations(event.data.visualizations),
          warnings: message.warnings.length > 0 ? message.warnings : publicWarnings(event.data.warnings),
        }))
      } else if (event.event === 'error') {
        const reason = event.data.stop_reason
        const code = stockContextErrorCode(event.data.error_code)
        if (code) {
          const safeMessage = typeof event.data.message === 'string'
            ? event.data.message
            : '종목 문맥을 확인할 수 없어 요청을 처리하지 않았습니다.'
          setPhase('completed')
          setProgress('')
          setStockContextError(code)
          updateAssistant(assistantId, (message) => ({
            ...message,
            text: safeMessage,
            sources: [],
            visualizations: [],
            warnings: [],
            state: 'complete',
            errorCode: code,
          }))
          return
        }
        const message = reason === 'timeout'
          ? '답변 시간이 초과됐어요. 같은 질문을 다시 시도해 주세요.'
          : '데이터를 불러오는 중 문제가 발생했습니다.'
        throw new Error(message)
      }
    }

    try {
      await streamQa(question, context, controller.signal, handleEvent)
    } catch (error) {
      if (controller.signal.aborted) {
        setPhase('aborted')
        setProgress('')
        updateAssistant(assistantId, (message) => ({
          ...message,
          text: message.text || '답변 생성을 중단했어요.',
          state: 'aborted',
        }))
      } else {
        setPhase('error')
        setProgress('')
        const errorCode = error instanceof QaStreamError ? error.code : undefined
        setStockContextError(errorCode ?? null)
        updateAssistant(assistantId, (message) => ({
          ...message,
          text: error instanceof Error ? error.message : '데이터를 불러오는 중 문제가 발생했습니다.',
          sources: [],
          visualizations: [],
          warnings: [],
          state: 'error',
          errorCode,
        }))
      }
    } finally {
      if (activeController.current === controller) activeController.current = null
    }
  }, [context, updateAssistant])

  const abort = useCallback(() => activeController.current?.abort(), [])
  const retry = useCallback(() => {
    if (lastQuestion.current) void send(lastQuestion.current)
  }, [send])
  const reset = useCallback(() => {
    activeController.current?.abort()
    setMessages([])
    setPhase('idle')
    setProgress('')
    setStockContextError(null)
  }, [])

  return { abort, messages, phase, progress, reset, retry, send, stockContextError }
}
