# GCP Compute Engine 배포 체크리스트

이 프로젝트는 `main` 브랜치의 CI가 성공하면 GitHub Actions가 백엔드 Docker
이미지를 GHCR에 올리고 Compute Engine VM의 컨테이너를 교체한다. VM 안에서
FastAPI와 APScheduler가 계속 실행되므로 개발용 노트북은 켜 둘 필요가 없다.

## 사용자가 한 번만 준비할 항목

### 1. Compute Engine VM

- 리전: `asia-northeast3` (서울)
- OS: Ubuntu 24.04 LTS, x86/64
- 권장 시작 사양: `e2-standard-2` (2 vCPU, 8 GB 메모리)
- 부팅 디스크: Balanced persistent disk 50 GB 이상
- 외부 IP: 고정 외부 IP로 승격
- 방화벽: SSH용 TCP 22 허용
- API를 외부에서 사용할 경우에만 TCP 8000 허용

BGE-M3 임베딩에서 메모리 부족이 발생하면 `e2-standard-4`로 올린다.

### 2. VM에 Docker 설치

VM의 SSH 터미널에서 실행한다.

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2 curl
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
exit
```

SSH로 다시 접속한 뒤 확인한다.

```bash
docker --version
docker compose version
docker run --rm hello-world
```

### 3. VM에 운영 환경변수 등록

VM에서 `/opt/stock-ai-assistant/.env`를 만든다. 이 파일은 GitHub에 올리지 않는다.

```bash
sudo install -d -o "$USER" -g "$USER" /opt/stock-ai-assistant
nano /opt/stock-ai-assistant/.env
chmod 600 /opt/stock-ai-assistant/.env
```

최소 필수 값은 다음과 같다.

```dotenv
APP_ENV=production
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=
UPSTAGE_API_KEY=
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
USE_LLM_ASSIGN=true
NEWS_SCHEDULER_ENABLED=true
NEWS_SCHEDULER_INTERVAL_MINUTES=30
NEWS_SCHEDULER_MAX_PER_STOCK=100
NEWS_EMBEDDING_DEVICE=cpu
```

DART와 토스 기능도 서버에서 호출한다면 아래 값도 추가한다.

```dotenv
DART_API_KEY=
TOSS_CLIENT_ID=
TOSS_CLIENT_SECRET=
```

### 4. CD 전용 SSH 키

로컬 Mac에서 전용 키를 만든다.

```bash
ssh-keygen -t ed25519 -C "github-actions-stock-deploy" -f ~/.ssh/stock_cd
```

`stock_cd.pub`의 공개키를 Compute Engine VM 사용자의
`~/.ssh/authorized_keys`에 추가한다. 비공개키 `stock_cd`의 전체 내용은 GitHub
Secret에만 저장한다.

### 5. GitHub Actions Secrets

GitHub 저장소의 `Settings > Environments > New environment`에서 `production`을
만들고, 그 환경의 Secrets에 아래 3개를 등록한다.

| Secret | 값 |
| --- | --- |
| `GCP_VM_HOST` | VM의 고정 외부 IP |
| `GCP_VM_USER` | VM에서 `whoami`로 확인한 사용자명 |
| `GCP_VM_SSH_KEY` | `~/.ssh/stock_cd` 비공개키 전체 내용 |

### 6. 첫 배포

PR을 `main`에 머지한다. PR 단계에서는 CI만 실행되고, 머지된 `main`의 CI가
성공해야 CD가 실행된다.

배포 후 VM에서 확인한다.

```bash
cd /opt/stock-ai-assistant
docker compose ps
docker compose logs -f backend
```

로그에 `News scheduler started interval_minutes=30`이 표시되면 서버의 30분
크롤링 스케줄이 시작된 것이다.

## 운영 중 자주 쓰는 명령

```bash
cd /opt/stock-ai-assistant
docker compose ps
docker compose logs --tail=200 backend
docker compose restart backend
```

API 포트를 외부에 열었다면 아래 주소에서 확인할 수 있다.

```text
http://VM_고정_외부_IP:8000/docs
```
