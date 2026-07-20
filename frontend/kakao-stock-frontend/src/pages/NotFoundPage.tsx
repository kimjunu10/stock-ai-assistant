import { AppLink, type Navigate } from '../components/AppLink'
import { Icon } from '../components/Icon'

interface NotFoundPageProps {
  onNavigate: Navigate
}

export function NotFoundPage({ onNavigate }: NotFoundPageProps) {
  return (
    <main className="not-found shell">
      <span>404</span>
      <h1>페이지를 찾을 수 없어요.</h1>
      <p>주소를 다시 확인하거나 홈에서 원하는 정보를 찾아보세요.</p>
      <AppLink className="primary-button" href="/" onNavigate={onNavigate}>홈으로 가기 <Icon name="arrow-right" size={17} /></AppLink>
    </main>
  )
}
