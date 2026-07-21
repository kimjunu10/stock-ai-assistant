interface LoadingDotsProps {
  label?: string
}

export function LoadingDots({ label = '불러오는 중' }: LoadingDotsProps) {
  return (
    <span aria-label={label} className="loading-dots" role="status">
      <i />
      <i />
      <i />
    </span>
  )
}
