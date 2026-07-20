import { useEffect, useRef, useState } from 'react'

const numberFormatter = new Intl.NumberFormat('ko-KR')

interface AnimatedPriceProps {
  fallback?: string
  value: number | null
}

export function AnimatedPrice({ fallback = '—원', value }: AnimatedPriceProps) {
  const [displayed, setDisplayed] = useState(value ?? 0)
  const previousRef = useRef(value ?? 0)

  useEffect(() => {
    if (value === null) return
    const start = previousRef.current
    previousRef.current = value
    if (start === value || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setDisplayed(value)
      return
    }

    const startedAt = performance.now()
    let frameId = 0
    const animate = (now: number) => {
      const progress = Math.min((now - startedAt) / 420, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplayed(Math.round(start + (value - start) * eased))
      if (progress < 1) frameId = requestAnimationFrame(animate)
    }
    frameId = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(frameId)
  }, [value])

  return (
    <strong className="animated-price" key={value ?? 'empty'}>
      {value === null ? fallback : `${numberFormatter.format(displayed)}원`}
    </strong>
  )
}
