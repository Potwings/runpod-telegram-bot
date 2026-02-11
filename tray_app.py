"""
RunPod Monitor - Windows System Tray Application
시스템 트레이에서 RunPod Monitor Bot을 실행/관리
- 트레이 아이콘 더블클릭: 로그 창 열기
- 창 닫기(X): 트레이로 숨김
- 트레이 메뉴: 시작/중지/재시작/종료
"""

import os
import sys
import subprocess
import threading
import tkinter as tk
import time
from datetime import datetime

import pystray
from PIL import Image, ImageDraw, ImageFont


# 현재 스크립트 디렉토리 기준으로 경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_SCRIPT = os.path.join(BASE_DIR, "runpod_monitor.py")
LOG_FILE = os.path.join(BASE_DIR, "bot.log")
PYTHON_EXE = sys.executable

# 로그 창 갱신 주기 (ms)
LOG_REFRESH_MS = 500


def create_icon_image(running: bool) -> Image.Image:
    """트레이 아이콘 이미지 생성 (실행 중: 초록, 중지: 회색)"""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    color = (76, 175, 80, 255) if running else (158, 158, 158, 255)
    draw.ellipse([4, 4, size - 4, size - 4], fill=color)

    try:
        font = ImageFont.truetype("arial.ttf", 32)
    except (OSError, IOError):
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), "R", font=font)
    tw = bbox[2] - bbox[0]
    tx = (size - tw) // 2
    ty = (size - bbox[3] + bbox[1]) // 2 - bbox[1]
    draw.text((tx, ty), "R", fill=(255, 255, 255, 255), font=font)

    return img


class LogWindow:
    """실시간 로그 뷰어 (tkinter)"""

    def __init__(self, root: tk.Tk, app: "TrayApp"):
        self.root = root
        self.app = app
        self._log_pos = 0  # 로그 파일 읽기 위치
        self._auto_scroll = True

        self._build_ui()
        self._schedule_refresh()

    def _build_ui(self):
        self.root.title("RunPod Monitor")
        self.root.geometry("800x520")
        self.root.configure(bg="#1e1e1e")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 상단 상태 바
        status_frame = tk.Frame(self.root, bg="#2d2d2d", pady=6, padx=10)
        status_frame.pack(fill=tk.X)

        self.status_dot = tk.Label(
            status_frame, text="\u25cf", font=("Segoe UI", 14),
            fg="#9e9e9e", bg="#2d2d2d",
        )
        self.status_dot.pack(side=tk.LEFT)

        self.status_label = tk.Label(
            status_frame, text="  중지됨", font=("Segoe UI", 10),
            fg="#cccccc", bg="#2d2d2d",
        )
        self.status_label.pack(side=tk.LEFT)

        # 버튼들
        btn_style = dict(
            font=("Segoe UI", 9), bg="#3c3c3c", fg="#cccccc",
            activebackground="#505050", activeforeground="#ffffff",
            relief=tk.FLAT, padx=10, pady=2, cursor="hand2",
        )

        self.btn_exit = tk.Button(
            status_frame, text="종료", command=self._on_quit, **btn_style,
        )
        self.btn_exit.pack(side=tk.RIGHT, padx=(4, 0))

        self.btn_restart = tk.Button(
            status_frame, text="재시작",
            command=lambda: threading.Thread(
                target=self.app.restart_bot, daemon=True).start(),
            **btn_style,
        )
        self.btn_restart.pack(side=tk.RIGHT, padx=(4, 0))

        self.btn_toggle = tk.Button(status_frame, **btn_style)
        self.btn_toggle.pack(side=tk.RIGHT, padx=(4, 0))

        self.btn_clear = tk.Button(
            status_frame, text="로그 지우기", command=self._clear_log,
            **btn_style,
        )
        self.btn_clear.pack(side=tk.RIGHT, padx=(4, 0))

        # 로그 텍스트 영역
        text_frame = tk.Frame(self.root, bg="#1e1e1e")
        text_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(4, 6))

        self.scrollbar = tk.Scrollbar(text_frame)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.text = tk.Text(
            text_frame,
            bg="#1e1e1e", fg="#d4d4d4",
            font=("Consolas", 10),
            insertbackground="#d4d4d4",
            selectbackground="#264f78",
            wrap=tk.WORD,
            state=tk.DISABLED,
            yscrollcommand=self._on_scroll_set,
            borderwidth=0, highlightthickness=0,
        )
        self.text.pack(fill=tk.BOTH, expand=True)
        self.scrollbar.config(command=self.text.yview)

        # 텍스트 태그 (색상)
        self.text.tag_configure("info", foreground="#d4d4d4")
        self.text.tag_configure("warn", foreground="#cca700")
        self.text.tag_configure("error", foreground="#f44747")
        self.text.tag_configure("header", foreground="#569cd6")

        self._update_toggle_btn()

    def _on_scroll_set(self, first, last):
        """스크롤바 위치 업데이트 + 자동 스크롤 여부 판단"""
        self.scrollbar.set(first, last)
        # 스크롤이 맨 아래 근처면 자동 스크롤 활성화
        self._auto_scroll = float(last) >= 0.98

    def _clear_log(self):
        """화면의 로그 지우기"""
        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        self.text.config(state=tk.DISABLED)
        # 파일 위치를 현재 끝으로 이동 (이전 내용 다시 안 읽음)
        try:
            self._log_pos = os.path.getsize(LOG_FILE)
        except OSError:
            self._log_pos = 0

    def _schedule_refresh(self):
        """주기적으로 로그 파일 읽기 + 상태 갱신"""
        self._read_new_log()
        self._refresh_status()
        self.root.after(LOG_REFRESH_MS, self._schedule_refresh)

    def _read_new_log(self):
        """로그 파일에서 새 내용 읽어서 텍스트에 추가"""
        if not os.path.exists(LOG_FILE):
            return
        try:
            size = os.path.getsize(LOG_FILE)
            if size < self._log_pos:
                # 파일이 잘렸거나 새로 생성됨
                self._log_pos = 0
            if size == self._log_pos:
                return

            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._log_pos)
                new_text = f.read()
                self._log_pos = f.tell()

            if not new_text:
                return

            self.text.config(state=tk.NORMAL)
            for line in new_text.splitlines(keepends=True):
                tag = "info"
                lower = line.lower()
                if "error" in lower or "critical" in lower:
                    tag = "error"
                elif "warning" in lower:
                    tag = "warn"
                elif line.startswith("="):
                    tag = "header"
                self.text.insert(tk.END, line, tag)

            # 최대 줄 수 제한 (메모리 보호)
            line_count = int(self.text.index("end-1c").split(".")[0])
            if line_count > 5000:
                self.text.delete("1.0", f"{line_count - 4000}.0")

            self.text.config(state=tk.DISABLED)

            if self._auto_scroll:
                self.text.see(tk.END)
        except OSError:
            pass

    def _refresh_status(self):
        """상태 표시 갱신"""
        running = self.app.running
        if running:
            self.status_dot.config(fg="#4caf50")
            self.status_label.config(text="  실행 중")
        else:
            self.status_dot.config(fg="#9e9e9e")
            self.status_label.config(text="  중지됨")
        self._update_toggle_btn()

    def _update_toggle_btn(self):
        """시작/중지 버튼 텍스트 전환"""
        if self.app.running:
            self.btn_toggle.config(
                text="중지",
                command=lambda: threading.Thread(
                    target=self.app.stop_bot, daemon=True).start(),
            )
        else:
            self.btn_toggle.config(
                text="시작",
                command=lambda: threading.Thread(
                    target=self.app.start_bot, daemon=True).start(),
            )

    def show(self):
        """창 보이기"""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide(self):
        """창 숨기기 (트레이로)"""
        self.root.withdraw()

    def _on_close(self):
        """X 버튼 → 트레이로 숨김"""
        self.hide()

    def _on_quit(self):
        """종료 버튼 → 앱 전체 종료"""
        self.app.quit()


class TrayApp:
    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.icon: pystray.Icon | None = None
        self.running = False
        self._lock = threading.Lock()
        self.root: tk.Tk | None = None
        self.log_window: LogWindow | None = None

    def start_bot(self):
        """봇 프로세스 시작"""
        with self._lock:
            if self.process and self.process.poll() is None:
                return

            # 헤더를 UTF-8로 기록
            header = (
                f"\n{'='*50}\n"
                f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Bot 시작\n"
                f"{'='*50}\n"
            )
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(header)

            # stdout을 파이프로 받아서 직접 인코딩 변환
            self.process = subprocess.Popen(
                [PYTHON_EXE, "-u", BOT_SCRIPT],
                cwd=BASE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self.running = True
            self._update_icon()

        # 파이프 → UTF-8 로그 파일 변환 스레드
        threading.Thread(target=self._pipe_to_log, daemon=True).start()
        threading.Thread(target=self._watch_process, daemon=True).start()

    def _pipe_to_log(self):
        """서브프로세스 stdout(바이트)을 읽어서 UTF-8로 로그 파일에 기록"""
        proc = self.process
        if not proc or not proc.stdout:
            return
        with open(LOG_FILE, "a", encoding="utf-8", errors="replace", newline="") as log_f:
            for raw_line in proc.stdout:
                try:
                    line = raw_line.decode("utf-8")
                except UnicodeDecodeError:
                    line = raw_line.decode("cp949", errors="replace")
                log_f.write(line)
                log_f.flush()

    def stop_bot(self):
        """봇 프로세스 종료"""
        with self._lock:
            if not self.process or self.process.poll() is not None:
                self.running = False
                self._update_icon()
                return

            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()

            self.running = False
            self._update_icon()

    def restart_bot(self):
        """봇 재시작"""
        self.stop_bot()
        time.sleep(1)
        self.start_bot()

    def _watch_process(self):
        """프로세스 예기치 않은 종료 감시"""
        if self.process:
            self.process.wait()
            with self._lock:
                if self.running:
                    self.running = False
                    self._update_icon()
                    self._notify("RunPod Monitor", "Bot이 예기치 않게 종료되었습니다.")

    def _update_icon(self):
        if self.icon:
            self.icon.icon = create_icon_image(self.running)
            status = "실행 중" if self.running else "중지됨"
            self.icon.title = f"RunPod Monitor - {status}"

    def _notify(self, title: str, message: str):
        if self.icon:
            try:
                self.icon.notify(message, title)
            except Exception:
                pass

    # ── 트레이 메뉴 콜백 ──

    def _on_show(self, icon, item):
        if self.root:
            self.root.after(0, self.log_window.show)

    def _on_start(self, icon, item):
        threading.Thread(target=self.start_bot, daemon=True).start()

    def _on_stop(self, icon, item):
        threading.Thread(target=self.stop_bot, daemon=True).start()

    def _on_restart(self, icon, item):
        threading.Thread(target=self.restart_bot, daemon=True).start()

    def _on_exit(self, icon, item):
        self.quit()

    def _is_running(self, item) -> bool:
        return self.running

    def _is_stopped(self, item) -> bool:
        return not self.running

    def quit(self):
        """앱 전체 종료"""
        self.stop_bot()
        if self.icon:
            self.icon.stop()
        if self.root:
            self.root.after(0, self.root.destroy)

    # ── 실행 ──

    def run(self):
        """메인 실행: tkinter + pystray"""
        # tkinter 윈도우 생성 (메인 스레드)
        self.root = tk.Tk()
        self.log_window = LogWindow(self.root, self)

        # 트레이 아이콘 (별도 스레드)
        menu = pystray.Menu(
            pystray.MenuItem("열기", self._on_show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("시작", self._on_start, visible=self._is_stopped),
            pystray.MenuItem("중지", self._on_stop, visible=self._is_running),
            pystray.MenuItem("재시작", self._on_restart, visible=self._is_running),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("종료", self._on_exit),
        )

        self.icon = pystray.Icon(
            name="runpod_monitor",
            icon=create_icon_image(False),
            title="RunPod Monitor - 중지됨",
            menu=menu,
        )

        # pystray를 별도 스레드에서 실행
        tray_thread = threading.Thread(target=self.icon.run, daemon=True)
        tray_thread.start()

        # 봇 자동 시작
        threading.Thread(target=self.start_bot, daemon=True).start()

        # tkinter 메인루프
        self.root.mainloop()


def main():
    try:
        import dotenv  # noqa: F401
    except ImportError:
        print("의존성을 설치합니다...")
        subprocess.check_call(
            [PYTHON_EXE, "-m", "pip", "install", "-r",
             os.path.join(BASE_DIR, "requirements.txt")],
        )

    app = TrayApp()
    app.run()


if __name__ == "__main__":
    main()
