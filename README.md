# RunPod Telegram Bot

RunPod GPU Pod를 모니터링하고 관리하기 위한 텔레그램 봇입니다.

## 주요 기능

- **자동 모니터링**: 설정된 주기로 Pod 상태를 확인하고 텔레그램으로 알림
- **원격 관리**: 텔레그램 명령어로 Pod 종료/정지 가능
- **비용 추적**: 실행 중인 Pod의 시간당 비용 표시
- **유연한 실행 모드**: Polling 및 Webhook 모드 지원

## 명령어

| 명령어 | 설명 |
|--------|------|
| `/start` | 봇 시작 및 환영 메시지 |
| `/status` | 실행 중인 Pod 상태 확인 |
| `/pods` | 전체 Pod 목록 조회 |
| `/terminate` | Pod 완전 삭제 (비용 청구 중단) |
| `/stop` | Pod 정지 (스토리지 유지) |
| `/help` | 도움말 |

## 설치 및 실행

### 1. 필수 요구사항

- Python 3.8 이상
- RunPod API Key (GraphQL 권한 필요)
- Telegram Bot Token

### 2. 설치

```bash
git clone https://github.com/Potwings/runpod-telegram-bot.git
cd runpod-telegram-bot
pip install -r requirements.txt
```

### 3. 환경 변수 설정

`.env.example`을 `.env`로 복사한 후 값을 입력합니다.

```bash
cp .env.example .env
```

```env
# 필수 설정
RUNPOD_API_KEY=your_runpod_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# 선택 설정
CHECK_INTERVAL_MINUTES=60
```

### 4. 실행

```bash
python runpod_monitor.py
```

또는 Windows에서:

```bash
start.bat
```

## API Key 발급 방법

### RunPod API Key
1. [RunPod Console](https://www.runpod.io/console/user/settings) 접속
2. API Keys 섹션에서 새 키 생성
3. **GraphQL API 권한 활성화** 필수

### Telegram Bot Token
1. 텔레그램에서 [@BotFather](https://t.me/BotFather) 검색
2. `/newbot` 명령으로 봇 생성
3. 발급된 토큰 복사

### Telegram Chat ID
1. 텔레그램에서 [@userinfobot](https://t.me/userinfobot) 검색
2. 대화 시작하면 Chat ID 확인 가능

## 라이선스

MIT License
