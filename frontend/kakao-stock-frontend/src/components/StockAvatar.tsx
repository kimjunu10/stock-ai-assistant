interface StockAvatarProps {
  initials: string
  imageSrc?: string
  size?: 'sm' | 'md' | 'lg'
}

export function StockAvatar({ imageSrc, initials, size = 'md' }: StockAvatarProps) {
  return (
    <span aria-hidden="true" className={`stock-avatar stock-avatar--${size}`}>
      {imageSrc ? <img alt="" src={imageSrc} /> : initials}
    </span>
  )
}
