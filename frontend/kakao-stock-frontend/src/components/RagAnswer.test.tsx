import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { cleanPublicText } from '../utils/publicText'
import { RagAnswer } from './RagAnswer'

describe('RagAnswer', () => {
  it('turns numbered prose into a semantic list without rendering HTML', () => {
    render(<RagAnswer text={'핵심만 정리하면 다음과 같습니다.\n\n1. 첫 번째 소식\n2. <script>alert(1)</script>'} />)
    expect(screen.getByText('핵심만 정리하면 다음과 같습니다.')).toBeTruthy()
    expect(screen.getByRole('list').tagName).toBe('OL')
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByText('<script>alert(1)</script>')).toBeTruthy()
    expect(document.querySelector('script')).toBeNull()
  })

  it('removes internal data labels from public copy', () => {
    expect(cleanPublicText('연결 · actual_value / forecast_value')).toBe('연결 · 실제 실적 / 전망')
  })

  it('removes internal source ids from answer copy', () => {
    expect(cleanPublicText('협약을 체결했습니다. (출처: news_cluster:7104)')).toBe('협약을 체결했습니다.')
  })
})
