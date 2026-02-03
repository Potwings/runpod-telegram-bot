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

import httpx
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

# RunPod REST API 설정
RUNPOD_REST_BASE = "https://rest.runpod.io/v1"

# GPU 목록 (PREFERRED_GPUS 환경 변수로 오버라이드 가능)
DEFAULT_GPUS = [
    "NVIDIA RTX A4500",
    "NVIDIA A100 80GB PCIe",
    "NVIDIA A100-SXM4-80GB",
]
_preferred_gpus_env = os.getenv("PREFERRED_GPUS", "")
PREFERRED_GPUS = (
    [g.strip() for g in _preferred_gpus_env.split(",") if g.strip()]
    if _preferred_gpus_env
    else DEFAULT_GPUS
)

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


# --- RunPod REST API 헬퍼 ---
async def runpod_rest_get(endpoint: str) -> dict:
    """RunPod REST API GET 호출"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{RUNPOD_REST_BASE}{endpoint}",
            headers={"Authorization": f"Bearer {RUNPOD_API_KEY}"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


async def runpod_rest_post(endpoint: str, data: dict) -> dict:
    """RunPod REST API POST 호출"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{RUNPOD_REST_BASE}{endpoint}",
            headers={"Authorization": f"Bearer {RUNPOD_API_KEY}"},
            json=data,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_templates() -> list:
    """등록된 템플릿 목록 조회"""
    data = await runpod_rest_get("/templates")
    return data if isinstance(data, list) else []


async def fetch_network_volumes() -> list:
    """네트워크 볼륨 목록 조회"""
    data = await runpod_rest_get("/networkvolumes")
    return data if isinstance(data, list) else []


async def create_pod_api(config: dict) -> dict:
    """Pod 생성 API 호출"""
    return await runpod_rest_post("/pods", config)


def generate_pod_name(template_name: str) -> str:
    """템플릿명+타임스탬프 기반 자동 이름 생성"""
    ts = datetime.now().strftime("%m%d-%H%M")
    safe_name = template_name[:20].replace(" ", "-")
    return f"{safe_name}-{ts}"


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
        "/create - 새 pod 생성\n"
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
        "/create - 새 pod 생성 (템플릿/볼륨/GPU 선택)\n"
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


async def create_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/create - Pod 생성 시작 (Step 1: 템플릿 선택)"""
    if not is_authorized(update):
        logger.warning(f"권한 없는 접근 시도: user_id={update.effective_user.id}")
        await update.message.reply_text("권한이 없습니다.")
        return

    try:
        templates = await fetch_templates()

        if not templates:
            await update.message.reply_text("등록된 템플릿이 없습니다.")
            return

        keyboard = []
        for tpl in templates:
            tpl_id = tpl.get("id", "")
            tpl_name = tpl.get("name", tpl_id[:8])
            keyboard.append(
                [InlineKeyboardButton(tpl_name, callback_data=f"crtpl_{tpl_id}")]
            )
        keyboard.append([InlineKeyboardButton("취소", callback_data="cancel")])

        # 상태 초기화 (템플릿 데이터 캐시)
        context.user_data["create_pod"] = {
            "_templates": {t.get("id"): t for t in templates},
        }

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Pod 생성 - 템플릿을 선택하세요:",
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.error(f"Create 메뉴 오류: {e}")
        await update.message.reply_text(
            "템플릿 목록을 가져오는 데 실패했습니다. 잠시 후 다시 시도해주세요."
        )


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
        context.user_data.pop("create_pod", None)
        await query.edit_message_text("작업이 취소되었습니다.")
        return

    # --- Pod 생성 플로우 콜백 ---
    if data.startswith("crtpl_"):
        # Step 2: 템플릿 선택 → 네트워크 볼륨 선택
        template_id = data[len("crtpl_"):]
        try:
            state = context.user_data.get("create_pod", {})
            cached_templates = state.get("_templates", {})
            tpl = cached_templates.get(template_id)
            if not tpl:
                await query.edit_message_text("선택한 템플릿을 찾을 수 없습니다.")
                return

            state.update({
                "template_id": template_id,
                "template_name": tpl.get("name", template_id[:8]),
                "image_name": tpl.get("imageName", ""),
                "docker_args": tpl.get("dockerArgs", ""),
                "container_disk": tpl.get("containerDiskInGb", 50),
                "ports": tpl.get("ports", "8888/http,22/tcp"),
            })
            # 템플릿 캐시 정리
            state.pop("_templates", None)

            volumes = await fetch_network_volumes()
            if volumes:
                # 볼륨 데이터 캐시
                state["_volumes"] = {v.get("id"): v for v in volumes}
                keyboard = []
                for vol in volumes:
                    vol_id = vol.get("id", "")
                    vol_name = vol.get("name", vol_id[:8])
                    vol_size = vol.get("size", 0)
                    dc = vol.get("dataCenterId", "?")
                    keyboard.append(
                        [InlineKeyboardButton(
                            f"{vol_name} ({vol_size}GB, {dc})",
                            callback_data=f"crvol_{vol_id}",
                        )]
                    )
                keyboard.append(
                    [InlineKeyboardButton("볼륨 없이 생성", callback_data="crvol_none")]
                )
                keyboard.append([InlineKeyboardButton("취소", callback_data="cancel")])
                await query.edit_message_text(
                    f"템플릿: {tpl.get('name', template_id[:8])}\n\n"
                    "네트워크 볼륨을 선택하세요 (선택사항):",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
            else:
                # 볼륨이 없으면 바로 GPU 선택으로
                context.user_data["create_pod"]["volume_id"] = None
                keyboard = []
                for i, gpu in enumerate(PREFERRED_GPUS):
                    keyboard.append(
                        [InlineKeyboardButton(gpu, callback_data=f"crgpu_{i}")]
                    )
                keyboard.append([InlineKeyboardButton("취소", callback_data="cancel")])
                await query.edit_message_text(
                    f"템플릿: {tpl.get('name', template_id[:8])}\n"
                    "볼륨: 없음\n\n"
                    "GPU를 선택하세요:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
        except Exception as e:
            logger.error(f"템플릿 선택 처리 오류: {e}")
            await query.edit_message_text("오류가 발생했습니다. 다시 시도해주세요.")
        return

    if data.startswith("crvol_"):
        # Step 3: 볼륨 선택 → GPU 선택
        state = context.user_data.get("create_pod")
        if not state:
            await query.edit_message_text("세션이 만료되었습니다. /create로 다시 시작해주세요.")
            return

        vol_part = data[len("crvol_"):]
        if vol_part == "none":
            state["volume_id"] = None
            vol_display = "없음"
        else:
            state["volume_id"] = vol_part
            cached_volumes = state.get("_volumes", {})
            vol = cached_volumes.get(vol_part)
            vol_display = vol.get("name", vol_part[:8]) if vol else vol_part[:8]
            if vol and vol.get("dataCenterId"):
                state["data_center_id"] = vol["dataCenterId"]

        # 볼륨 캐시 정리
        state.pop("_volumes", None)

        keyboard = []
        for i, gpu in enumerate(PREFERRED_GPUS):
            keyboard.append(
                [InlineKeyboardButton(gpu, callback_data=f"crgpu_{i}")]
            )
        keyboard.append([InlineKeyboardButton("취소", callback_data="cancel")])
        await query.edit_message_text(
            f"템플릿: {state['template_name']}\n"
            f"볼륨: {vol_display}\n\n"
            "GPU를 선택하세요:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith("crgpu_"):
        # Step 4: GPU 선택 → 확인 화면
        state = context.user_data.get("create_pod")
        if not state:
            await query.edit_message_text("세션이 만료되었습니다. /create로 다시 시작해주세요.")
            return

        try:
            gpu_index = int(data[len("crgpu_"):])
        except ValueError:
            await query.edit_message_text("잘못된 GPU 선택입니다.")
            return
        if gpu_index < 0 or gpu_index >= len(PREFERRED_GPUS):
            await query.edit_message_text("잘못된 GPU 선택입니다.")
            return

        state["gpu_type"] = PREFERRED_GPUS[gpu_index]

        pod_name = generate_pod_name(state["template_name"])
        state["pod_name"] = pod_name

        vol_display = "없음"
        if state.get("volume_id"):
            vol_display = state["volume_id"][:12] + "..."

        summary = (
            f"Pod 생성 확인\n\n"
            f"이름: {pod_name}\n"
            f"템플릿: {state['template_name']}\n"
            f"GPU: {state['gpu_type']}\n"
            f"네트워크 볼륨: {vol_display}\n"
            f"컨테이너 디스크: {state.get('container_disk', 50)}GB\n"
            f"포트: {state.get('ports', '8888/http,22/tcp')}\n\n"
            "생성하시겠습니까?"
        )

        keyboard = [
            [InlineKeyboardButton("생성", callback_data="crconfirm")],
            [InlineKeyboardButton("취소", callback_data="cancel")],
        ]
        await query.edit_message_text(
            summary,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data == "crconfirm":
        # Step 5: Pod 생성 실행
        state = context.user_data.pop("create_pod", None)
        if not state:
            await query.edit_message_text("세션이 만료되었습니다. /create로 다시 시작해주세요.")
            return

        await query.edit_message_text(
            f"Pod 생성 중... ({state['gpu_type']})"
        )

        # ports를 배열로 변환 (API는 배열 형식 요구)
        ports_raw = state.get("ports", "8888/http,22/tcp")
        if isinstance(ports_raw, str):
            ports_list = [p.strip() for p in ports_raw.split(",") if p.strip()]
        else:
            ports_list = ports_raw

        config = {
            "name": state["pod_name"],
            "imageName": state.get("image_name", ""),
            "gpuTypeIds": [state["gpu_type"]],
            "gpuCount": 1,
            "containerDiskInGb": state.get("container_disk", 50),
            "ports": ports_list,
            "templateId": state["template_id"],
        }
        if state.get("docker_args"):
            docker_args = state["docker_args"]
            if isinstance(docker_args, str):
                config["dockerStartCmd"] = docker_args.split()
            elif isinstance(docker_args, list):
                config["dockerStartCmd"] = docker_args
        if state.get("volume_id"):
            config["networkVolumeId"] = state["volume_id"]
            config["volumeInGb"] = 0
            if state.get("data_center_id"):
                config["dataCenterIds"] = [state["data_center_id"]]
        else:
            config["volumeInGb"] = 20

        try:
            result = await create_pod_api(config)
            pod_id = result.get("id", "N/A")
            await query.edit_message_text(
                f"Pod이 성공적으로 생성되었습니다!\n\n"
                f"ID: `{pod_id}`\n"
                f"이름: {state['pod_name']}\n"
                f"GPU: {state['gpu_type']}\n\n"
                "/status 명령으로 상태를 확인하세요.",
                parse_mode="Markdown",
            )
        except httpx.HTTPStatusError as e:
            logger.error(f"Pod 생성 API 오류: {e.response.status_code} - {e.response.text}")
            error_detail = e.response.text[:200]
            try:
                err_body = e.response.json()
                err_field = err_body.get("error", "")
                if isinstance(err_field, dict):
                    error_detail = err_field.get("message", error_detail)
                elif isinstance(err_field, str) and err_field:
                    error_detail = err_field
            except Exception:
                pass
            await query.edit_message_text(
                f"Pod 생성에 실패했습니다.\n\n오류: {error_detail}"
            )
        except Exception as e:
            logger.error(f"Pod 생성 실패: {e}")
            await query.edit_message_text(
                "Pod 생성에 실패했습니다. 잠시 후 다시 시도해주세요."
            )
        return

    if data.startswith("terminate_"):
        pod_id = data[len("terminate_"):]

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
        pod_id = data[len("stop_"):]

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
    app.add_handler(CommandHandler("create", create_command))
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
