"""
RunPod Pod Monitor with Telegram Bot Integration
- 주기적으로 RunPod pod 상태 확인
- pod 존재 시 Telegram 알림
- Telegram 명령어로 pod terminate/stop 가능
"""

import os
import asyncio
import logging
from datetime import datetime

import runpod
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# 환경 변수 로드 (.env 파일에서)
load_dotenv()

# 로깅 설정
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# HTTP 요청 로그 줄이기 (getUpdates 로그 제거)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# 설정 (.env 파일에서 읽어옴)
RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "60"))

# Webhook 설정
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # ngrok URL (예: https://xxxx.ngrok.io)
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8443"))

# 허용된 사용자 ID 목록 (쉼표로 구분, 예: "123456,789012")
ALLOWED_USER_IDS = os.getenv("ALLOWED_USER_IDS", "")

# RunPod API 키 설정
runpod.api_key = RUNPOD_API_KEY


def get_allowed_users() -> set:
    """허용된 사용자 ID 집합 반환"""
    if not ALLOWED_USER_IDS:
        return set()
    return {int(uid.strip()) for uid in ALLOWED_USER_IDS.split(",") if uid.strip()}


def is_authorized(update: Update) -> bool:
    """사용자 권한 확인"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    allowed_users = get_allowed_users()

    # TELEGRAM_CHAT_ID가 설정되어 있으면 해당 채팅방만 허용
    if TELEGRAM_CHAT_ID and str(chat_id) != TELEGRAM_CHAT_ID:
        return False

    # ALLOWED_USER_IDS가 설정되어 있으면 해당 사용자만 허용
    if allowed_users and user_id not in allowed_users:
        return False

    return True


def format_uptime(seconds: int) -> str:
    """업타임을 읽기 쉬운 형식으로 변환"""
    if not seconds:
        return "N/A"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{int(hours)}h {int(minutes)}m {int(secs)}s"


def format_pod_info(pod: dict) -> str:
    """pod 정보를 텍스트로 포맷"""
    runtime = pod.get("runtime") or {}
    uptime = runtime.get("uptimeInSeconds", 0)
    gpu_type = pod.get("gpuTypeId", "N/A")
    cost = pod.get("costPerHr", 0)
    status = pod.get("desiredStatus", "N/A")

    return (
        f"  - ID: `{pod['id']}`\n"
        f"  - 이름: {pod.get('name', 'N/A')}\n"
        f"  - GPU: {gpu_type}\n"
        f"  - 상태: {status}\n"
        f"  - 업타임: {format_uptime(uptime)}\n"
        f"  - 시간당 비용: ${cost:.4f}"
    )


# Telegram Bot 핸들러
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """시작 명령어"""
    if not is_authorized(update):
        logger.warning(f"권한 없는 접근 시도: user_id={update.effective_user.id}")
        await update.message.reply_text("권한이 없습니다.")
        return

    await update.message.reply_text(
        "RunPod Monitor Bot에 오신 것을 환영합니다!\n\n"
        "사용 가능한 명령어:\n"
        "/status - 현재 실행 중인 pod 확인\n"
        "/pods - 모든 pod 목록 확인\n"
        "/terminate - pod 종료 메뉴 (완전 삭제)\n"
        "/stop - pod 정지 메뉴 (스토리지 유지)\n"
        "/help - 도움말"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """도움말 명령어"""
    if not is_authorized(update):
        logger.warning(f"권한 없는 접근 시도: user_id={update.effective_user.id}")
        await update.message.reply_text("권한이 없습니다.")
        return

    await update.message.reply_text(
        "RunPod Monitor Bot 도움말\n\n"
        "/status - 현재 실행 중인 pod 상태 확인\n"
        "/pods - 모든 pod 목록 조회\n"
        "/terminate - pod 완전 삭제 (비용 청구 중단)\n"
        "/stop - pod 정지 (스토리지 유지)\n\n"
        f"자동 체크 주기: {CHECK_INTERVAL_MINUTES}분"
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """실행 중인 pod 상태 확인"""
    if not is_authorized(update):
        logger.warning(f"권한 없는 접근 시도: user_id={update.effective_user.id}")
        await update.message.reply_text("권한이 없습니다.")
        return

    try:
        pods = runpod.get_pods()
        running_pods = [p for p in pods if p.get("desiredStatus") == "RUNNING"]

        if not running_pods:
            await update.message.reply_text("현재 실행 중인 pod이 없습니다.")
            return

        message = f"실행 중인 Pod: {len(running_pods)}개\n\n"
        for pod in running_pods:
            message += format_pod_info(pod) + "\n\n"

        await update.message.reply_text(message, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Status 조회 실패: {e}")
        await update.message.reply_text("오류가 발생했습니다. 잠시 후 다시 시도해주세요.")


async def pods_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """모든 pod 목록 조회"""
    if not is_authorized(update):
        logger.warning(f"권한 없는 접근 시도: user_id={update.effective_user.id}")
        await update.message.reply_text("권한이 없습니다.")
        return

    try:
        pods = runpod.get_pods()

        if not pods:
            await update.message.reply_text("등록된 pod이 없습니다.")
            return

        message = f"전체 Pod 목록: {len(pods)}개\n\n"
        for pod in pods:
            message += format_pod_info(pod) + "\n\n"

        await update.message.reply_text(message, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Pods 조회 실패: {e}")
        await update.message.reply_text("오류가 발생했습니다. 잠시 후 다시 시도해주세요.")


async def terminate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """pod terminate 메뉴"""
    if not is_authorized(update):
        logger.warning(f"권한 없는 접근 시도: user_id={update.effective_user.id}")
        await update.message.reply_text("권한이 없습니다.")
        return

    try:
        pods = runpod.get_pods()

        if not pods:
            await update.message.reply_text("현재 등록된 pod이 없습니다.")
            return

        keyboard = []
        for pod in pods:
            name = pod.get("name", pod["id"][:8])
            status = pod.get("desiredStatus", "")
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"[{status}] {name}",
                        callback_data=f"terminate_{pod['id']}",
                    )
                ]
            )
        keyboard.append([InlineKeyboardButton("취소", callback_data="cancel")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "종료할 pod을 선택하세요 (완전 삭제됨):",
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.error(f"Terminate 메뉴 오류: {e}")
        await update.message.reply_text("오류가 발생했습니다. 잠시 후 다시 시도해주세요.")


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """pod stop 메뉴"""
    if not is_authorized(update):
        logger.warning(f"권한 없는 접근 시도: user_id={update.effective_user.id}")
        await update.message.reply_text("권한이 없습니다.")
        return

    try:
        pods = runpod.get_pods()
        running_pods = [p for p in pods if p.get("desiredStatus") == "RUNNING"]

        if not running_pods:
            await update.message.reply_text("현재 실행 중인 pod이 없습니다.")
            return

        keyboard = []
        for pod in running_pods:
            name = pod.get("name", pod["id"][:8])
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"Stop: {name}",
                        callback_data=f"stop_{pod['id']}",
                    )
                ]
            )
        keyboard.append([InlineKeyboardButton("취소", callback_data="cancel")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "정지할 pod을 선택하세요 (스토리지 유지):",
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.error(f"Stop 메뉴 오류: {e}")
        await update.message.reply_text("오류가 발생했습니다. 잠시 후 다시 시도해주세요.")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """인라인 버튼 콜백 처리"""
    query = update.callback_query
    await query.answer()

    # 콜백에서도 권한 체크
    if not is_authorized(update):
        logger.warning(f"권한 없는 콜백 시도: user_id={update.effective_user.id}")
        await query.edit_message_text("권한이 없습니다.")
        return

    data = query.data

    if data == "cancel":
        await query.edit_message_text("작업이 취소되었습니다.")
        return

    if data.startswith("terminate_"):
        pod_id = data.replace("terminate_", "")

        # pod_id 형식 검증 (영숫자와 하이픈만 허용)
        if not pod_id or not all(c.isalnum() or c == '-' for c in pod_id):
            logger.warning(f"잘못된 pod_id 형식: {pod_id}")
            await query.edit_message_text("잘못된 요청입니다.")
            return

        await query.edit_message_text(f"Pod `{pod_id}` 종료 중...", parse_mode="Markdown")

        try:
            runpod.terminate_pod(pod_id)
            await query.edit_message_text(
                f"Pod `{pod_id}` 가 성공적으로 종료되었습니다.",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Pod terminate 실패: {e}")
            await query.edit_message_text(
                "Pod 종료에 실패했습니다. 잠시 후 다시 시도해주세요.",
                parse_mode="Markdown",
            )

    elif data.startswith("stop_"):
        pod_id = data.replace("stop_", "")

        # pod_id 형식 검증
        if not pod_id or not all(c.isalnum() or c == '-' for c in pod_id):
            logger.warning(f"잘못된 pod_id 형식: {pod_id}")
            await query.edit_message_text("잘못된 요청입니다.")
            return

        await query.edit_message_text(f"Pod `{pod_id}` 정지 중...", parse_mode="Markdown")

        try:
            runpod.stop_pod(pod_id)
            await query.edit_message_text(
                f"Pod `{pod_id}` 가 성공적으로 정지되었습니다.",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Pod stop 실패: {e}")
            await query.edit_message_text(
                "Pod 정지에 실패했습니다. 잠시 후 다시 시도해주세요.",
                parse_mode="Markdown",
            )


async def send_alert(app: Application, message: str):
    """Telegram 알림 전송"""
    try:
        await app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"알림 전송 실패: {e}")


async def check_pods(app: Application):
    """모든 pod 체크 및 알림"""
    logger.info("Pod 상태 체크 중...")

    try:
        pods = runpod.get_pods()

        if pods:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = f"[RunPod 알림] {now}\n\n"
            message += f"존재하는 Pod: {len(pods)}개\n\n"

            # 실행 중인 pod 수 계산
            running_pods = [p for p in pods if p.get("desiredStatus") == "RUNNING"]
            message += f"(실행 중: {len(running_pods)}개)\n\n"

            total_cost = 0
            for pod in pods:
                message += format_pod_info(pod) + "\n\n"
                if pod.get("desiredStatus") == "RUNNING":
                    total_cost += pod.get("costPerHr", 0)

            if running_pods:
                message += f"실행 중인 Pod 시간당 비용: ${total_cost:.4f}\n\n"
            message += "/terminate 또는 /stop 명령으로 관리할 수 있습니다."

            await send_alert(app, message)
            logger.info(f"알림 전송 완료: {len(pods)}개 pod 존재 (실행 중: {len(running_pods)}개)")
        else:
            logger.info("존재하는 pod 없음")

    except Exception as e:
        logger.error(f"Pod 체크 실패: {e}")
        await send_alert(app, f"[오류] Pod 상태 체크 실패: {e}")


async def scheduled_check(app: Application):
    """스케줄된 체크 실행"""
    while True:
        await check_pods(app)
        await asyncio.sleep(CHECK_INTERVAL_MINUTES * 60)


def main():
    """메인 함수"""
    # 설정 검증
    if not RUNPOD_API_KEY:
        raise ValueError("RUNPOD_API_KEY가 설정되지 않았습니다.")
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다.")
    if not TELEGRAM_CHAT_ID:
        raise ValueError("TELEGRAM_CHAT_ID가 설정되지 않았습니다.")

    logger.info("RunPod Monitor Bot 시작...")
    logger.info(f"체크 주기: {CHECK_INTERVAL_MINUTES}분")

    # Telegram Bot 애플리케이션 생성
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # 핸들러 등록
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("pods", pods_command))
    app.add_handler(CommandHandler("terminate", terminate_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CallbackQueryHandler(button_callback))

    # 스케줄된 체크를 위한 job queue 설정
    async def post_init(application: Application):
        """봇 시작 후 초기화"""
        # 시작 알림
        await send_alert(application, "RunPod Monitor Bot이 시작되었습니다.")
        # 스케줄된 체크 시작
        asyncio.create_task(scheduled_check(application))

    app.post_init = post_init

    # Webhook 또는 Polling 모드로 실행
    if WEBHOOK_URL:
        logger.info(f"Bot webhook 시작... (URL: {WEBHOOK_URL})")
        app.run_webhook(
            listen="0.0.0.0",
            port=WEBHOOK_PORT,
            url_path=TELEGRAM_BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}",
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info("Bot polling 시작...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
