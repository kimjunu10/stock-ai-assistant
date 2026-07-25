import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
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
})
