import subprocess
"""
flow_runner.py  —— Part 1: 底层引擎
包含：
  - RecorderEngine   : 鼠标轨迹/点击/滚轮完整录制
  - PlaybackEngine   : 脚本回放（原始时间戳 + 随机抖动）
  - StepExecutor     : 11种步骤类型的执行逻辑
  - FlowEngine       : 流程状态机（Part 2 会扩展）

依赖：
  pip install pyautogui pynput pillow pywin32 opencv-python numpy
  PaddleOCR-json.exe（可选，用于OCR步骤）

  本文件可独立测试，也可被 flow_runner_p2/p3 import
"""

import sys, os, time, json, copy, threading, random, logging
import tkinter as tk
from tkinter import messagebox

# ── 日志 ─────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_LOG_DIR    = os.path.join(_SCRIPT_DIR, "log")
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE   = os.path.join(_LOG_DIR, f"flow_runner_{time.strftime('%Y%m%d_%H%M%S')}.log")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("flow_runner")

# ── 依赖检查 ─────────────────────────────────────────────
MISSING = []
try:
    import pyautogui
    pyautogui.FAILSAFE = False
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False; MISSING.append("pyautogui")

try:
    from pynput import mouse as _pynput_mouse
    from pynput import keyboard as _pynput_keyboard
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False; MISSING.append("pynput")

try:
    from PIL import Image, ImageGrab
    HAS_PIL = True
except ImportError:
    HAS_PIL = False; MISSING.append("Pillow")

try:
    import win32gui, win32con, win32api, win32ui
    import ctypes
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False; MISSING.append("pywin32")

try:
    import cv2, numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

# ── 复用 bg_ocr_click 底层（如果在同目录） ───────────────
_BG_OCR_PATH = os.path.join(_SCRIPT_DIR, "bg_ocr_click.py")
_bg = None
if os.path.exists(_BG_OCR_PATH):
    try:
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location("bg_ocr_click", _BG_OCR_PATH)
        _bg   = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_bg)
        log.info("成功 import bg_ocr_click 底层模块")
    except Exception as e:
        log.warning(f"import bg_ocr_click 失败: {e}，将使用内联实现")
        _bg = None


# ══════════════════════════════════════════════════════════
#  截图工具
# ══════════════════════════════════════════════════════════

def _do_screenshot(region=None):
    """
    普通截图（ImageGrab）：region=(x1,y1,x2,y2) 屏幕绝对坐标，None=全屏
    返回 PIL Image 或 None
    """
    try:
        img = ImageGrab.grab(all_screens=True)
        if region:
            img = img.crop(region)
        return img
    except Exception as e:
        log.error(f"截图失败: {e}")
        return None


def _do_screenshot_blt(region=None):
    """
    BitBlt 截图：直接从屏幕 DC 读取，与 PrintWindow 行为一致，
    兼容全屏/独占模式比 ImageGrab 更可靠。
    region=(x1,y1,x2,y2)，None=全屏
    返回 PIL Image 或 None
    """
    if not HAS_WIN32:
        return _do_screenshot(region)
    try:
        if region:
            x1, y1, x2, y2 = region
            w, h = x2 - x1, y2 - y1
        else:
            x1, y1 = 0, 0
            # 多显示器支持
            w = win32api.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
            h = win32api.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN
            if w <= 0 or h <= 0:
                w = win32api.GetSystemMetrics(0)
                h = win32api.GetSystemMetrics(1)

        hwnd_desk = win32gui.GetDesktopWindow()
        hdc_desk  = win32gui.GetWindowDC(hwnd_desk)
        dc_obj    = win32ui.CreateDCFromHandle(hdc_desk)
        mem_dc    = dc_obj.CreateCompatibleDC()
        bmp       = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(dc_obj, w, h)
        mem_dc.SelectObject(bmp)
        # BitBlt 从屏幕 DC 拷贝
        mem_dc.BitBlt((0, 0), (w, h), dc_obj, (x1, y1), win32con.SRCCOPY)

        bmp_info = bmp.GetInfo()
        raw = bmp.GetBitmapBits(True)

        img = Image.frombuffer(
            "RGB",
            (bmp_info["bmWidth"], bmp_info["bmHeight"]),
            raw, "raw", "BGRX", 0, 1
        )

        mem_dc.DeleteDC()
        dc_obj.DeleteDC()
        win32gui.ReleaseDC(hwnd_desk, hdc_desk)
        win32gui.DeleteObject(bmp.GetHandle())
        return img
    except Exception as e:
        log.error(f"BitBlt截图失败: {e}，fallback ImageGrab")
        return _do_screenshot(region)


def _do_ocr(img, engine="paddle", lang="chi_sim", tess_path="", psm=6,
            scale=2, contrast=1.5, binarize=True, threshold=128, invert=False):
    """
    OCR识别，返回文本字符串或None
    优先使用 bg_ocr_click 的实现
    """
    try:
        scale = int(scale)
    except (ValueError, TypeError):
        scale = 1
    if _bg:
        try:
            if scale > 1:
                w, h = img.size
                img = img.resize((w * scale, h * scale), Image.LANCZOS)
            text = _bg.do_ocr_text(img, engine=engine, lang=lang,
                                   tess_path=tess_path, psm=psm)
            return text
        except Exception as e:
            log.error(f"OCR(bg_ocr_click)失败: {e}")
            return None
    else:
        try:
            import pytesseract
            from PIL import ImageEnhance, ImageFilter
            if scale > 1:
                w, h = img.size
                img = img.resize((w * scale, h * scale), Image.LANCZOS)
            img = img.convert('L')
            if invert:
                img = img.point(lambda p: 255 - p)
            if contrast != 1.0:
                img = ImageEnhance.Contrast(img).enhance(contrast)
            img = img.filter(ImageFilter.SHARPEN)
            if binarize:
                img = img.point(lambda p: 255 if p > threshold else 0)
            if tess_path and os.path.exists(tess_path):
                pytesseract.pytesseract.tesseract_cmd = tess_path
            return pytesseract.image_to_string(
                img, lang=lang, config=f"--psm {psm} --oem 3")
        except Exception as e:
            log.error(f"OCR(内联tesseract)失败: {e}")
            return None


def _match_keywords(text, kw_str):
    """
    复用 bg_ocr_click 的关键词匹配逻辑
    | = OR，, = AND
    返回 (matched: bool, first_kw: str)
    """
    if _bg:
        return _bg.match_keywords(text, kw_str)
    if not text or not kw_str.strip():
        return False, ""
    text_nsp = text.replace(" ", "")
    for group in kw_str.split("|"):
        kws = [k.strip() for k in group.split(",") if k.strip()]
        if not kws:
            continue
        if all(k in text or k in text_nsp for k in kws):
            return True, kws[0]
    return False, ""


def _img_match_template(screen_img, template_path, threshold=0.8):
    """
    模板匹配。
    screen_img: PIL Image（待搜索的屏幕区域）
    template_path: 模板图片路径
    threshold: 0.0~1.0
    返回 (matched: bool, cx: int, cy: int) — cx/cy 是匹配区域中心点（相对 screen_img）
    """
    if not HAS_CV2:
        log.error("cv2 未安装，无法使用截图识别步骤")
        return False, 0, 0
    if not template_path or not os.path.exists(template_path):
        log.error(f"模板文件不存在: {template_path}")
        return False, 0, 0
    try:
        # screen
        screen_np = cv2.cvtColor(np.array(screen_img), cv2.COLOR_RGB2BGR)
        # template
        tmpl_np = cv2.imdecode(
            np.frombuffer(open(template_path, "rb").read(), np.uint8),
            cv2.IMREAD_COLOR
        )
        if tmpl_np is None:
            log.error(f"模板图片读取失败: {template_path}")
            return False, 0, 0

        result = cv2.matchTemplate(screen_np, tmpl_np, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        log.debug(f"模板匹配得分: {max_val:.3f} 阈值: {threshold:.3f}")

        if max_val >= threshold:
            th, tw = tmpl_np.shape[:2]
            cx = max_loc[0] + tw // 2
            cy = max_loc[1] + th // 2
            return True, cx, cy
        return False, 0, 0
    except Exception as e:
        log.error(f"模板匹配异常: {e}")
        return False, 0, 0


# ══════════════════════════════════════════════════════════
#  点击序列工具
# ══════════════════════════════════════════════════════════

# click_actions 列表元素默认结构
CLICK_ACTION_DEFAULT = {
    "pre_delay":  0.0,           # 前置等待秒数
    "pos_mode":   "match_center",# match_center | offset | abs
    "offset_x":   0,
    "offset_y":   0,
    "abs_x":      0,
    "abs_y":      0,
    "count":      1,             # 点击次数
    "interval":   0.1,           # 多次点击间隔
    "click_type": "single",      # single | double | right
}


def make_click_action():
    return copy.deepcopy(CLICK_ACTION_DEFAULT)


def _resolve_click_pos(action, match_pos):
    """
    根据 action.pos_mode 和 match_pos（识别位置绝对屏幕坐标 or None）
    计算最终点击坐标。
    返回 (x, y) 或 None（无法确定坐标时）
    """
    mode = action.get("pos_mode", "match_center")
    if mode == "match_center":
        return match_pos  # 可能为 None
    elif mode == "offset":
        if match_pos is None:
            return None
        ox = int(action.get("offset_x", 0))
        oy = int(action.get("offset_y", 0))
        return (match_pos[0] + ox, match_pos[1] + oy)
    elif mode == "abs":
        return (int(action.get("abs_x", 0)), int(action.get("abs_y", 0)))
    return match_pos


# ══════════════════════════════════════════════════════════
#  录制引擎
# ══════════════════════════════════════════════════════════

class RecorderEngine:
    """
    完整录制鼠标轨迹/点击/滚轮。
    pynput 监听，事件带时间戳写入列表。
    """

    def __init__(self):
        self._events = []
        self._recording = False
        self._mouse_listener   = None
        self._t_start = 0.0
        self._lock = threading.Lock()
        self._filter_key = None

    def start(self):
        if not HAS_PYNPUT:
            raise RuntimeError("缺少依赖 pynput，请 pip install pynput")
        with self._lock:
            self._events.clear()
            self._recording = True
            self._t_start   = time.time()

        self._mouse_listener = _pynput_mouse.Listener(
            on_move   = self._on_move,
            on_click  = self._on_click,
            on_scroll = self._on_scroll,
        )
        self._mouse_listener.start()
        log.info("录制开始")

    def stop(self):
        with self._lock:
            self._recording = False
        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener = None
        log.info(f"录制结束，共 {len(self._events)} 个事件")
        return copy.deepcopy(self._events)

    def get_events(self):
        return copy.deepcopy(self._events)

    def is_recording(self):
        return self._recording

    def _ts(self):
        return time.time() - self._t_start

    def _on_move(self, x, y):
        if not self._recording:
            return
        with self._lock:
            self._events.append({
                "t": self._ts(), "type": "move", "x": x, "y": y
            })

    def _on_click(self, x, y, button, pressed):
        if not self._recording:
            return
        btn_name = "left" if button == _pynput_mouse.Button.left else \
                   "right" if button == _pynput_mouse.Button.right else "middle"
        with self._lock:
            self._events.append({
                "t": self._ts(), "type": "click",
                "x": x, "y": y, "btn": btn_name, "down": pressed
            })

    def _on_scroll(self, x, y, dx, dy):
        if not self._recording:
            return
        with self._lock:
            self._events.append({
                "t": self._ts(), "type": "scroll",
                "x": x, "y": y, "dx": dx, "dy": dy
            })

    @staticmethod
    def save(events, path):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(events, f, ensure_ascii=False, indent=2)
            log.info(f"录制脚本已保存: {path}")
        except Exception as e:
            log.error(f"保存录制脚本失败: {e}")
            raise

    @staticmethod
    def load(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)


# ══════════════════════════════════════════════════════════
#  回放引擎
# ══════════════════════════════════════════════════════════

def _is_admin():
    try: return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except: return False

def _shell_exec(path, verb):
    try:
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, verb, path, None,
            os.path.dirname(os.path.abspath(path)) or None, 1)
        if ret > 32:
            return True, ""
        codes = {2: "文件未找到", 3: "路径未找到", 5: "访问被拒绝"}
        return False, codes.get(ret, f"ShellExecute code={ret}")
    except Exception as e:
        return False, str(e)

def _launch_app(path, run_as_admin=False):
    if not path:
        return False, "路径为空", None
    path = os.path.normpath(path)
    if not os.path.exists(path):
        return False, f"文件不存在: {path}", None

    ext = os.path.splitext(path)[1].lower()

    if ext in (".py", ".pyw"):
        try:
            work_dir = os.path.dirname(os.path.abspath(path))
            CREATE_NO_WINDOW = 0x08000000
            proc = subprocess.Popen(
                [sys.executable, path],
                creationflags=CREATE_NO_WINDOW,
                cwd=work_dir,
            )
            return True, "", proc
        except Exception as e:
            return False, str(e), None

    if run_as_admin and _is_admin():
        try:
            work_dir = os.path.dirname(os.path.abspath(path))
            CREATE_NO_WINDOW = 0x08000000
            proc = subprocess.Popen(
                [path],
                creationflags=CREATE_NO_WINDOW,
                cwd=work_dir,
            )
            return True, "", proc
        except Exception:
            pass

    verb = "runas" if run_as_admin else "open"
    ok, err = _shell_exec(path, verb)
    return ok, err, None


WHEEL_DELTA = 120

def _scroll_wheel(units, delta_per_unit=120):
    if not units:
        return
    total_delta = int(units) * int(delta_per_unit)
    if HAS_WIN32:
        try:
            MOUSEEVENTF_WHEEL = 0x0800
            win32api.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, total_delta, 0)
            return
        except Exception as e:
            log.warning(f"win32api 滚轮失败，尝试 ctypes: {e}")
    try:
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx",int),("dy",int),("mouseData",ctypes.c_uint32),
                        ("dwFlags",ctypes.c_uint32),("time",ctypes.c_uint32),
                        ("dwExtraInfo",ctypes.POINTER(ctypes.c_ulong))]
        class INPUT(ctypes.Structure):
            class _INPUT(ctypes.Union):
                _fields_ = [("mi", MOUSEINPUT)]
            _anonymous_ = ("_input",)
            _fields_ = [("type", ctypes.c_uint32), ("_input", _INPUT)]
        inp = INPUT()
        inp.type = 0
        inp.mi.mouseData = ctypes.c_uint32(total_delta)
        inp.mi.dwFlags = ctypes.c_uint32(0x0800)
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        return
    except Exception as e:
        log.warning(f"ctypes SendInput 滚轮失败，fallback pyautogui: {e}")
    if HAS_PYAUTOGUI:
        pyautogui.scroll(units)


class PlaybackEngine:
    def __init__(self, jitter_ms=50):
        self.jitter_ms = jitter_ms
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def play(self, events, speed=1.0, on_progress=None, max_gap=2.0):
        if not HAS_PYAUTOGUI:
            raise RuntimeError("缺少依赖 pyautogui")

        _orig_pause = pyautogui.PAUSE
        pyautogui.PAUSE = 0

        self._stop_event.clear()
        total = len(events)
        if total == 0:
            pyautogui.PAUSE = _orig_pause
            return

        if max_gap > 0:
            proc = [dict(events[0])]
            accumulated_offset = 0.0
            for i in range(1, len(events)):
                dt = events[i]["t"] - events[i-1]["t"]
                if dt > max_gap:
                    accumulated_offset += (dt - max_gap)
                ev2 = dict(events[i])
                ev2["t"] = events[i]["t"] - accumulated_offset
                proc.append(ev2)
        else:
            proc = events

        t_play_start = time.time()
        t_rec_start  = proc[0]["t"]

        try:
            for i, ev in enumerate(proc):
                if self._stop_event.is_set():
                    log.info("回放被中断")
                    break

                rec_relative = (ev["t"] - t_rec_start) / speed
                jitter = random.uniform(-self.jitter_ms, self.jitter_ms) / 1000.0
                target_t = t_play_start + rec_relative + jitter

                now = time.time()
                if target_t > now:
                    sleep_t = target_t - now
                    while sleep_t > 0.05:
                        if self._stop_event.is_set():
                            break
                        time.sleep(0.05)
                        sleep_t -= 0.05
                    if not self._stop_event.is_set() and sleep_t > 0:
                        time.sleep(max(0.0, sleep_t))

                if self._stop_event.is_set():
                    break

                try:
                    self._exec_event(ev)
                except Exception as e:
                    log.error(f"回放事件[{i}]执行失败: {e} | 事件: {ev}")

                if on_progress:
                    try:
                        on_progress(i + 1, total)
                    except Exception:
                        pass
        finally:
            pyautogui.PAUSE = _orig_pause

        log.info(f"回放完成，共 {total} 个事件")

    @staticmethod
    def _exec_event(ev):
        t = ev["type"]
        if t == "move":
            try:
                import ctypes as _ct
                _ct.windll.user32.SetCursorPos(int(ev["x"]), int(ev["y"]))
            except Exception:
                pyautogui.moveTo(ev["x"], ev["y"])
        elif t == "click":
            btn = ev.get("btn", "left")
            if ev.get("down", True):
                pyautogui.mouseDown(ev["x"], ev["y"], button=btn)
            else:
                pyautogui.mouseUp(ev["x"], ev["y"], button=btn)
        elif t == "scroll":
            dy = int(ev.get("dy", 0))
            if dy != 0:
                try:
                    import ctypes as _ct
                    _ct.windll.user32.SetCursorPos(int(ev["x"]), int(ev["y"]))
                except Exception:
                    pyautogui.moveTo(int(ev["x"]), int(ev["y"]))
                _scroll_wheel(dy)
        elif t == "key":
            key = ev.get("key", "")
            if key:
                if ev.get("down", True):
                    pyautogui.keyDown(key)
                else:
                    pyautogui.keyUp(key)


# ══════════════════════════════════════════════════════════
#  步骤数据结构
# ══════════════════════════════════════════════════════════

# 默认点击序列（一个动作，识别位置单击一次）
_DEFAULT_CLICK_ACTIONS = [copy.deepcopy(CLICK_ACTION_DEFAULT)]

STEP_DEFAULTS = {
    # 1. OCR点击
    "ocr_click": {
        "type":           "ocr_click",
        "name":           "OCR点击",
        "region":         None,
        "keywords":       "",
        "click_actions":  [copy.deepcopy(CLICK_ACTION_DEFAULT)],
        "ocr_engine":     "paddle",
        "ocr_scale":      2,
        "language":       "chi_sim",
        "retry_interval": 1.0,
        "max_retries":    30,
        "jitter":         True,
    },
    # 2. 固定等待
    "wait": {
        "type":    "wait",
        "name":    "固定等待",
        "seconds": 1.0,
    },
    # 3. 鼠标移动
    "mouse_move": {
        "type":     "mouse_move",
        "name":     "鼠标移动",
        "x":        0,
        "y":        0,
        "duration": 0.3,
    },
    # 4. 滚轮
    "scroll": {
        "type":      "scroll",
        "name":      "滚轮",
        "x":         0,
        "y":         0,
        "direction": "up",
        "clicks":    1,
        "interval":  0.1,
        "delta_mul": 3.0,
    },
    # 5. OCR循环检测（带子动作）
    "ocr_loop": {
        "type":           "ocr_loop",
        "name":           "OCR循环检测",
        "region":         None,
        "keywords":       "",
        "click_on_match": True,
        "click_actions":  [copy.deepcopy(CLICK_ACTION_DEFAULT)],
        "check_interval": 1.0,
        "max_retries":    10,
        "ocr_engine":     "paddle",
        "ocr_scale":      2,
        "language":       "chi_sim",
        "pre_action":     None,
    },
    # 6. 执行录制脚本
    "run_script": {
        "type":        "run_script",
        "name":        "执行录制脚本",
        "script_path": "",
        "speed":       1.0,
        "jitter_ms":   50,
        "max_gap":     2.0,
    },
    # 7. 轮询OCR
    "ocr_poll": {
        "type":           "ocr_poll",
        "name":           "轮询OCR",
        "region":         None,
        "keywords":       "",
        "interval":       1.0,
        "max_count":      60,
        "on_timeout":     "continue",
        "click_on_match": False,
        "click_actions":  [copy.deepcopy(CLICK_ACTION_DEFAULT)],
        "ocr_engine":     "paddle",
        "ocr_scale":      2,
        "language":       "chi_sim",
    },
    # 8. 启动程序/脚本
    "launch_app": {
        "type":         "launch_app",
        "name":         "启动程序",
        "app_path":     "",
        "run_as_admin": False,
        "wait_seconds": 0.0,
    },
    # 9. 截图点击（BitBlt截图+模板匹配，检测到就点击，超限ABORT）
    "img_click": {
        "type":           "img_click",
        "name":           "截图点击",
        "region":         None,          # 检测区域
        "template_path":  "",            # 模板图片路径
        "threshold":      80,            # 匹配阈值 %（0-100）
        "click_actions":  [copy.deepcopy(CLICK_ACTION_DEFAULT)],
        "retry_interval": 1.0,
        "max_retries":    30,
        "jitter":         True,
    },
    # 10. 截图循环检测（带子动作，超限ABORT）
    "img_loop": {
        "type":           "img_loop",
        "name":           "截图循环检测",
        "region":         None,
        "template_path":  "",
        "threshold":      80,
        "click_on_match": True,
        "click_actions":  [copy.deepcopy(CLICK_ACTION_DEFAULT)],
        "check_interval": 1.0,
        "max_retries":    10,
        "pre_action":     None,
    },
    # 11. 轮询截图（最多检测N次，超限 continue/abort）
    "img_poll": {
        "type":           "img_poll",
        "name":           "轮询截图",
        "region":         None,
        "template_path":  "",
        "threshold":      80,
        "interval":       1.0,
        "max_count":      60,
        "on_timeout":     "continue",
        "click_on_match": False,
        "click_actions":  [copy.deepcopy(CLICK_ACTION_DEFAULT)],
    },
    # 12. 键盘命令
    "keyboard": {
        "type":        "keyboard",
        "name":        "键盘命令",
        "key_actions": [],   # 按键序列，每项: {key, action, count, interval}
    },
}

def make_step(step_type):
    """创建指定类型的步骤（深拷贝默认配置）"""
    return copy.deepcopy(STEP_DEFAULTS.get(step_type, {}))


# ══════════════════════════════════════════════════════════
#  步骤执行器
# ══════════════════════════════════════════════════════════

class StepExecutor:
    OK    = "ok"
    ABORT = "abort"
    SKIP  = "skip"

    def __init__(self, cfg=None, stop_event=None, log_callback=None):
        self.cfg          = cfg or {}
        self.stop_event   = stop_event or threading.Event()
        self.log_callback = log_callback
        self._playback    = None

    def _log(self, msg, level="info"):
        log.log(getattr(logging, level.upper(), logging.INFO), msg)
        if self.log_callback:
            try:
                self.log_callback(msg, level)
            except Exception:
                pass

    def _stopped(self):
        return self.stop_event.is_set()

    def _interruptible_sleep(self, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self._stopped():
                return False
            time.sleep(min(0.05, deadline - time.time()))
        return True

    def _get_ocr_settings(self):
        return {
            "tess_path":  self.cfg.get("tesseract_path", ""),
            "paddle_exe": self.cfg.get("paddle_exe_path", ""),
        }

    def _ensure_paddle(self):
        if not _bg:
            return False
        exe = self.cfg.get("paddle_exe_path", "").strip()
        if not exe or not os.path.exists(exe):
            self._log("PaddleOCR-json.exe 路径未配置", "err")
            return False
        try:
            eng = _bg._get_paddle_engine()
            eng.start(exe)
            return True
        except Exception as e:
            self._log(f"PaddleOCR启动失败: {e}", "err")
            return False

    def _do_ocr_on_region(self, step):
        region = step.get("region")
        if not region:
            self._log("步骤未设置检测区域", "warn")
            return None
        img = _do_screenshot(region)
        if img is None:
            self._log("截图失败", "err")
            return None
        engine = step.get("ocr_engine", "paddle")
        if engine == "paddle":
            self._ensure_paddle()
        text = _do_ocr(
            img,
            engine=engine,
            lang=step.get("language", "chi_sim"),
            tess_path=self.cfg.get("tesseract_path", ""),
            scale=step.get("ocr_scale", 2),
        )
        return text

    def _find_match_pos(self, step, text):
        kw_str = step.get("keywords", "")
        matched, first_kw = _match_keywords(text, kw_str)
        if not matched or not first_kw:
            return matched, None

        region = step.get("region")
        try:
            scale = int(step.get("ocr_scale", 2))
        except (ValueError, TypeError):
            scale = 2
        if not region or not _bg:
            if region:
                cx = (region[0] + region[2]) // 2
                cy = (region[1] + region[3]) // 2
                return True, (cx, cy)
            return True, None

        try:
            img = _do_screenshot(region)
            if img and scale > 1:
                w, h = img.size
                img_scaled = img.resize((w * scale, h * scale), Image.LANCZOS)
            else:
                img_scaled = img
            pos = _bg.do_ocr_find_pos(
                img_scaled, [first_kw],
                engine=step.get("ocr_engine", "paddle"),
                lang=step.get("language", "chi_sim"),
                tess_path=self.cfg.get("tesseract_path", ""),
            )
            if pos and scale > 1:
                pos = (pos[0] // scale, pos[1] // scale)
            if pos:
                abs_x = region[0] + pos[0]
                abs_y = region[1] + pos[1]
                return True, (abs_x, abs_y)
        except Exception as e:
            self._log(f"定位关键词坐标失败: {e}", "warn")

        cx = (region[0] + region[2]) // 2
        cy = (region[1] + region[3]) // 2
        return True, (cx, cy)

    def _do_img_match_on_region(self, step):
        """
        BitBlt截图 + 模板匹配。
        返回 (matched: bool, abs_cx: int, abs_cy: int)
        abs_cx/cy 是屏幕绝对坐标中心点
        """
        region = step.get("region")
        template_path = step.get("template_path", "").strip()
        threshold = float(step.get("threshold", 80)) / 100.0

        if not region:
            self._log("步骤未设置检测区域", "warn")
            return False, 0, 0

        img = _do_screenshot_blt(region)
        if img is None:
            self._log("BitBlt截图失败", "err")
            return False, 0, 0

        matched, cx, cy = _img_match_template(img, template_path, threshold)
        if matched:
            # cx/cy 是相对 region 的坐标，转为屏幕绝对坐标
            abs_cx = region[0] + cx
            abs_cy = region[1] + cy
            return True, abs_cx, abs_cy
        return False, 0, 0

    # ── 序列点击执行 ────────────────────────────────────────

    def _exec_click_actions(self, click_actions, match_pos, jitter=True):
        """
        执行 click_actions 序列。
        match_pos: 识别位置绝对屏幕坐标 (x,y) 或 None（无识别时）
        jitter: 是否对最终坐标加随机抖动
        """
        if not click_actions:
            # 兼容旧数据：无序列则不点击
            return

        for i, action in enumerate(click_actions):
            if self._stopped():
                return

            # 前置等待
            pre_delay = float(action.get("pre_delay", 0.0))
            if pre_delay > 0:
                self._log(f"    序列[{i+1}] 前置等待 {pre_delay}s", "info")
                if not self._interruptible_sleep(pre_delay):
                    return

            if self._stopped():
                return

            pos = _resolve_click_pos(action, match_pos)
            if pos is None:
                self._log(f"    序列[{i+1}] 无法确定点击坐标，跳过", "warn")
                continue

            x, y = pos
            if jitter:
                x += random.randint(-3, 3)
                y += random.randint(-3, 3)

            count     = int(action.get("count", 1))
            interval  = float(action.get("interval", 0.1))
            ctype     = action.get("click_type", "single")

            # 移动到目标
            dur = round(random.uniform(0.01, 0.02), 3)
            try:
                pyautogui.moveTo(x, y, duration=dur)
            except Exception as e:
                self._log(f"    鼠标移动失败: {e}", "warn")

            time.sleep(random.uniform(0.01, 0.02))

            for n in range(count):
                if self._stopped():
                    return
                try:
                    if ctype == "double":
                        pyautogui.doubleClick(x, y)
                        self._log(f"    序列[{i+1}] 双击({x},{y}) [{n+1}/{count}]", "info")
                    elif ctype == "right":
                        pyautogui.rightClick(x, y)
                        self._log(f"    序列[{i+1}] 右击({x},{y}) [{n+1}/{count}]", "info")
                    else:
                        pyautogui.click(x, y)
                        self._log(f"    序列[{i+1}] 单击({x},{y}) [{n+1}/{count}]", "info")
                except Exception as e:
                    self._log(f"    序列[{i+1}] 点击失败: {e}", "err")

                if n < count - 1 and interval > 0:
                    time.sleep(interval)

    # ── 11种步骤执行 ────────────────────────────────────────

    def exec_step(self, step):
        t = step.get("type", "")
        name = step.get("name", t)
        self._log(f"执行步骤 [{name}]", "info")

        if   t == "ocr_click":   return self._exec_ocr_click(step)
        elif t == "wait":         return self._exec_wait(step)
        elif t == "mouse_move":   return self._exec_mouse_move(step)
        elif t == "scroll":       return self._exec_scroll(step)
        elif t == "ocr_loop":     return self._exec_ocr_loop(step)
        elif t == "run_script":   return self._exec_run_script(step)
        elif t == "ocr_poll":     return self._exec_ocr_poll(step)
        elif t == "launch_app":   return self._exec_launch_app(step)
        elif t == "img_click":    return self._exec_img_click(step)
        elif t == "img_loop":     return self._exec_img_loop(step)
        elif t == "img_poll":     return self._exec_img_poll(step)
        elif t == "keyboard":     return self._exec_keyboard(step)
        else:
            self._log(f"未知步骤类型: {t}", "warn")
            return self.OK

    # ── OCR三种步骤 ──────────────────────────────────────────

    def _exec_ocr_click(self, step):
        kw_str      = step.get("keywords", "")
        max_retries = int(step.get("max_retries", 30))
        interval    = float(step.get("retry_interval", 1.0))
        click_actions = step.get("click_actions", [])
        jitter      = step.get("jitter", True)

        for attempt in range(max_retries + 1):
            if self._stopped():
                return self.ABORT

            text = self._do_ocr_on_region(step)
            text_short = (text or "").strip().replace("\n", " ")[:60]
            self._log(
                f"  OCR结果: 「{text_short}」 | 关键词: 「{kw_str}」 "
                f"| 尝试{attempt+1}/{max_retries+1}", "info")

            if text:
                matched, pos = self._find_match_pos(step, text)
                if matched:
                    self._log(f"  关键词匹配，坐标: {pos}", "ok")
                    self._exec_click_actions(click_actions, pos, jitter=jitter)
                    return self.OK

            if attempt < max_retries:
                self._log(f"  未匹配，{interval}s后重试...", "info")
                if not self._interruptible_sleep(interval):
                    return self.ABORT

        self._log(f"OCR点击步骤超过最大重试次数({max_retries})，终止流程", "err")
        return self.ABORT

    def _exec_ocr_loop(self, step):
        kw_str       = step.get("keywords", "")
        max_retries  = int(step.get("max_retries", 10))
        interval     = float(step.get("check_interval", 1.0))
        click_match  = step.get("click_on_match", True)
        click_actions = step.get("click_actions", [])
        pre_action   = step.get("pre_action")

        for attempt in range(max_retries + 1):
            if self._stopped():
                return self.ABORT

            if pre_action:
                self._log(f"  循环第{attempt+1}轮：执行子动作", "info")
                result = self.exec_step(pre_action)
                if result == self.ABORT:
                    return self.ABORT

            if not self._interruptible_sleep(interval):
                return self.ABORT

            text = self._do_ocr_on_region(step)
            text_short = (text or "").strip().replace("\n", " ")[:60]
            self._log(f"  循环OCR[{attempt+1}/{max_retries+1}]: 「{text_short}」", "info")

            if text:
                matched, pos = self._find_match_pos(step, text)
                if matched:
                    self._log(f"  关键词匹配成功，坐标: {pos}", "ok")
                    if click_match:
                        self._exec_click_actions(click_actions, pos)
                    return self.OK

        self._log(f"OCR循环检测超过最大重试次数({max_retries})，终止流程", "err")
        return self.ABORT

    def _exec_ocr_poll(self, step):
        kw_str      = step.get("keywords", "")
        interval    = float(step.get("interval", 1.0))
        max_count   = int(step.get("max_count", 60))
        on_timeout  = step.get("on_timeout", "continue")
        click_match = step.get("click_on_match", False)
        click_actions = step.get("click_actions", [])

        for i in range(max_count):
            if self._stopped():
                return self.ABORT

            text = self._do_ocr_on_region(step)
            text_short = (text or "").strip().replace("\n", " ")[:60]
            self._log(f"  轮询[{i+1}/{max_count}]: 「{text_short}」", "info")

            if text:
                matched, pos = self._find_match_pos(step, text)
                if matched:
                    self._log(f"  轮询检测成功，坐标: {pos}", "ok")
                    if click_match:
                        self._exec_click_actions(click_actions, pos)
                    return self.OK

            if i < max_count - 1:
                if not self._interruptible_sleep(interval):
                    return self.ABORT

        self._log(f"轮询OCR超过最大次数({max_count})，on_timeout={on_timeout}", "warn")
        if on_timeout == "abort":
            return self.ABORT
        return self.OK

    # ── 截图三种步骤 ─────────────────────────────────────────

    def _exec_img_click(self, step):
        """截图点击：BitBlt截图+模板匹配，检测到→点击，超限→ABORT"""
        max_retries  = int(step.get("max_retries", 30))
        interval     = float(step.get("retry_interval", 1.0))
        click_actions = step.get("click_actions", [])
        jitter       = step.get("jitter", True)
        tpl          = step.get("template_path", "")
        thr          = step.get("threshold", 80)

        for attempt in range(max_retries + 1):
            if self._stopped():
                return self.ABORT

            matched, cx, cy = self._do_img_match_on_region(step)
            self._log(
                f"  截图匹配[{attempt+1}/{max_retries+1}]: "
                f"{'命中' if matched else '未命中'} 模板={os.path.basename(tpl)} 阈值={thr}%",
                "info"
            )

            if matched:
                self._log(f"  模板匹配成功，中心坐标: ({cx},{cy})", "ok")
                self._exec_click_actions(click_actions, (cx, cy), jitter=jitter)
                return self.OK

            if attempt < max_retries:
                if not self._interruptible_sleep(interval):
                    return self.ABORT

        self._log(f"截图点击超过最大重试次数({max_retries})，终止流程", "err")
        return self.ABORT

    def _exec_img_loop(self, step):
        """截图循环检测（带子动作）：结构同 ocr_loop"""
        max_retries  = int(step.get("max_retries", 10))
        interval     = float(step.get("check_interval", 1.0))
        click_match  = step.get("click_on_match", True)
        click_actions = step.get("click_actions", [])
        pre_action   = step.get("pre_action")
        tpl          = step.get("template_path", "")
        thr          = step.get("threshold", 80)

        for attempt in range(max_retries + 1):
            if self._stopped():
                return self.ABORT

            if pre_action:
                self._log(f"  截图循环第{attempt+1}轮：执行子动作", "info")
                result = self.exec_step(pre_action)
                if result == self.ABORT:
                    return self.ABORT

            if not self._interruptible_sleep(interval):
                return self.ABORT

            matched, cx, cy = self._do_img_match_on_region(step)
            self._log(
                f"  截图循环[{attempt+1}/{max_retries+1}]: "
                f"{'命中' if matched else '未命中'} 模板={os.path.basename(tpl)} 阈值={thr}%",
                "info"
            )

            if matched:
                self._log(f"  模板匹配成功，中心坐标: ({cx},{cy})", "ok")
                if click_match:
                    self._exec_click_actions(click_actions, (cx, cy))
                return self.OK

        self._log(f"截图循环检测超过最大重试次数({max_retries})，终止流程", "err")
        return self.ABORT

    def _exec_img_poll(self, step):
        """轮询截图：结构同 ocr_poll"""
        interval    = float(step.get("interval", 1.0))
        max_count   = int(step.get("max_count", 60))
        on_timeout  = step.get("on_timeout", "continue")
        click_match = step.get("click_on_match", False)
        click_actions = step.get("click_actions", [])
        tpl         = step.get("template_path", "")
        thr         = step.get("threshold", 80)

        for i in range(max_count):
            if self._stopped():
                return self.ABORT

            matched, cx, cy = self._do_img_match_on_region(step)
            self._log(
                f"  截图轮询[{i+1}/{max_count}]: "
                f"{'命中' if matched else '未命中'} 模板={os.path.basename(tpl)} 阈值={thr}%",
                "info"
            )

            if matched:
                self._log(f"  模板匹配成功，中心坐标: ({cx},{cy})", "ok")
                if click_match:
                    self._exec_click_actions(click_actions, (cx, cy))
                return self.OK

            if i < max_count - 1:
                if not self._interruptible_sleep(interval):
                    return self.ABORT

        self._log(f"轮询截图超过最大次数({max_count})，on_timeout={on_timeout}", "warn")
        if on_timeout == "abort":
            return self.ABORT
        return self.OK

    # ── 其余步骤 ─────────────────────────────────────────────

    def _exec_wait(self, step):
        seconds = float(step.get("seconds", 1.0))
        self._log(f"  等待 {seconds}s", "info")
        if not self._interruptible_sleep(seconds):
            return self.ABORT
        return self.OK

    def _exec_mouse_move(self, step):
        x   = int(step.get("x", 0))
        y   = int(step.get("y", 0))
        dur = float(step.get("duration", 0.3))
        dur += random.uniform(-0.05, 0.05)
        dur = max(0.05, dur)
        self._log(f"  移动鼠标到 ({x},{y}) 耗时{dur:.2f}s", "info")
        try:
            pyautogui.moveTo(x, y, duration=dur)
        except Exception as e:
            self._log(f"  鼠标移动失败: {e}", "err")
        return self.OK

    def _exec_scroll(self, step):
        x         = int(step.get("x", 0))
        y         = int(step.get("y", 0))
        direction = step.get("direction", "up")
        clicks    = int(step.get("clicks", 1))
        interval  = float(step.get("interval", 0.1))
        try:
            delta_mul = float(step.get("delta_mul", 3))
        except (ValueError, TypeError):
            delta_mul = 3.0
        unit = 1 if direction == "up" else -1

        self._log(
            f"  移动到 ({x},{y}) 滚轮{'上' if direction=='up' else '下'} "
            f"{clicks}格 delta_mul={delta_mul}", "info")
        try:
            pyautogui.moveTo(x, y, duration=random.uniform(0.01, 0.02))
            for i in range(clicks):
                if self._stopped():
                    return self.ABORT
                _scroll_wheel(unit, delta_per_unit=max(1, int(WHEEL_DELTA * delta_mul)))
                if i < clicks - 1:
                    self._interruptible_sleep(interval)
        except Exception as e:
            self._log(f"  滚轮操作失败: {e}", "err")
        return self.OK


    def _exec_keyboard(self, step):
        """
        执行键盘命令序列。
        key_actions 每项: {key, action: 'press'/'down'/'up', count, interval}
        action: press=按下并弹起, down=仅按下, up=仅弹起
        """
        key_actions = step.get('key_actions', [])
        if not key_actions:
            self._log('  键盘命令序列为空', 'warn')
            return self.OK

        for i, ka in enumerate(key_actions):
            if self._stopped():
                return self.ABORT
            key    = ka.get('key', '').strip()
            action = ka.get('action', 'press')
            count  = max(1, int(ka.get('count', 1)))
            interval = float(ka.get('interval', 0.05))
            if not key:
                self._log(f'  键盘序列[{i+1}] key为空，跳过', 'warn')
                continue
            # 解析组合键: ctrl+c -> ['ctrl','c']
            keys = [k.strip() for k in key.replace('+', ' + ').split('+') if k.strip()]
            self._log(
                f'  键盘序列[{i+1}] key={key} action={action} x{count}', 'info')
            try:
                for n in range(count):
                    if self._stopped():
                        return self.ABORT
                    if action == 'press':
                        if len(keys) > 1:
                            pyautogui.hotkey(*keys)
                        else:
                            pyautogui.press(keys[0])
                    elif action == 'down':
                        for k in keys:
                            pyautogui.keyDown(k)
                    elif action == 'up':
                        for k in reversed(keys):
                            pyautogui.keyUp(k)
                    if n < count - 1 and interval > 0:
                        if not self._interruptible_sleep(interval):
                            return self.ABORT
            except Exception as e:
                self._log(f'  键盘序列[{i+1}] 执行失败: {e}', 'err')
                log.exception('键盘步骤异常')
        return self.OK

    def _exec_run_script(self, step):
        path = step.get("script_path", "").strip()
        if not path or not os.path.exists(path):
            self._log(f"录制脚本文件不存在: {path}", "err")
            return self.ABORT

        speed    = float(step.get("speed", 1.0))
        jitter   = int(step.get("jitter_ms", 50))

        try:
            events = RecorderEngine.load(path)
        except Exception as e:
            self._log(f"加载录制脚本失败: {e}", "err")
            return self.ABORT

        max_gap  = float(step.get("max_gap", 2.0))
        self._log(
            f"  回放脚本: {os.path.basename(path)} ({len(events)}个事件) "
            f"speed={speed} max_gap={max_gap}s", "info")
        pb = PlaybackEngine(jitter_ms=jitter)
        self._playback = pb

        def progress(i, total):
            if self._stopped():
                pb.stop()

        pb.play(events, speed=speed, on_progress=progress, max_gap=max_gap)
        self._playback = None

        if self._stopped():
            return self.ABORT
        return self.OK

    def _exec_launch_app(self, step):
        app_path     = step.get("app_path", "").strip()
        run_as_admin = bool(step.get("run_as_admin", False))
        wait_sec     = float(step.get("wait_seconds", 0.0))

        if not app_path:
            self._log("启动程序步骤：路径为空", "err")
            return self.ABORT

        app_path = os.path.normpath(app_path)
        self._log(
            f"  启动{'(管理员)' if run_as_admin else ''}: {os.path.basename(app_path)}",
            "info")

        ok, err, proc = _launch_app(app_path, run_as_admin)
        if ok:
            self._log(f"  启动成功: {os.path.basename(app_path)}", "ok")
        else:
            self._log(f"  启动失败: {err}", "err")
            return self.ABORT

        if wait_sec > 0:
            self._log(f"  等待 {wait_sec}s...", "info")
            if not self._interruptible_sleep(wait_sec):
                return self.ABORT

        return self.OK


# ══════════════════════════════════════════════════════════
#  流程/流程组数据结构
# ══════════════════════════════════════════════════════════

FLOW_DEFAULT = {
    "name":       "流程1",
    "loop_count": 1,
    "steps":      [],
    "next_flow":  -1,   # 组内串联，-1=结束
    "pre_delay":  0.0,
}

FLOW_GROUP_DEFAULT = {
    "name":  "组1",
    "flows": [],
}

GLOBAL_CFG_DEFAULT = {
    "paddle_exe_path": "",
    "tesseract_path":  r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    "ocr_engine":      "paddle",
    "scripts_dir":     "",
    "flow_groups":     [],          # 新格式：流程组列表
    # 兼容旧格式：若存在 "flows" key，迁移逻辑在 load_config 完成
}

CONFIG_FILE = os.path.join(_SCRIPT_DIR, "config", "flow_runner.json")


def _migrate_legacy_config(cfg):
    """
    将旧格式 cfg["flows"] 迁移到 cfg["flow_groups"][0]["flows"]
    迁移后删除顶层 flows key。
    """
    if "flows" in cfg and "flow_groups" not in cfg:
        log.info("检测到旧版配置格式，自动迁移到流程组结构")
        grp = copy.deepcopy(FLOW_GROUP_DEFAULT)
        grp["name"]  = "默认组"
        grp["flows"] = cfg.pop("flows", [])
        cfg["flow_groups"] = [grp]
    elif "flows" in cfg and "flow_groups" in cfg:
        # 两者都有时，以 flow_groups 为准，丢弃顶层 flows
        cfg.pop("flows", None)
    cfg.setdefault("flow_groups", [])
    return cfg


def load_config():
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    cfg = copy.deepcopy(GLOBAL_CFG_DEFAULT)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            cfg.update(data)
    except FileNotFoundError:
        pass
    except Exception as e:
        log.error(f"加载配置失败: {e}")
    _migrate_legacy_config(cfg)
    return cfg


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    # 确保不保存旧 flows 顶层 key
    cfg.pop("flows", None)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        log.info("配置已保存")
    except Exception as e:
        log.error(f"保存配置失败: {e}")


# ══════════════════════════════════════════════════════════
#  进程清理保障
# ══════════════════════════════════════════════════════════
import atexit as _atexit

def _cleanup_all():
    try:
        if _bg:
            eng = _bg._get_paddle_engine()
            if eng._proc and eng._proc.poll() is None:
                eng._proc.terminate()
                try: eng._proc.wait(timeout=3)
                except Exception: eng._proc.kill()
                log.info("[atexit] PaddleOCR-json 子进程已终止")
    except Exception:
        pass

_atexit.register(_cleanup_all)


# ══════════════════════════════════════════════════════════
#  简单自测
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    if MISSING:
        print(f"[警告] 缺少依赖: {', '.join(MISSING)}")
        print("pip install " + " ".join(MISSING))

    print("=== flow_runner Part 1 底层引擎自测 ===")
    print(f"bg_ocr_click 模块: {'已加载' if _bg else '未找到（将使用内联实现）'}")
    print(f"pyautogui: {'OK' if HAS_PYAUTOGUI else '缺失'}")
    print(f"pynput:    {'OK' if HAS_PYNPUT else '缺失'}")
    print(f"Pillow:    {'OK' if HAS_PIL else '缺失'}")
    print(f"pywin32:   {'OK' if HAS_WIN32 else '缺失'}")
    print(f"opencv:    {'OK' if HAS_CV2 else '缺失（截图识别步骤不可用）'}")

    s = make_step("img_click")
    print(f"\n默认 img_click 步骤: {json.dumps(s, ensure_ascii=False, indent=2)}")

    cfg = load_config()
    print(f"\n当前配置流程组数: {len(cfg.get('flow_groups', []))}")
    print("\n=== Part 1 自测完成 ===")
