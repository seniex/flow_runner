"""
flow_runner_p3.py  -- Part 3: GUI 主程序
依赖 flow_runner_p1.py + flow_runner_p2.py（同目录）

变更：
  A. 左侧栏改为流程组树形列表（Treeview），支持右键→移动到/复制到组
  B. 顶部"从流程开始"改为 [组▼]-[流程▼] 二级选择
  C. 新增 img_click / img_loop / img_poll 三种步骤的 GUI 编辑
  D. 所有含识别位置的步骤，click_type 改为序列点击编辑器
"""

import sys, os, time, copy, json, threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from flow_runner_p1 import (
    RecorderEngine, make_step, make_click_action, load_config, save_config, log,
    STEP_DEFAULTS,
)
from flow_runner_p2 import (
    FlowRunner, State,
    group_add, group_delete, group_rename,
    flow_add, flow_delete, flow_move, flow_move_to_group,
    step_add, step_delete, step_move,
)

# ══════════════════════════════════════════════════════════
#  颜色主题
# ══════════════════════════════════════════════════════════
T = {
    "bg":"#1e2130","sidebar":"#161827","card":"#252840","card2":"#2d3150",
    "accent":"#3d6bff","success":"#2ecc71","danger":"#e74c3c","warning":"#f39c12",
    "text":"#e8eaf0","text2":"#9099b8","border":"#363d60","active":"#3d4f8a",
    "lb":"#141520","lt":"#8fc6ff","lw":"#f39c12","lo":"#2ecc71","le":"#e74c3c",
}

STEP_LABELS = {
    "ocr_click":  "OCR点击",
    "wait":       "固定等待",
    "mouse_move": "鼠标移动",
    "scroll":     "滚轮",
    "ocr_loop":   "OCR循环检测",
    "run_script": "执行录制脚本",
    "ocr_poll":   "轮询OCR",
    "launch_app": "启动程序",
    "img_click":  "截图点击",
    "img_loop":   "截图循环检测",
    "img_poll":   "轮询截图",
    "keyboard":   "键盘命令",
}

# 有"识别位置"的步骤类型（可使用序列点击且有 match_center/offset 选项）
MATCH_STEP_TYPES = {"ocr_click","ocr_loop","ocr_poll","img_click","img_loop","img_poll"}


# ══════════════════════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════════════════════
def _btn(p, text, color, cmd, width=None, **kw):
    b = tk.Button(p, text=text, bg=color, fg="white", relief="flat",
                  font=("Microsoft YaHei", 9), cursor="hand2", command=cmd,
                  activebackground=T["accent"], activeforeground="white",
                  padx=8, pady=3, **kw)
    if width:
        b.config(width=width)
    return b

def _sep(p, color=None):
    tk.Frame(p, bg=color or T["border"], height=1).pack(fill="x", pady=4)

def _entry(parent, width=6, value=""):
    tf = tk.Frame(parent, bg=T["border"], padx=1, pady=1)
    tf.pack(side="left", padx=2)
    e = tk.Entry(tf, bg=T["card"], fg=T["text"], insertbackground=T["text"],
                 relief="flat", font=("Microsoft YaHei", 9), width=width)
    e.insert(0, str(value))
    e.pack(ipady=2)
    return e


def pick_region(callback, cancel_callback=None):
    from PIL import ImageGrab, ImageTk
    try:
        shot = ImageGrab.grab(all_screens=True)
    except Exception:
        messagebox.showerror("错误", "截图失败")
        return
    ov = tk.Toplevel()
    ov.attributes("-fullscreen", True)
    ov.attributes("-topmost", True)
    ov.overrideredirect(True)
    sw, sh = ov.winfo_screenwidth(), ov.winfo_screenheight()
    disp = shot.resize((sw, sh)) if shot.size != (sw, sh) else shot
    tki = ImageTk.PhotoImage(disp)
    cv = tk.Canvas(ov, width=sw, height=sh, cursor="crosshair", bd=0, highlightthickness=0)
    cv.pack(fill="both", expand=True)
    cv.create_image(0, 0, anchor="nw", image=tki); cv._ref = tki
    cv.create_rectangle(0, 0, sw, sh, fill="black", stipple="gray25", outline="")
    cv.create_text(sw//2, 30, text="拖动选择检测区域  Esc=取消",
                   fill="white", font=("Microsoft YaHei", 14))
    st = {"s": None, "r": None}
    def press(e): st["s"] = (e.x, e.y)
    def drag(e):
        if st["s"]:
            if st["r"]: cv.delete(st["r"])
            st["r"] = cv.create_rectangle(st["s"][0], st["s"][1], e.x, e.y,
                                           outline="#3d6bff", width=2, dash=(4, 2))
    def release(e):
        if st["s"]:
            x1, y1 = min(st["s"][0], e.x), min(st["s"][1], e.y)
            x2, y2 = max(st["s"][0], e.x), max(st["s"][1], e.y)
            ov.destroy()
            if x2-x1 > 4 and y2-y1 > 4:
                sx = shot.width/sw; sy = shot.height/sh
                callback(int(x1*sx), int(y1*sy), int(x2*sx), int(y2*sy))
            elif cancel_callback:
                cancel_callback()
    def on_cancel(e):
        ov.destroy()
        if cancel_callback: cancel_callback()
    cv.bind("<ButtonPress-1>", press)
    cv.bind("<B1-Motion>", drag)
    cv.bind("<ButtonRelease-1>", release)
    ov.bind("<Escape>", on_cancel)
    ov.focus_force()


def pick_coord(callback, cancel_callback=None):
    ov = tk.Toplevel()
    ov.attributes("-fullscreen", True)
    ov.attributes("-alpha", 0.01)
    ov.attributes("-topmost", True)
    ov.overrideredirect(True)
    tk.Label(ov, text="点击目标位置  Esc=取消", bg="#222", fg="white",
             font=("Microsoft YaHei", 14), padx=20, pady=10
             ).place(relx=0.5, rely=0.05, anchor="center")
    def on_click(e):
        ov.destroy(); callback(e.x_root, e.y_root)
    def on_cancel(e):
        ov.destroy()
        if cancel_callback: cancel_callback()
    ov.bind("<Button-1>", on_click)
    ov.bind("<Escape>", on_cancel)
    ov.focus_force()


# ══════════════════════════════════════════════════════════
#  序列点击编辑器组件
# ══════════════════════════════════════════════════════════
POS_MODE_LABELS = {
    "match_center": "识别位置（中心点）",
    "offset":       "识别位置 + 偏移",
    "abs":          "屏幕固定坐标",
}
POS_MODES = list(POS_MODE_LABELS.keys())


class ClickActionRow(tk.Frame):
    """
    单条序列点击行：
      [前置等待___秒]  [点击位置▼]  点击[___]次  间隔[___]秒  [↑][↓][×]
    has_match_pos: 是否显示"识别位置"选项（无识别的步骤只显示 abs 模式）
    """
    def __init__(self, parent, action_data, index, on_delete, on_move, has_match_pos,
                 app_ref, **kw):
        super().__init__(parent, bg=T["card"], **kw)
        self._d    = action_data
        self._idx  = index
        self._del  = on_delete
        self._mov  = on_move
        self._has  = has_match_pos
        self._app  = app_ref
        self._build()
        self._load()

    def _build(self):
        bg = T["card"]
        # 行号
        tk.Label(self, text=f"{self._idx+1}.", bg=bg, fg=T["text2"],
                 font=("Microsoft YaHei", 8), width=2).pack(side="left", padx=(4,0))

        # 前置等待
        tk.Label(self, text="前置等待", bg=bg, fg=T["text2"],
                 font=("Microsoft YaHei", 8)).pack(side="left", padx=(4,0))
        self._pre_e = _entry(self, width=4, value=self._d.get("pre_delay", 0.0))
        self._pre_e.pack(side="left")  # already packed inside _entry frame
        # 重新 pack：_entry 返回 Entry，父Frame已经pack了，但side没设，补一下
        # 实际 _entry 返回 Entry widget，外层 tf Frame 由 _entry 自己 pack。
        # 为了 side="left" 一致，改用内联写法：
        self._pre_e.master.pack_forget()
        self._pre_e.master.pack(side="left", padx=2)
        tk.Label(self, text="秒", bg=bg, fg=T["text2"],
                 font=("Microsoft YaHei", 8)).pack(side="left")

        # 点击位置
        tk.Label(self, text="  位置:", bg=bg, fg=T["text2"],
                 font=("Microsoft YaHei", 8)).pack(side="left")
        pos_opts = (list(POS_MODE_LABELS.values()) if self._has
                    else [POS_MODE_LABELS["abs"]])
        self._pos_var = tk.StringVar()
        self._pos_cb = ttk.Combobox(self, textvariable=self._pos_var,
                                    values=pos_opts, width=16, state="readonly",
                                    font=("Microsoft YaHei", 8))
        self._pos_cb.pack(side="left", padx=2)
        self._pos_cb.bind("<<ComboboxSelected>>", lambda e: self._on_pos_change())

        # 偏移/绝对坐标（动态显示）
        self._offset_frm = tk.Frame(self, bg=bg)
        self._offset_frm.pack(side="left")
        self._ox_e = self._oy_e = None
        self._abs_frm = tk.Frame(self, bg=bg)
        self._abs_frm.pack(side="left")
        self._ax_e = self._ay_e = None

        # 单/双击
        tk.Label(self, text="  方式:", bg=bg, fg=T["text2"],
                 font=("Microsoft YaHei", 8)).pack(side="left")
        self._ct_var = tk.StringVar()
        ttk.Combobox(self, textvariable=self._ct_var,
                     values=["single", "double", "right"], width=6,
                     state="readonly", font=("Microsoft YaHei", 8)
                     ).pack(side="left", padx=2)

        # 点击次数
        tk.Label(self, text="点击", bg=bg, fg=T["text2"],
                 font=("Microsoft YaHei", 8)).pack(side="left", padx=(6,0))
        self._cnt_e = _entry(self, width=3, value=self._d.get("count", 1))
        self._cnt_e.master.pack_forget()
        self._cnt_e.master.pack(side="left", padx=2)
        tk.Label(self, text="次  间隔", bg=bg, fg=T["text2"],
                 font=("Microsoft YaHei", 8)).pack(side="left")
        self._itv_e = _entry(self, width=4, value=self._d.get("interval", 0.1))
        self._itv_e.master.pack_forget()
        self._itv_e.master.pack(side="left", padx=2)
        tk.Label(self, text="秒", bg=bg, fg=T["text2"],
                 font=("Microsoft YaHei", 8)).pack(side="left")

        # 操作按钮
        for txt, clr, cmd in [
            ("↑", T["border"], lambda: self._mov(self._idx, -1)),
            ("↓", T["border"], lambda: self._mov(self._idx, +1)),
            ("×", T["danger"], lambda: self._del(self._idx)),
        ]:
            tk.Button(self, text=txt, bg=clr, fg="white", relief="flat",
                      font=("Microsoft YaHei", 8), cursor="hand2",
                      command=cmd, padx=4, pady=1,
                      activebackground=T["accent"], activeforeground="white"
                      ).pack(side="left", padx=1)

        # 绝对坐标时显示"点选"按钮
        self._pick_btn = tk.Button(
            self, text="点选", bg=T["border"], fg="white", relief="flat",
            font=("Microsoft YaHei", 8), cursor="hand2", padx=4, pady=1,
            command=self._pick_abs,
            activebackground=T["accent"], activeforeground="white"
        )

    def _load(self):
        # 位置模式
        mode = self._d.get("pos_mode", "match_center" if self._has else "abs")
        if not self._has:
            mode = "abs"
        label = POS_MODE_LABELS.get(mode, POS_MODE_LABELS["abs"])
        self._pos_var.set(label)
        self._on_pos_change()

        # 偏移值
        if self._ox_e:
            self._ox_e.delete(0, "end"); self._ox_e.insert(0, str(self._d.get("offset_x", 0)))
        if self._oy_e:
            self._oy_e.delete(0, "end"); self._oy_e.insert(0, str(self._d.get("offset_y", 0)))
        if self._ax_e:
            self._ax_e.delete(0, "end"); self._ax_e.insert(0, str(self._d.get("abs_x", 0)))
        if self._ay_e:
            self._ay_e.delete(0, "end"); self._ay_e.insert(0, str(self._d.get("abs_y", 0)))

        self._ct_var.set(self._d.get("click_type", "single"))
        self._pre_e.delete(0, "end"); self._pre_e.insert(0, str(self._d.get("pre_delay", 0.0)))
        self._cnt_e.delete(0, "end"); self._cnt_e.insert(0, str(self._d.get("count", 1)))
        self._itv_e.delete(0, "end"); self._itv_e.insert(0, str(self._d.get("interval", 0.1)))

    def _on_pos_change(self):
        # 清理旧的动态控件
        for w in self._offset_frm.winfo_children(): w.destroy()
        for w in self._abs_frm.winfo_children(): w.destroy()
        self._ox_e = self._oy_e = None
        self._ax_e = self._ay_e = None
        self._pick_btn.pack_forget()

        label = self._pos_var.get()
        # 反查 mode key
        mode = next((k for k, v in POS_MODE_LABELS.items() if v == label), "abs")

        bg = T["card"]
        if mode == "offset":
            tk.Label(self._offset_frm, text=" 偏移X", bg=bg, fg=T["text2"],
                     font=("Microsoft YaHei", 8)).pack(side="left")
            tf1 = tk.Frame(self._offset_frm, bg=T["border"], padx=1, pady=1)
            tf1.pack(side="left", padx=1)
            self._ox_e = tk.Entry(tf1, bg=T["card"], fg=T["text"],
                                   insertbackground=T["text"], relief="flat",
                                   font=("Microsoft YaHei", 8), width=5)
            self._ox_e.insert(0, str(self._d.get("offset_x", 0)))
            self._ox_e.pack(ipady=1)

            tk.Label(self._offset_frm, text="Y", bg=bg, fg=T["text2"],
                     font=("Microsoft YaHei", 8)).pack(side="left", padx=(2,0))
            tf2 = tk.Frame(self._offset_frm, bg=T["border"], padx=1, pady=1)
            tf2.pack(side="left", padx=1)
            self._oy_e = tk.Entry(tf2, bg=T["card"], fg=T["text"],
                                   insertbackground=T["text"], relief="flat",
                                   font=("Microsoft YaHei", 8), width=5)
            self._oy_e.insert(0, str(self._d.get("offset_y", 0)))
            self._oy_e.pack(ipady=1)

        elif mode == "abs":
            tk.Label(self._abs_frm, text=" X", bg=bg, fg=T["text2"],
                     font=("Microsoft YaHei", 8)).pack(side="left")
            tf1 = tk.Frame(self._abs_frm, bg=T["border"], padx=1, pady=1)
            tf1.pack(side="left", padx=1)
            self._ax_e = tk.Entry(tf1, bg=T["card"], fg=T["text"],
                                   insertbackground=T["text"], relief="flat",
                                   font=("Microsoft YaHei", 8), width=5)
            self._ax_e.insert(0, str(self._d.get("abs_x", 0)))
            self._ax_e.pack(ipady=1)

            tk.Label(self._abs_frm, text="Y", bg=bg, fg=T["text2"],
                     font=("Microsoft YaHei", 8)).pack(side="left", padx=(2,0))
            tf2 = tk.Frame(self._abs_frm, bg=T["border"], padx=1, pady=1)
            tf2.pack(side="left", padx=1)
            self._ay_e = tk.Entry(tf2, bg=T["card"], fg=T["text"],
                                   insertbackground=T["text"], relief="flat",
                                   font=("Microsoft YaHei", 8), width=5)
            self._ay_e.insert(0, str(self._d.get("abs_y", 0)))
            self._ay_e.pack(ipady=1)

            self._pick_btn.pack(side="left", padx=2)

    def _pick_abs(self):
        if self._app:
            self._app.withdraw()
        def cb(x, y):
            if self._ax_e:
                self._ax_e.delete(0, "end"); self._ax_e.insert(0, str(x))
            if self._ay_e:
                self._ay_e.delete(0, "end"); self._ay_e.insert(0, str(y))
            if self._app:
                self._app.deiconify()
        def cancel():
            if self._app: self._app.deiconify()
        if self._app:
            self._app.after(200, lambda: pick_coord(cb, cancel_callback=cancel))
        else:
            pick_coord(cb, cancel_callback=cancel)

    def save(self):
        label = self._pos_var.get()
        mode  = next((k for k, v in POS_MODE_LABELS.items() if v == label), "abs")
        self._d["pos_mode"]   = mode
        self._d["click_type"] = self._ct_var.get()
        try: self._d["pre_delay"] = float(self._pre_e.get())
        except: pass
        try: self._d["count"]     = int(self._cnt_e.get())
        except: pass
        try: self._d["interval"]  = float(self._itv_e.get())
        except: pass
        if mode == "offset":
            try: self._d["offset_x"] = int(self._ox_e.get()) if self._ox_e else 0
            except: pass
            try: self._d["offset_y"] = int(self._oy_e.get()) if self._oy_e else 0
            except: pass
        elif mode == "abs":
            try: self._d["abs_x"] = int(self._ax_e.get()) if self._ax_e else 0
            except: pass
            try: self._d["abs_y"] = int(self._ay_e.get()) if self._ay_e else 0
            except: pass


class ClickActionsEditor(tk.Frame):
    """
    序列点击编辑器：包含多个 ClickActionRow + [+ 添加]按钮
    has_match_pos: 步骤是否有识别位置
    """
    def __init__(self, parent, actions_list, has_match_pos, app_ref, **kw):
        super().__init__(parent, bg=T["card2"], **kw)
        self._actions = actions_list   # 直接引用步骤内 click_actions 列表
        self._has     = has_match_pos
        self._app     = app_ref
        self._rows    = []
        self._rebuild()

    def _rebuild(self):
        for w in self.winfo_children(): w.destroy()
        self._rows.clear()

        hdr = tk.Frame(self, bg=T["card2"])
        hdr.pack(fill="x", pady=(2, 1))
        tk.Label(hdr, text="序列点击:", bg=T["card2"], fg=T["warning"],
                 font=("Microsoft YaHei", 9, "bold")).pack(side="left")
        tk.Button(hdr, text="+ 添加点击", bg=T["accent"], fg="white",
                  relief="flat", font=("Microsoft YaHei", 8), cursor="hand2",
                  command=self._add, padx=6, pady=1,
                  activebackground=T["border"], activeforeground="white"
                  ).pack(side="left", padx=6)

        for i, action in enumerate(self._actions):
            row = ClickActionRow(
                self, action, i,
                on_delete=self._del,
                on_move=self._move,
                has_match_pos=self._has,
                app_ref=self._app,
            )
            row.pack(fill="x", pady=1, padx=4)
            self._rows.append(row)

    def _add(self):
        a = make_click_action()
        if not self._has:
            a["pos_mode"] = "abs"
        self._actions.append(a)
        self._rebuild()

    def _del(self, idx):
        if 0 <= idx < len(self._actions):
            del self._actions[idx]
        self._rebuild()

    def _move(self, idx, d):
        new = idx + d
        if 0 <= new < len(self._actions):
            self._actions[idx], self._actions[new] = self._actions[new], self._actions[idx]
        self._rebuild()

    def save(self):
        for row in self._rows:
            row.save()



# ══════════════════════════════════════════════════════════
#  键盘序列编辑器组件
# ══════════════════════════════════════════════════════════

# pyautogui 常用键名列表（供下拉提示）
# pyautogui 支持的键名完整列表，作为下拉提示（Combobox 可自由输入，不受此限制）
KEY_NAMES = [
    # 字母
    "a","b","c","d","e","f","g","h","i","j","k","l","m",
    "n","o","p","q","r","s","t","u","v","w","x","y","z",
    # 数字主键盘
    "0","1","2","3","4","5","6","7","8","9",
    # F 键
    "f1","f2","f3","f4","f5","f6","f7","f8","f9","f10","f11","f12",
    "f13","f14","f15","f16","f17","f18","f19","f20","f21","f22","f23","f24",
    # 控制键
    "enter","return","tab","space","backspace","delete","escape","esc",
    "insert","home","end","pageup","pagedown",
    "up","down","left","right",
    # 修饰键（单独按下/弹起用）
    "ctrl","shift","alt","win","command","option",
    "ctrlleft","ctrlright","shiftleft","shiftright","altleft","altright",
    # 数字小键盘
    "num0","num1","num2","num3","num4","num5","num6","num7","num8","num9",
    "numlock","decimal","add","subtract","multiply","divide","numpadenter",
    # 符号键（直接按名称）
    "minus","plus","equals","bracketleft","bracketright","backslash",
    "semicolon","apostrophe","grave","comma","period","slash",
    # 媒体/功能键
    "volumeup","volumedown","volumemute",
    "playpause","nexttrack","prevtrack","stop",
    "browserback","browserforward","browserrefresh",
    "capslock","scrolllock","numlock","printscreen","pause","break",
    # 常用组合键（直接输入整条，如 ctrl+c）
    "ctrl+c","ctrl+v","ctrl+x","ctrl+z","ctrl+y","ctrl+a","ctrl+s",
    "ctrl+d","ctrl+f","ctrl+h","ctrl+n","ctrl+o","ctrl+p","ctrl+w",
    "ctrl+shift+esc","ctrl+alt+delete",
    "alt+f4","alt+tab","alt+enter","alt+f",
    "shift+tab","shift+enter","shift+delete",
    "ctrl+shift+n","ctrl+shift+t","ctrl+shift+w",
    "win+d","win+e","win+l","win+r","win+tab",
]

KEY_ACTIONS_CN = {
    "press": "按键",
    "down":  "按下",
    "up":    "弹起",
}

class KeyActionRow(tk.Frame):
    """
    单条键盘序列行：
      [序号] 按键[___▼]  操作[按键▼]  次数[_]  间隔[___]秒  [↑][↓][×]
    """
    def __init__(self, parent, action_data, index, on_delete, on_move, **kw):
        super().__init__(parent, bg=T["card"], **kw)
        self._d    = action_data
        self._idx  = index
        self._del  = on_delete
        self._mov  = on_move
        self._build()
        self._load()

    def _build(self):
        bg = T["card"]
        # 行号
        tk.Label(self, text=f"{self._idx+1}.", bg=bg, fg=T["text2"],
                 font=("Microsoft YaHei", 8), width=2).pack(side="left", padx=(4,0))

        # 按键
        tk.Label(self, text="按键", bg=bg, fg=T["text2"],
                 font=("Microsoft YaHei", 8)).pack(side="left", padx=(4,0))
        self._key_var = tk.StringVar()
        key_cb = ttk.Combobox(self, textvariable=self._key_var,
                              values=KEY_NAMES, width=16,
                              font=("Microsoft YaHei", 8))
        # 不设 state="readonly"，允许自由输入任意键名或组合（如 ctrl+shift+f5）
        key_cb.pack(side="left", padx=2)

        # 操作类型
        tk.Label(self, text="操作", bg=bg, fg=T["text2"],
                 font=("Microsoft YaHei", 8)).pack(side="left", padx=(6,0))
        self._act_var = tk.StringVar()
        ttk.Combobox(self, textvariable=self._act_var,
                     values=list(KEY_ACTIONS_CN.values()),
                     width=5, state="readonly",
                     font=("Microsoft YaHei", 8)).pack(side="left", padx=2)

        # 次数
        tk.Label(self, text="次数", bg=bg, fg=T["text2"],
                 font=("Microsoft YaHei", 8)).pack(side="left", padx=(6,0))
        tf1 = tk.Frame(self, bg=T["border"], padx=1, pady=1)
        tf1.pack(side="left", padx=2)
        self._cnt_e = tk.Entry(tf1, bg=T["card"], fg=T["text"],
                               insertbackground=T["text"], relief="flat",
                               font=("Microsoft YaHei", 8), width=3)
        self._cnt_e.pack(ipady=1)

        # 间隔
        tk.Label(self, text="间隔", bg=bg, fg=T["text2"],
                 font=("Microsoft YaHei", 8)).pack(side="left", padx=(6,0))
        tf2 = tk.Frame(self, bg=T["border"], padx=1, pady=1)
        tf2.pack(side="left", padx=2)
        self._itv_e = tk.Entry(tf2, bg=T["card"], fg=T["text"],
                               insertbackground=T["text"], relief="flat",
                               font=("Microsoft YaHei", 8), width=4)
        self._itv_e.pack(ipady=1)
        tk.Label(self, text="秒", bg=bg, fg=T["text2"],
                 font=("Microsoft YaHei", 8)).pack(side="left")

        # 操作按钮
        for txt, clr, cmd in [
            ("↑", T["border"], lambda: self._mov(self._idx, -1)),
            ("↓", T["border"], lambda: self._mov(self._idx, +1)),
            ("×", T["danger"], lambda: self._del(self._idx)),
        ]:
            tk.Button(self, text=txt, bg=clr, fg="white", relief="flat",
                      font=("Microsoft YaHei", 8), cursor="hand2",
                      command=cmd, padx=4, pady=1,
                      activebackground=T["accent"], activeforeground="white"
                      ).pack(side="left", padx=1)

    def _load(self):
        self._key_var.set(self._d.get("key", ""))
        act_raw = self._d.get("action", "press")
        self._act_var.set(KEY_ACTIONS_CN.get(act_raw, "按键"))
        self._cnt_e.delete(0, "end"); self._cnt_e.insert(0, str(self._d.get("count", 1)))
        self._itv_e.delete(0, "end"); self._itv_e.insert(0, str(self._d.get("interval", 0.05)))

    def save(self):
        self._d["key"]    = self._key_var.get().strip()
        # 反查 action value
        cn_val = self._act_var.get()
        self._d["action"] = next(
            (k for k, v in KEY_ACTIONS_CN.items() if v == cn_val), "press")
        try: self._d["count"]    = int(self._cnt_e.get())
        except: pass
        try: self._d["interval"] = float(self._itv_e.get())
        except: pass


class KeyActionsEditor(tk.Frame):
    """
    键盘序列编辑器：包含多个 KeyActionRow + [+ 添加]按钮
    """
    def __init__(self, parent, actions_list, **kw):
        super().__init__(parent, bg=T["card2"], **kw)
        self._actions = actions_list
        self._rows    = []
        self._rebuild()

    def _rebuild(self):
        for w in self.winfo_children(): w.destroy()
        self._rows.clear()

        hdr = tk.Frame(self, bg=T["card2"])
        hdr.pack(fill="x", pady=(2, 1))
        tk.Label(hdr, text="按键序列:", bg=T["card2"], fg=T["warning"],
                 font=("Microsoft YaHei", 9, "bold")).pack(side="left")
        tk.Button(hdr, text="+ 添加按键", bg=T["accent"], fg="white",
                  relief="flat", font=("Microsoft YaHei", 8), cursor="hand2",
                  command=self._add, padx=6, pady=1,
                  activebackground=T["border"], activeforeground="white"
                  ).pack(side="left", padx=6)

        for i, action in enumerate(self._actions):
            row = KeyActionRow(
                self, action, i,
                on_delete=self._del,
                on_move=self._move,
            )
            row.pack(fill="x", pady=1, padx=4)
            self._rows.append(row)

    def _add(self):
        self._actions.append({"key": "", "action": "press", "count": 1, "interval": 0.05})
        self._rebuild()

    def _del(self, idx):
        if 0 <= idx < len(self._actions):
            del self._actions[idx]
        self._rebuild()

    def _move(self, idx, d):
        new = idx + d
        if 0 <= new < len(self._actions):
            self._actions[idx], self._actions[new] = self._actions[new], self._actions[idx]
        self._rebuild()

    def save(self):
        for row in self._rows:
            row.save()


# ══════════════════════════════════════════════════════════
#  步骤卡片
# ══════════════════════════════════════════════════════════
class StepCard(tk.Frame):
    def __init__(self, parent, step_data, index, on_delete, on_move, app, **kw):
        super().__init__(parent, bg=T["card2"], highlightthickness=1,
                         highlightbackground=T["border"], **kw)
        self._step  = step_data
        self._index = index
        self._del   = on_delete
        self._mov   = on_move
        self._app   = app
        self._exp   = True
        self._wvars = {}
        self._click_editor = None   # ClickActionsEditor 引用
        self._key_editor   = None   # KeyActionsEditor 引用
        self._build()
        self._load()

    def _build(self):
        st  = self._step.get("type", "")
        lbl = STEP_LABELS.get(st, st)
        hdr = tk.Frame(self, bg=T["card2"])
        hdr.pack(fill="x", padx=6, pady=4)
        self._arrow = tk.Label(hdr, text="▼", bg=T["card2"], fg=T["accent"],
                               font=("Microsoft YaHei", 9), cursor="hand2")
        self._arrow.pack(side="left")
        self._arrow.bind("<Button-1>", lambda e: self._toggle())
        tk.Label(hdr, text=f"[{self._index+1}] {lbl}", bg=T["card2"], fg=T["text"],
                 font=("Microsoft YaHei", 9, "bold")).pack(side="left", padx=6)
        self._name_var = tk.StringVar(value=self._step.get("name", lbl))
        tf = tk.Frame(hdr, bg=T["border"], padx=1, pady=1)
        tf.pack(side="left", padx=4)
        tk.Entry(tf, textvariable=self._name_var, bg=T["card"], fg=T["text"],
                 insertbackground=T["text"], relief="flat",
                 font=("Microsoft YaHei", 9), width=14).pack(ipady=2)
        for txt, clr, cmd in [
            ("↑", T["border"], lambda: self._mov(self._index, -1)),
            ("↓", T["border"], lambda: self._mov(self._index, +1)),
            ("×", T["danger"], lambda: self._del(self._index)),
        ]:
            _btn(hdr, txt, clr, cmd).pack(side="right", padx=2)
        self._body = tk.Frame(self, bg=T["card2"])
        self._body.pack(fill="x", padx=10, pady=(0, 6))
        self._build_body(st)

    def _build_body(self, t):
        b = self._body
        has_match = (t in MATCH_STEP_TYPES)

        # ── OCR 三种 ──────────────────────────────────────
        if t in ("ocr_click", "ocr_poll", "ocr_loop"):
            self._build_ocr_region(b)
            self._build_ocr_engine(b)
            if t == "ocr_click":
                self._prow(b, [
                    ("retry_interval", "重试间隔(秒)", "entry", 4, "1.0"),
                    ("max_retries",    "最大重试",     "entry", 4, "30"),
                    ("jitter",         "随机抖动",     "check", None, True),
                ])
            elif t == "ocr_poll":
                self._prow(b, [
                    ("interval",       "间隔(秒)",    "entry", 4, "1.0"),
                    ("max_count",      "最多次数",    "entry", 4, "60"),
                    ("on_timeout",     "超限后",      "combo", ["continue","abort"], "continue"),
                    ("click_on_match", "检测到后执行序列点击", "check", None, False),
                ])
            elif t == "ocr_loop":
                self._prow(b, [
                    ("check_interval", "检测间隔(秒)", "entry", 4, "1.0"),
                    ("max_retries",    "最大重试",     "entry", 4, "10"),
                    ("click_on_match", "检测到后执行序列点击", "check", None, True),
                ])
                self._build_pre(b)

        # ── 截图三种 ──────────────────────────────────────
        elif t in ("img_click", "img_loop", "img_poll"):
            self._build_img_region(b)
            if t == "img_click":
                self._prow(b, [
                    ("retry_interval", "重试间隔(秒)", "entry", 4, "1.0"),
                    ("max_retries",    "最大重试",     "entry", 4, "30"),
                    ("jitter",         "随机抖动",     "check", None, True),
                ])
            elif t == "img_poll":
                self._prow(b, [
                    ("interval",       "间隔(秒)",    "entry", 4, "1.0"),
                    ("max_count",      "最多次数",    "entry", 4, "60"),
                    ("on_timeout",     "超限后",      "combo", ["continue","abort"], "continue"),
                    ("click_on_match", "检测到后执行序列点击", "check", None, False),
                ])
            elif t == "img_loop":
                self._prow(b, [
                    ("check_interval", "检测间隔(秒)", "entry", 4, "1.0"),
                    ("max_retries",    "最大重试",     "entry", 4, "10"),
                    ("click_on_match", "检测到后执行序列点击", "check", None, True),
                ])
                self._build_pre(b)

        # ── 其余步骤 ──────────────────────────────────────
        elif t == "wait":
            self._prow(b, [("seconds", "等待秒数", "entry", 6, "1.0")])
        elif t == "mouse_move":
            self._crow(b, "x", "y", "目标坐标")
            self._prow(b, [("duration", "移动耗时(秒)", "entry", 5, "0.3")])
        elif t == "scroll":
            self._crow(b, "x", "y", "滚轮位置")
            self._prow(b, [
                ("direction", "方向",     "combo", ["up","down"], "up"),
                ("clicks",    "格数",     "entry", 3, "1"),
                ("interval",  "间隔(秒)", "entry", 4, "0.1"),
                ("delta_mul", "滚动倍数", "entry", 3, "3"),
            ])
            tk.Label(b, text="  ↑ 滚动倍数：0.5=60(半格)，1=120(标准)，3=360(大幅)。录制脚本不受影响",
                     bg=T["card2"], fg=T["text2"],
                     font=("Microsoft YaHei", 7)).pack(anchor="w", pady=(0,2))
        elif t == "run_script":
            r = tk.Frame(b, bg=T["card2"])
            r.pack(fill="x", pady=2)
            tk.Label(r, text="脚本文件:", bg=T["card2"], fg=T["text2"],
                     font=("Microsoft YaHei", 9)).pack(side="left")
            self._slbl = tk.Label(r,
                text=os.path.basename(self._step.get("script_path","")) or "未选择",
                bg=T["card2"], fg=T["text2"], font=("Microsoft YaHei", 9))
            self._slbl.pack(side="left", padx=4)
            _btn(r, "选择脚本", T["border"], self._browse_script).pack(side="left")
            self._prow(b, [
                ("speed",    "速度倍数",    "entry", 4, "1.0"),
                ("jitter_ms","抖动(ms)",    "entry", 4, "50"),
                ("max_gap",  "停顿截短(秒)","entry", 4, "2.0"),
            ])
        elif t == "launch_app":
            r = tk.Frame(b, bg=T["card2"])
            r.pack(fill="x", pady=2)
            tk.Label(r, text="程序路径:", bg=T["card2"], fg=T["text2"],
                     font=("Microsoft YaHei", 9)).pack(side="left")
            tf = tk.Frame(r, bg=T["border"], padx=1, pady=1)
            tf.pack(side="left", padx=4, fill="x", expand=True)
            path_e = tk.Entry(tf, bg=T["card"], fg=T["text"], insertbackground=T["text"],
                               relief="flat", font=("Microsoft YaHei", 9), width=28)
            path_e.insert(0, self._step.get("app_path", ""))
            path_e.pack(fill="x", ipady=3)
            self._wvars["app_path"] = path_e
            def _browse_app(e=path_e):
                p = filedialog.askopenfilename(
                    title="选择程序或脚本",
                    filetypes=[("可执行文件","*.exe *.py *.pyw *.bat *.cmd"),("All","*.*")])
                if p:
                    p = os.path.normpath(p)
                    e.delete(0,"end"); e.insert(0, p)
                    self._step["app_path"] = p
            _btn(r, "浏览", T["border"], _browse_app).pack(side="left", padx=4)
            r2 = tk.Frame(b, bg=T["card2"])
            r2.pack(fill="x", pady=2)
            adm_v = tk.BooleanVar(value=bool(self._step.get("run_as_admin", False)))
            self._wvars["run_as_admin"] = adm_v
            tk.Checkbutton(r2, text="以管理员身份启动", variable=adm_v,
                           bg=T["card2"], fg=T["warning"], selectcolor=T["card"],
                           activebackground=T["card2"],
                           font=("Microsoft YaHei", 9)).pack(side="left")
            tk.Label(r2, text="  启动后等待:", bg=T["card2"], fg=T["text2"],
                     font=("Microsoft YaHei", 9)).pack(side="left", padx=(16,0))
            tf2 = tk.Frame(r2, bg=T["border"], padx=1, pady=1)
            tf2.pack(side="left", padx=3)
            wait_e = tk.Entry(tf2, bg=T["card"], fg=T["text"], insertbackground=T["text"],
                               relief="flat", font=("Microsoft YaHei", 9), width=5)
            wait_e.insert(0, str(self._step.get("wait_seconds", 0.0)))
            wait_e.pack(ipady=2)
            self._wvars["wait_seconds"] = wait_e
            tk.Label(r2, text="秒", bg=T["card2"], fg=T["text2"],
                     font=("Microsoft YaHei", 9)).pack(side="left")

        # ── 键盘命令步骤 ──────────────────────────────────
        elif t == "keyboard":
            if "key_actions" not in self._step or not isinstance(self._step.get("key_actions"), list):
                self._step["key_actions"] = []
            self._key_editor = KeyActionsEditor(b, self._step["key_actions"])
            self._key_editor.pack(fill="x", pady=(2, 4))

        # ── 序列点击编辑器（有识别位置的步骤才显示）──────
        if has_match:
            _sep(b)
            # 确保步骤有 click_actions 列表
            if "click_actions" not in self._step or not isinstance(self._step.get("click_actions"), list):
                self._step["click_actions"] = [make_click_action()]
            self._click_editor = ClickActionsEditor(
                b, self._step["click_actions"],
                has_match_pos=True,
                app_ref=self._app,
            )
            self._click_editor.pack(fill="x", pady=(2, 4))

    # ── OCR 区域 / 引擎 ─────────────────────────────────
    def _build_ocr_region(self, parent):
        r = tk.Frame(parent, bg=T["card2"])
        r.pack(fill="x", pady=2)
        tk.Label(r, text="检测区域:", bg=T["card2"], fg=T["text2"],
                 font=("Microsoft YaHei", 9)).pack(side="left")
        self._rlbl = tk.Label(r, text="未设置", bg=T["card2"], fg=T["text2"],
                               font=("Microsoft YaHei", 9))
        self._rlbl.pack(side="left", padx=4)
        _btn(r, "框选区域", T["accent"], self._pick_region).pack(side="left")
        r2 = tk.Frame(parent, bg=T["card2"])
        r2.pack(fill="x", pady=2)
        tk.Label(r2, text="关键词:", bg=T["card2"], fg=T["text2"],
                 font=("Microsoft YaHei", 9)).pack(side="left")
        tf = tk.Frame(r2, bg=T["border"], padx=1, pady=1)
        tf.pack(side="left", padx=4)
        kw = tk.Entry(tf, bg=T["card"], fg=T["text"], insertbackground=T["text"],
                       relief="flat", font=("Microsoft YaHei", 9), width=22)
        kw.pack(ipady=3)
        self._wvars["keywords"] = kw
        tk.Label(r2, text="|=OR  ,=AND", bg=T["card2"], fg=T["text2"],
                 font=("Microsoft YaHei", 8)).pack(side="left")

    def _build_ocr_engine(self, parent):
        r3 = tk.Frame(parent, bg=T["card2"])
        r3.pack(fill="x", pady=2)
        tk.Label(r3, text="OCR引擎:", bg=T["card2"], fg=T["text2"],
                 font=("Microsoft YaHei", 9)).pack(side="left")
        ev = tk.StringVar(value="paddle")
        self._wvars["ocr_engine"] = ev
        for v, txt in [("paddle","PaddleOCR"), ("tesseract","Tesseract")]:
            tk.Radiobutton(r3, text=txt, variable=ev, value=v, bg=T["card2"],
                           fg=T["text"], selectcolor=T["card"],
                           activebackground=T["card2"],
                           font=("Microsoft YaHei", 9)).pack(side="left", padx=4)
        tk.Label(r3, text="  放大:", bg=T["card2"], fg=T["text2"],
                 font=("Microsoft YaHei", 9)).pack(side="left")
        sv2 = tk.StringVar(value="2")
        self._wvars["ocr_scale"] = sv2
        ttk.Combobox(r3, textvariable=sv2, values=["1","2","3","4"],
                     width=2, state="readonly",
                     font=("Microsoft YaHei", 9)).pack(side="left", padx=4)
        tk.Label(r3, text="x", bg=T["card2"], fg=T["text2"],
                 font=("Microsoft YaHei", 9)).pack(side="left")

    # ── 截图区域 + 模板 ──────────────────────────────────
    def _build_img_region(self, parent):
        r = tk.Frame(parent, bg=T["card2"])
        r.pack(fill="x", pady=2)
        tk.Label(r, text="检测区域:", bg=T["card2"], fg=T["text2"],
                 font=("Microsoft YaHei", 9)).pack(side="left")
        self._rlbl = tk.Label(r, text="未设置", bg=T["card2"], fg=T["text2"],
                               font=("Microsoft YaHei", 9))
        self._rlbl.pack(side="left", padx=4)
        _btn(r, "框选区域", T["accent"], self._pick_region).pack(side="left")

        r2 = tk.Frame(parent, bg=T["card2"])
        r2.pack(fill="x", pady=2)
        tk.Label(r2, text="截图为模板:", bg=T["card2"], fg=T["text2"],
                 font=("Microsoft YaHei", 9)).pack(side="left")
        self._tlbl = tk.Label(r2, text="未设置", bg=T["card2"], fg=T["text2"],
                               font=("Microsoft YaHei", 9))
        self._tlbl.pack(side="left", padx=4)

        # 截图按钮（BitBlt截取当前区域保存为模板）
        _btn(r2, "截图区域", T["accent"], self._capture_template).pack(side="left", padx=2)
        _btn(r2, "选择文件", T["border"], self._browse_template).pack(side="left", padx=2)

        r3 = tk.Frame(parent, bg=T["card2"])
        r3.pack(fill="x", pady=2)
        tk.Label(r3, text="匹配阈值:", bg=T["card2"], fg=T["text2"],
                 font=("Microsoft YaHei", 9)).pack(side="left")
        tf = tk.Frame(r3, bg=T["border"], padx=1, pady=1)
        tf.pack(side="left", padx=3)
        thr_e = tk.Entry(tf, bg=T["card"], fg=T["text"], insertbackground=T["text"],
                          relief="flat", font=("Microsoft YaHei", 9), width=4)
        thr_e.insert(0, str(self._step.get("threshold", 80)))
        thr_e.pack(ipady=2)
        self._wvars["threshold"] = thr_e
        tk.Label(r3, text="%  （BitBlt截图，支持独占窗口）",
                 bg=T["card2"], fg=T["text2"],
                 font=("Microsoft YaHei", 8)).pack(side="left")

    def _capture_template(self):
        """截取当前检测区域保存为模板图片"""
        region = self._step.get("region")
        if not region:
            messagebox.showwarning("提示", "请先框选检测区域")
            return
        from flow_runner_p1 import _do_screenshot_blt
        img = _do_screenshot_blt(region)
        if img is None:
            messagebox.showerror("错误", "截图失败")
            return
        d = self._app.cfg.get("scripts_dir", _SCRIPT_DIR)
        os.makedirs(d, exist_ok=True)
        fname = f"template_{int(time.time())}.png"
        path  = os.path.join(d, fname)
        try:
            img.save(path)
            self._step["template_path"] = path
            self._tlbl.config(text=fname, fg=T["success"])
            self._app.log(f"模板已保存: {fname}", "ok")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {e}")

    def _browse_template(self):
        p = filedialog.askopenfilename(
            title="选择模板图片",
            filetypes=[("图片","*.png *.jpg *.bmp *.jpeg"),("All","*.*")])
        if p:
            self._step["template_path"] = p
            self._tlbl.config(text=os.path.basename(p), fg=T["success"])

    # ── 子动作（pre_action）───────────────────────────────
    def _build_pre(self, parent):
        _sep(parent)
        hdr = tk.Frame(parent, bg=T["card2"])
        hdr.pack(fill="x", pady=2)
        tk.Label(hdr, text="每轮前执行子动作:", bg=T["card2"], fg=T["warning"],
                 font=("Microsoft YaHei", 9, "bold")).pack(side="left")
        row = tk.Frame(parent, bg=T["card2"])
        row.pack(fill="x", pady=2)
        tk.Label(row, text="类型:", bg=T["card2"], fg=T["text2"],
                 font=("Microsoft YaHei", 9)).pack(side="left")
        opts = [f"{k}({v})" for k, v in STEP_LABELS.items()]
        sv = tk.StringVar(value="scroll(滚轮)")
        self._wvars["_pre_type"] = sv
        ttk.Combobox(row, textvariable=sv, values=opts, width=22, state="readonly",
                     font=("Microsoft YaHei", 9)).pack(side="left", padx=4)
        _btn(row, "配置", T["border"], self._open_sub).pack(side="left", padx=4)
        self._prelbl = tk.Label(row, text="(未配置)", bg=T["card2"], fg=T["text2"],
                                font=("Microsoft YaHei", 8))
        self._prelbl.pack(side="left")
        pa = self._step.get("pre_action")
        if pa:
            pt = pa.get("type", "")
            sv.set(f"{pt}({STEP_LABELS.get(pt, pt)})")
            self._prelbl.config(text=f"({STEP_LABELS.get(pt, pt)})", fg=T["success"])

    def _open_sub(self):
        type_str = self._wvars.get("_pre_type", tk.StringVar()).get()
        stype    = type_str.split("(")[0].strip()
        pa = self._step.get("pre_action") or make_step(stype)
        if pa.get("type") != stype:
            pa = make_step(stype)
        pa["type"] = stype
        win = tk.Toplevel(self._app)
        win.title(f"配置子动作 — {STEP_LABELS.get(stype, stype)}")
        win.configure(bg=T["bg"])
        win.grab_set()
        win.resizable(False, False)
        f = tk.Frame(win, bg=T["card2"], highlightthickness=1,
                     highlightbackground=T["border"])
        f.pack(fill="both", expand=True, padx=12, pady=12)
        card = StepCard(f, pa, 0, on_delete=lambda i: None,
                        on_move=lambda i, d: None, app=self._app)
        card.pack(fill="x")
        def confirm():
            card.save()
            self._step["pre_action"] = pa
            self._prelbl.config(text=f"({STEP_LABELS.get(stype, stype)})", fg=T["success"])
            win.destroy()
        _btn(win, "确认", T["success"], confirm).pack(pady=6)

    # ── 通用控件行 ───────────────────────────────────────
    def _prow(self, parent, fields):
        for key, label, wtype, opt, default in fields:
            row = tk.Frame(parent, bg=T["card2"])
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label+":", bg=T["card2"], fg=T["text2"],
                     font=("Microsoft YaHei", 9)).pack(side="left")
            if wtype == "entry":
                ew = opt if isinstance(opt, int) else 6
                tf = tk.Frame(row, bg=T["border"], padx=1, pady=1)
                tf.pack(side="left", padx=3)
                e = tk.Entry(tf, bg=T["card"], fg=T["text"], insertbackground=T["text"],
                              relief="flat", font=("Microsoft YaHei", 9), width=ew)
                e.insert(0, str(default) if default is not None else "")
                e.pack(ipady=2)
                self._wvars[key] = e
            elif wtype == "combo":
                sv = tk.StringVar(value=str(default) if default is not None else "")
                self._wvars[key] = sv
                cw = max([len(o) for o in opt]+[6])+1 if opt else 8
                ttk.Combobox(row, textvariable=sv, values=opt, width=cw,
                              state="readonly", font=("Microsoft YaHei", 9)
                              ).pack(side="left", padx=3)
            elif wtype == "check":
                bv = tk.BooleanVar(value=bool(default))
                self._wvars[key] = bv
                tk.Checkbutton(row, text="", variable=bv, bg=T["card2"], fg=T["text"],
                                selectcolor=T["card"], activebackground=T["card2"],
                                font=("Microsoft YaHei", 9)).pack(side="left", padx=3)

    def _crow(self, parent, xk, yk, label):
        row = tk.Frame(parent, bg=T["card2"])
        row.pack(fill="x", pady=2)
        tk.Label(row, text=label+":", bg=T["card2"], fg=T["text2"],
                 font=("Microsoft YaHei", 9)).pack(side="left")
        for key, txt in [(xk,"X"), (yk,"Y")]:
            tk.Label(row, text=txt, bg=T["card2"], fg=T["text2"],
                     font=("Microsoft YaHei", 9)).pack(side="left", padx=(4,0))
            tf = tk.Frame(row, bg=T["border"], padx=1, pady=1)
            tf.pack(side="left", padx=2)
            e = tk.Entry(tf, bg=T["card"], fg=T["text"], insertbackground=T["text"],
                          relief="flat", font=("Microsoft YaHei", 9), width=6)
            e.insert(0, str(self._step.get(key, 0)))
            e.pack(ipady=2)
            self._wvars[key] = e
        _btn(row, "点选坐标", T["border"],
             lambda xk=xk, yk=yk: self._pick_coord(xk, yk)).pack(side="left", padx=6)

    # ── 区域/坐标选取 ────────────────────────────────────
    def _pick_region(self):
        self._app.withdraw()
        def cb(x1, y1, x2, y2):
            self._step["region"] = [x1, y1, x2, y2]
            self._rlbl.config(text=f"({x1},{y1})-({x2},{y2})", fg=T["success"])
            self._app.deiconify()
        def cancel():
            self._app.deiconify()
        self._app.after(200, lambda: pick_region(cb, cancel_callback=cancel))

    def _pick_coord(self, xk, yk):
        self._app.withdraw()
        def cb(x, y):
            for key, val in [(xk, x), (yk, y)]:
                w = self._wvars.get(key)
                if w:
                    w.delete(0, "end"); w.insert(0, str(val))
            self._app.deiconify()
        def cancel():
            self._app.deiconify()
        self._app.after(200, lambda: pick_coord(cb, cancel_callback=cancel))

    def _browse_script(self):
        d = self._app.cfg.get("scripts_dir", "") or _SCRIPT_DIR
        p = filedialog.askopenfilename(title="选择录制脚本", initialdir=d,
                                        filetypes=[("JSON脚本","*.json"),("All","*.*")])
        if p:
            self._step["script_path"] = p
            self._slbl.config(text=os.path.basename(p), fg=T["success"])

    def _toggle(self):
        self._exp = not self._exp
        if self._exp:
            self._body.pack(fill="x", padx=10, pady=(0,6))
            self._arrow.config(text="▼")
        else:
            self._body.pack_forget()
            self._arrow.config(text="▶")

    def _load(self):
        s = self._step
        for key, w in self._wvars.items():
            if key.startswith("_"): continue
            val = s.get(key)
            if val is None: continue
            try:
                if isinstance(w, tk.Entry):
                    w.delete(0, "end"); w.insert(0, str(val))
                elif isinstance(w, tk.StringVar):
                    w.set(str(val))
                elif isinstance(w, tk.BooleanVar):
                    w.set(bool(val))
            except: pass

        r = s.get("region")
        if r and hasattr(self, "_rlbl"):
            self._rlbl.config(text=f"({r[0]},{r[1]})-({r[2]},{r[3]})", fg=T["success"])
        sp = s.get("script_path", "")
        if sp and hasattr(self, "_slbl"):
            self._slbl.config(text=os.path.basename(sp), fg=T["success"])
        tp = s.get("template_path", "")
        if tp and hasattr(self, "_tlbl"):
            self._tlbl.config(text=os.path.basename(tp), fg=T["success"])

    def save(self):
        self._step["name"] = self._name_var.get()
        # 序列点击编辑器
        if self._click_editor:
            self._click_editor.save()
        # 键盘序列编辑器
        if self._key_editor:
            self._key_editor.save()
        # 普通字段
        for key, w in self._wvars.items():
            if key.startswith("_"): continue
            try:
                orig = self._step.get(key)
                if isinstance(w, tk.Entry):
                    raw = w.get().strip()
                    if isinstance(orig, bool):
                        self._step[key] = raw.lower() in ("1","true","yes")
                    elif key in ("delta_mul", "seconds", "duration", "interval",
                                 "check_interval", "retry_interval", "pre_delay",
                                 "wait_seconds", "speed", "max_gap"):
                        # 这些字段始终保存为 float，兼容旧配置中存为 int 的情况
                        try: self._step[key] = float(raw)
                        except: pass
                    elif isinstance(orig, int):
                        self._step[key] = int(float(raw))
                    elif isinstance(orig, float):
                        self._step[key] = float(raw)
                    else:
                        self._step[key] = raw
                elif isinstance(w, tk.StringVar):
                    self._step[key] = w.get()
                elif isinstance(w, tk.BooleanVar):
                    self._step[key] = w.get()
            except: pass


# ══════════════════════════════════════════════════════════
#  主应用
# ══════════════════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("不思议挂机 — 自动化流程执行器")
        self.configure(bg=T["bg"])
        self.minsize(1200, 720)
        self.cfg = load_config()
        self.cfg.setdefault("hotkey_start",      "F6")
        self.cfg.setdefault("hotkey_stop",        "F7")
        self.cfg.setdefault("hotkey_pause",       "F8")
        self.cfg.setdefault("hotkey_rec_toggle",  "F9")
        if not self.cfg.get("scripts_dir"):
            self.cfg["scripts_dir"] = os.path.join(_SCRIPT_DIR, "scripts")
        os.makedirs(self.cfg["scripts_dir"], exist_ok=True)
        # 确保至少有一个流程组
        if not self.cfg.get("flow_groups"):
            group_add(self.cfg, "默认组")

        self._runner       = None
        self._recorder     = RecorderEngine()
        self._sel_group    = 0       # 当前选中组索引
        self._sel_flow     = -1      # 当前选中组内流程索引
        self._step_cards   = []
        self.geometry(self.cfg.get("window_geometry", "1280x800+80+50"))
        self._build_ui()
        self._refresh_tree()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._start_hotkey_listener()

    # ══════════════════════════════════════════════════════
    #  UI 构建
    # ══════════════════════════════════════════════════════

    def _build_ui(self):
        # 顶部工具栏
        top = tk.Frame(self, bg=T["sidebar"], pady=6)
        top.pack(fill="x")
        _btn(top, "▶ 启动",  T["success"], self._start).pack(side="left", padx=(12,4))
        _btn(top, "⏸ 暂停",  T["warning"], self._pause).pack(side="left", padx=4)
        _btn(top, "■ 停止",  T["danger"],  self._stop ).pack(side="left", padx=4)
        tk.Frame(top, bg=T["border"], width=1).pack(side="left", fill="y", padx=10, pady=4)

        tk.Label(top, text="从:", bg=T["sidebar"], fg=T["text2"],
                 font=("Microsoft YaHei", 9)).pack(side="left")
        # 组选择
        self._start_grp_var = tk.StringVar()
        self._start_grp_cb  = ttk.Combobox(top, textvariable=self._start_grp_var,
                                            values=[], width=12, state="readonly",
                                            font=("Microsoft YaHei", 9))
        self._start_grp_cb.pack(side="left", padx=2)
        self._start_grp_cb.bind("<<ComboboxSelected>>", lambda e: self._on_start_grp_change())
        tk.Label(top, text="-", bg=T["sidebar"], fg=T["text2"],
                 font=("Microsoft YaHei", 10)).pack(side="left")
        # 流程选择
        self._start_flow_var = tk.StringVar()
        self._start_flow_cb  = ttk.Combobox(top, textvariable=self._start_flow_var,
                                             values=[], width=16, state="readonly",
                                             font=("Microsoft YaHei", 9))
        self._start_flow_cb.pack(side="left", padx=2)
        tk.Label(top, text="开始", bg=T["sidebar"], fg=T["text2"],
                 font=("Microsoft YaHei", 9)).pack(side="left", padx=(2,8))

        tk.Frame(top, bg=T["border"], width=1).pack(side="left", fill="y", padx=6, pady=4)
        self._dot  = tk.Label(top, text="●", bg=T["sidebar"], fg=T["text2"],
                               font=("Microsoft YaHei", 12))
        self._dot.pack(side="left")
        self._stxt = tk.Label(top, text="未运行", bg=T["sidebar"], fg=T["text2"],
                               font=("Microsoft YaHei", 9))
        self._stxt.pack(side="left", padx=4)
        self._llbl = tk.Label(top, text="", bg=T["sidebar"], fg=T["accent"],
                               font=("Microsoft YaHei", 9))
        self._llbl.pack(side="left", padx=12)
        _btn(top, "⚙ 设置", T["border"], self._settings).pack(side="right", padx=12)

        # 主体
        body = tk.Frame(self, bg=T["bg"])
        body.pack(fill="both", expand=True)
        self._build_sidebar(body)
        right = tk.Frame(body, bg=T["bg"])
        right.pack(side="left", fill="both", expand=True)
        self._build_editor(right)
        self._build_log(right)

    def _build_sidebar(self, parent):
        sb = tk.Frame(parent, bg=T["sidebar"], width=240)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        # 标题行
        hdr = tk.Frame(sb, bg=T["sidebar"])
        hdr.pack(fill="x", padx=8, pady=(8,4))
        tk.Label(hdr, text="流程组", bg=T["sidebar"], fg=T["text"],
                 font=("Microsoft YaHei", 10, "bold")).pack(side="left")
        _btn(hdr, "+ 组", T["accent"], self._add_group).pack(side="right", padx=2)

        # Treeview（流程组树）
        style = ttk.Style()
        style.theme_use("default")
        style.configure("FR.Treeview",
                         background=T["lb"], foreground=T["text"],
                         fieldbackground=T["lb"],
                         font=("Microsoft YaHei", 9),
                         rowheight=22)
        style.configure("FR.Treeview.Heading",
                         background=T["card"], foreground=T["text2"],
                         font=("Microsoft YaHei", 9))
        style.map("FR.Treeview",
                  background=[("selected", T["active"])],
                  foreground=[("selected", T["text"])])

        tf = tk.Frame(sb, bg=T["sidebar"])
        tf.pack(fill="both", expand=True, padx=8, pady=4)
        self._tree = ttk.Treeview(tf, style="FR.Treeview",
                                   selectmode="browse", show="tree")
        vsb = ttk.Scrollbar(tf, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(side="left", fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.bind("<Button-3>",         self._on_tree_rightclick)
        self._tree.bind("<Double-1>",         self._on_tree_dblclick)
        # 拖拽排序（同组内）
        # _drag_line: 1px 高的蓝色 Frame，放在 tf（Treeview 父容器）中，
        # 用 place() 精确定位作为插入线，不拦截鼠标事件
        self._drag_line = tk.Frame(tf, bg=T["accent"], height=2)
        self._drag_data = {}   # {iid, gi, fi, target_iid, insert_before}
        self._tree.bind("<ButtonPress-1>",   self._drag_start)
        self._tree.bind("<B1-Motion>",       self._drag_motion)
        self._tree.bind("<ButtonRelease-1>", self._drag_release)

        # 组/流程操作按钮
        br = tk.Frame(sb, bg=T["sidebar"])
        br.pack(fill="x", padx=8, pady=(0,4))
        _btn(br, "+ 流程", T["accent"],  self._add_flow).pack(side="left")
        _btn(br, "删除",   T["danger"],  self._del_selected).pack(side="left", padx=4)
        _btn(br, "↑",      T["border"],  lambda: self._mv_flow(-1)).pack(side="left")
        _btn(br, "↓",      T["border"],  lambda: self._mv_flow(+1)).pack(side="left", padx=2)
        _btn(br, "串联",   T["border"],  self._chain_dlg).pack(side="left", padx=2)

        _sep(sb)

        # 录制脚本区
        tk.Label(sb, text="录制脚本", bg=T["sidebar"], fg=T["text"],
                 font=("Microsoft YaHei", 10, "bold"), pady=4).pack(fill="x", padx=12)
        self._rec_btn = _btn(sb, "● 开始录制", T["danger"], self._toggle_rec)
        self._rec_btn.pack(fill="x", padx=8, pady=2)
        nr = tk.Frame(sb, bg=T["sidebar"])
        nr.pack(fill="x", padx=8, pady=2)
        tk.Label(nr, text="脚本名:", bg=T["sidebar"], fg=T["text2"],
                 font=("Microsoft YaHei", 9)).pack(side="left")
        tf2 = tk.Frame(nr, bg=T["border"], padx=1, pady=1)
        tf2.pack(side="left", padx=4)
        self._rec_name_e = tk.Entry(tf2, bg=T["card"], fg=T["text"],
                                     insertbackground=T["text"], relief="flat",
                                     font=("Microsoft YaHei", 9), width=12)
        self._rec_name_e.insert(0, "脚本1")
        self._rec_name_e.pack(ipady=2)
        self._rec_stat = tk.Label(sb, text="未录制", bg=T["sidebar"], fg=T["text2"],
                                   font=("Microsoft YaHei", 8))
        self._rec_stat.pack(anchor="w", padx=12)
        tk.Label(sb, text="已保存脚本:", bg=T["sidebar"], fg=T["text2"],
                 font=("Microsoft YaHei", 8), pady=2).pack(anchor="w", padx=12)
        sf = tk.Frame(sb, bg=T["sidebar"])
        sf.pack(fill="both", expand=True, padx=8)
        self._script_lb = tk.Listbox(sf, bg=T["lb"], fg=T["lt"],
                                      selectbackground=T["active"],
                                      font=("Microsoft YaHei", 8),
                                      relief="flat", bd=0, activestyle="none", height=5)
        self._script_lb.pack(fill="both", expand=True)
        sbr = tk.Frame(sb, bg=T["sidebar"])
        sbr.pack(fill="x", padx=8, pady=2)
        _btn(sbr, "刷新", T["border"], self._refresh_scripts).pack(side="left")
        _btn(sbr, "删除", T["danger"],  self._del_script).pack(side="left", padx=4)
        self._refresh_scripts()

    def _build_editor(self, parent):
        outer = tk.Frame(parent, bg=T["bg"])
        outer.pack(fill="both", expand=True)
        # 流程信息头
        hdr = tk.Frame(outer, bg=T["card2"])
        hdr.pack(fill="x", padx=10, pady=(6,2))
        self._fnlbl = tk.Label(hdr, text="(未选择流程)", bg=T["card2"], fg=T["text"],
                                font=("Microsoft YaHei", 10, "bold"))
        self._fnlbl.pack(side="left", padx=10, pady=6)
        tk.Label(hdr, text="循环次数:", bg=T["card2"], fg=T["text2"],
                 font=("Microsoft YaHei", 9)).pack(side="left", padx=(20,0))
        tf1 = tk.Frame(hdr, bg=T["border"], padx=1, pady=1)
        tf1.pack(side="left", padx=4)
        self._loop_e = tk.Entry(tf1, bg=T["card2"], fg=T["text"], insertbackground=T["text"],
                                 relief="flat", font=("Microsoft YaHei", 9), width=4)
        self._loop_e.insert(0, "1")
        self._loop_e.pack(ipady=3)
        tk.Label(hdr, text="(0=无限)", bg=T["card2"], fg=T["text2"],
                 font=("Microsoft YaHei", 8)).pack(side="left")
        tk.Label(hdr, text="  执行前等待:", bg=T["card2"], fg=T["text2"],
                 font=("Microsoft YaHei", 9)).pack(side="left", padx=(12,0))
        tf2 = tk.Frame(hdr, bg=T["border"], padx=1, pady=1)
        tf2.pack(side="left", padx=4)
        self._pd_e = tk.Entry(tf2, bg=T["card2"], fg=T["text"], insertbackground=T["text"],
                               relief="flat", font=("Microsoft YaHei", 9), width=4)
        self._pd_e.insert(0, "0")
        self._pd_e.pack(ipady=3)
        tk.Label(hdr, text="秒", bg=T["card2"], fg=T["text2"],
                 font=("Microsoft YaHei", 9)).pack(side="left")
        _btn(hdr, "保存流程", T["success"], lambda: self._save_flow(save_to_disk=True)).pack(side="right", padx=10)

        # 添加步骤栏
        ar = tk.Frame(outer, bg=T["bg"])
        ar.pack(fill="x", padx=10, pady=4)
        tk.Label(ar, text="添加步骤:", bg=T["bg"], fg=T["text2"],
                 font=("Microsoft YaHei", 9)).pack(side="left")
        self._new_sv = tk.StringVar(value="ocr_click(OCR点击)")
        opts = [f"{k}({v})" for k, v in STEP_LABELS.items()]
        ttk.Combobox(ar, textvariable=self._new_sv, values=opts,
                     width=22, state="readonly",
                     font=("Microsoft YaHei", 9)).pack(side="left", padx=6)
        _btn(ar, "+ 添加", T["accent"], self._add_step).pack(side="left")

        # 步骤滚动区
        so = tk.Frame(outer, bg=T["bg"])
        so.pack(fill="both", expand=True, padx=10, pady=4)
        cv = tk.Canvas(so, bg=T["bg"], bd=0, highlightthickness=0)
        vb = ttk.Scrollbar(so, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=vb.set)
        vb.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)
        self._sf  = tk.Frame(cv, bg=T["bg"])
        self._sw  = cv.create_window((0,0), window=self._sf, anchor="nw")
        self._sf.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>",      lambda e: cv.itemconfig(self._sw, width=e.width))
        cv.bind_all("<MouseWheel>", lambda e: cv.yview_scroll(int(-1*(e.delta/120)), "units"))
        self._cv = cv

    def _build_log(self, parent):
        lf = tk.Frame(parent, bg=T["bg"])
        lf.pack(fill="x", side="bottom", padx=10, pady=(0,8))
        lh = tk.Frame(lf, bg=T["bg"])
        lh.pack(fill="x")
        tk.Label(lh, text="运行日志", bg=T["bg"], fg=T["text2"],
                 font=("Microsoft YaHei", 9)).pack(side="left")
        _btn(lh, "清空", T["border"], self._clear_log).pack(side="right")
        self._log_t = tk.Text(lf, height=9, bg=T["lb"], fg=T["text"],
                               font=("Consolas", 9), relief="flat",
                               state="disabled", wrap="word")
        self._log_t.pack(fill="x")
        for tag, fg in [("ok",T["lo"]),("err",T["le"]),("warn",T["lw"]),("info",T["text"])]:
            self._log_t.tag_config(tag, foreground=fg)

    # ══════════════════════════════════════════════════════
    #  树形列表操作
    # ══════════════════════════════════════════════════════

    def _tree_iid_group(self, gi):
        return f"grp_{gi}"

    def _tree_iid_flow(self, gi, fi):
        return f"flow_{gi}_{fi}"

    def _refresh_tree(self):
        """重建整棵树"""
        # 记住当前展开状态
        expanded = set()
        for item in self._tree.get_children():
            if self._tree.item(item, "open"):
                expanded.add(item)

        self._tree.delete(*self._tree.get_children())
        groups = self.cfg.get("flow_groups", [])

        for gi, grp in enumerate(groups):
            giid = self._tree_iid_group(gi)
            gname = grp.get("name", f"组{gi+1}")
            self._tree.insert("", "end", iid=giid,
                               text=f"📁 {gname}",
                               open=(giid in expanded or len(groups) <= 3))
            flows = grp.get("flows", [])
            for fi, f in enumerate(flows):
                fiid = self._tree_iid_flow(gi, fi)
                nf   = int(f.get("next_flow", -1))
                sfx  = f" → {nf+1}" if 0 <= nf < len(flows) else ""
                lc   = f.get("loop_count", 1)
                self._tree.insert(giid, "end", iid=fiid,
                                   text=f"  [{fi+1}] {f.get('name','')} ×{lc}{sfx}")

        # 恢复选择
        if self._sel_flow >= 0:
            fiid = self._tree_iid_flow(self._sel_group, self._sel_flow)
            try:
                self._tree.selection_set(fiid)
                self._tree.see(fiid)
            except Exception:
                pass

        self._refresh_start_combos()

    def _refresh_start_combos(self):
        groups = self.cfg.get("flow_groups", [])
        grp_names = [f"{i+1}: {g.get('name','')}" for i, g in enumerate(groups)]
        self._start_grp_cb["values"] = grp_names or ["1: 默认组"]
        if grp_names:
            # 保持当前选中或设第一个
            cur = self._start_grp_var.get()
            if cur not in grp_names:
                self._start_grp_var.set(grp_names[0])
        self._on_start_grp_change()

    def _on_start_grp_change(self):
        groups = self.cfg.get("flow_groups", [])
        try:
            gi = int(self._start_grp_var.get().split(":")[0]) - 1
        except Exception:
            gi = 0
        if not (0 <= gi < len(groups)):
            gi = 0
        flows = groups[gi].get("flows", []) if gi < len(groups) else []
        flow_names = [f"{i+1}: {f.get('name','')}" for i, f in enumerate(flows)]
        self._start_flow_cb["values"] = flow_names or ["1"]
        if flow_names:
            self._start_flow_var.set(flow_names[0])

    def _on_tree_select(self, e=None):
        sel = self._tree.selection()
        if not sel: return
        iid = sel[0]
        if iid.startswith("flow_"):
            _, gi, fi = iid.split("_")
            gi, fi = int(gi), int(fi)
           # self._save_flow()
            self._sel_group = gi
            self._sel_flow  = fi
            self._load_flow(gi, fi)
        elif iid.startswith("grp_"):
            # 点组不做步骤加载
            gi = int(iid.split("_")[1])
            self._sel_group = gi
            # 不改 sel_flow，保持上次选中

    def _on_tree_dblclick(self, e=None):
        """双击组名：改名"""
        sel = self._tree.selection()
        if not sel: return
        iid = sel[0]
        if not iid.startswith("grp_"): return
        gi = int(iid.split("_")[1])
        self._rename_group_dlg(gi)

    def _on_tree_rightclick(self, e):
        """右键菜单（组节点 + 流程节点）"""
        iid = self._tree.identify_row(e.y)
        if not iid: return
        self._tree.selection_set(iid)

        menu = tk.Menu(self, tearoff=0, bg=T["card"], fg=T["text"],
                       activebackground=T["active"], activeforeground=T["text"],
                       font=("Microsoft YaHei", 9))

        if iid.startswith("grp_"):
            gi = int(iid.split("_")[1])
            menu.add_command(label="重命名",
                             command=lambda: self._rename_group_dlg(gi))
            menu.add_separator()
            menu.add_command(label="删除此组",
                             command=lambda: self._del_group(gi))
            menu.post(e.x_root, e.y_root)
            return

        if not iid.startswith("flow_"): return
        _, gi, fi = iid.split("_")
        gi, fi = int(gi), int(fi)

        groups = self.cfg.get("flow_groups", [])
        other_groups = [(i, g.get("name", f"组{i+1}"))
                         for i, g in enumerate(groups) if i != gi]
        cur_grp_name = groups[gi].get("name", f"组{gi+1}") if gi < len(groups) else ""

        # 重命名
        menu.add_command(label="重命名",
                         command=lambda: self._rename_flow_dlg(gi, fi))
        menu.add_separator()

        # 复制到当前组（末尾追加一份）
        menu.add_command(label=f"复制到当前组（{cur_grp_name}）",
                         command=lambda: self._copy_flow_in_group(gi, fi))

        if other_groups:
            move_menu = tk.Menu(menu, tearoff=0, bg=T["card"], fg=T["text"],
                                activebackground=T["active"], activeforeground=T["text"],
                                font=("Microsoft YaHei", 9))
            copy_menu = tk.Menu(menu, tearoff=0, bg=T["card"], fg=T["text"],
                                activebackground=T["active"], activeforeground=T["text"],
                                font=("Microsoft YaHei", 9))
            for dst_gi, dst_name in other_groups:
                move_menu.add_command(
                    label=dst_name,
                    command=lambda dg=dst_gi: self._move_flow_to(gi, fi, dg, copy_mode=False))
                copy_menu.add_command(
                    label=dst_name,
                    command=lambda dg=dst_gi: self._move_flow_to(gi, fi, dg, copy_mode=True))
            menu.add_cascade(label="移动到...", menu=move_menu)
            menu.add_cascade(label="复制到...", menu=copy_menu)

        menu.add_separator()
        menu.add_command(label="删除此流程", command=lambda: self._del_flow(gi, fi))
        menu.post(e.x_root, e.y_root)

    def _move_flow_to(self, src_gi, src_fi, dst_gi, copy_mode):
        self._save_flow()
        pos = flow_move_to_group(self.cfg, src_gi, src_fi, dst_gi, copy_mode=copy_mode)
        if pos is None:
            messagebox.showerror("错误", "移动/复制失败")
            return
        verb = "复制" if copy_mode else "移动"
        dst_name = self.cfg["flow_groups"][dst_gi].get("name", f"组{dst_gi+1}")
        self.log(f"已{verb}流程到「{dst_name}」", "ok")
        # 如果是移动，当前选中流程消失了，重置
        if not copy_mode:
            self._sel_flow = -1
            self._rebuild_cards([])
            self._fnlbl.config(text="(未选择流程)")
        self._refresh_tree()

    # ══════════════════════════════════════════════════════
    #  流程操作
    # ══════════════════════════════════════════════════════

    def _rename_group_dlg(self, gi):
        groups = self.cfg.get("flow_groups", [])
        if not (0 <= gi < len(groups)): return
        cur_name = groups[gi].get("name", f"组{gi+1}")
        win = tk.Toplevel(self)
        win.title("重命名流程组")
        win.configure(bg=T["bg"])
        win.grab_set()
        win.resizable(False, False)
        f = tk.Frame(win, bg=T["card"], padx=16, pady=12)
        f.pack(fill="both", expand=True, padx=12, pady=12)
        tk.Label(f, text="组名:", bg=T["card"], fg=T["text"],
                 font=("Microsoft YaHei", 9)).pack(anchor="w")
        tf = tk.Frame(f, bg=T["border"], padx=1, pady=1)
        tf.pack(fill="x", pady=4)
        e = tk.Entry(tf, bg=T["card2"], fg=T["text"], insertbackground=T["text"],
                      relief="flat", font=("Microsoft YaHei", 9))
        e.insert(0, cur_name); e.pack(fill="x", ipady=3)
        def ok():
            name = e.get().strip()
            if name:
                group_rename(self.cfg, gi, name)
                self._refresh_tree()
            win.destroy()
        _btn(f, "确认", T["success"], ok).pack(anchor="w", pady=6)
        e.bind("<Return>", lambda ev: ok())
        e.focus_set(); e.select_range(0, "end")

    def _rename_flow_dlg(self, gi, fi):
        groups = self.cfg.get("flow_groups", [])
        if not (0 <= gi < len(groups)): return
        flows = groups[gi].get("flows", [])
        if not (0 <= fi < len(flows)): return
        cur_name = flows[fi].get("name", f"流程{fi+1}")
        win = tk.Toplevel(self)
        win.title("重命名流程")
        win.configure(bg=T["bg"])
        win.grab_set()
        win.resizable(False, False)
        f = tk.Frame(win, bg=T["card"], padx=16, pady=12)
        f.pack(fill="both", expand=True, padx=12, pady=12)
        tk.Label(f, text="流程名:", bg=T["card"], fg=T["text"],
                 font=("Microsoft YaHei", 9)).pack(anchor="w")
        tf = tk.Frame(f, bg=T["border"], padx=1, pady=1)
        tf.pack(fill="x", pady=4)
        e = tk.Entry(tf, bg=T["card2"], fg=T["text"], insertbackground=T["text"],
                      relief="flat", font=("Microsoft YaHei", 9))
        e.insert(0, cur_name); e.pack(fill="x", ipady=3)
        def ok():
            name = e.get().strip()
            if name:
                flows[fi]["name"] = name
                # 同步更新编辑器头部
                if self._sel_group == gi and self._sel_flow == fi:
                    grp_name = groups[gi].get("name", f"组{gi+1}")
                    self._fnlbl.config(
                        text=f"[{gi+1}-{fi+1}] {grp_name} / {name}")
                self._refresh_tree()
            win.destroy()
        _btn(f, "确认", T["success"], ok).pack(anchor="w", pady=6)
        e.bind("<Return>", lambda ev: ok())
        e.focus_set(); e.select_range(0, "end")

    def _copy_flow_in_group(self, gi, fi):
        """复制流程到当前组末尾"""
        import copy as _copy
        groups = self.cfg.get("flow_groups", [])
        if not (0 <= gi < len(groups)): return
        flows = groups[gi].get("flows", [])
        if not (0 <= fi < len(flows)): return
        self._save_flow()
        new_flow = _copy.deepcopy(flows[fi])
        new_flow["next_flow"] = -1   # 复制品不继承串联
        new_flow["name"] = new_flow.get("name", f"流程{fi+1}") + "_副本"
        flows.append(new_flow)
        new_fi = len(flows) - 1
        self.log(f"已复制流程「{flows[fi].get('name','')}」到当前组末尾", "ok")
        self._refresh_tree()
        # 选中并加载复制品
        self._sel_flow = new_fi
        self._load_flow(gi, new_fi)
        fiid = self._tree_iid_flow(gi, new_fi)
        try:
            self._tree.selection_set(fiid)
            self._tree.see(fiid)
        except Exception:
            pass


    # ══════════════════════════════════════════════════════
    #  Treeview 拖拽排序（同组内流程）
    # ══════════════════════════════════════════════════════
    # 实现要点：
    #   - _drag_line 是一个 1px 高的 Frame，放在 Treeview 父容器(tf)里，
    #     用 place() 按像素定位，不会拦截鼠标事件
    #   - motion/release 全部绑定在 Treeview 本身，坐标始终是 Treeview 相对坐标
    #   - 通过 winfo_rooty() 把 Treeview 相对坐标转换为屏幕绝对坐标，
    #     再减去父容器 rooty 得到 place y 值，让插入线出现在正确位置

    def _drag_start(self, e):
        iid = self._tree.identify_row(e.y)
        self._drag_data.clear()
        if not iid or not iid.startswith("flow_"):
            return
        _, gi, fi = iid.split("_")
        self._drag_data = {"iid": iid, "gi": int(gi), "fi": int(fi)}
        # 隐藏插入线
        self._drag_line.place_forget()

    def _drag_motion(self, e):
        d = self._drag_data
        if not d.get("iid"):
            return

        # identify_row 用 Treeview 相对 y
        target_iid = self._tree.identify_row(e.y)
        if not target_iid:
            self._drag_line.place_forget()
            return

        # 只允许同组
        if target_iid.startswith("flow_"):
            _, tgi, _ = target_iid.split("_")
            if int(tgi) != d["gi"]:
                self._drag_line.place_forget()
                return
        elif target_iid.startswith("grp_"):
            tgi = int(target_iid.split("_")[1])
            if tgi != d["gi"]:
                self._drag_line.place_forget()
                return
        else:
            self._drag_line.place_forget()
            return

        bbox = self._tree.bbox(target_iid)
        if not bbox:
            self._drag_line.place_forget()
            return
        bx, by, bw, bh = bbox
        insert_before = (e.y < by + bh // 2)
        line_y_in_tree = by if insert_before else by + bh

        # 把 Treeview 相对 y 转成父容器 tf 相对 y
        tree_root_y  = self._tree.winfo_rooty()
        tf_root_y    = self._drag_line.master.winfo_rooty()
        line_y_in_tf = tree_root_y - tf_root_y + line_y_in_tree

        tw = self._drag_line.master.winfo_width()
        self._drag_line.place(x=2, y=line_y_in_tf - 1,
                               width=tw - 4, height=2)
        self._drag_line.lift()

        d["target_iid"]   = target_iid
        d["insert_before"] = insert_before

    def _drag_release(self, e):
        d = self._drag_data
        self._drag_line.place_forget()

        if not d.get("iid"):
            self._drag_data.clear()
            return

        src_gi       = d["gi"]
        src_fi       = d["fi"]
        target_iid   = d.get("target_iid")
        insert_before = d.get("insert_before", True)

        self._drag_data.clear()

        if not target_iid:
            return

        # 解析目标索引
        if target_iid.startswith("flow_"):
            _, tgi, tfi = target_iid.split("_")
            tgi, tfi = int(tgi), int(tfi)
        elif target_iid.startswith("grp_"):
            tgi = int(target_iid.split("_")[1])
            tfi = None
        else:
            return

        if tgi != src_gi:
            return

        if tfi is None:
            dst_fi = 0
        else:
            dst_fi = tfi if insert_before else tfi + 1

        # 原地不动
        if dst_fi == src_fi or dst_fi == src_fi + 1:
            return

        self._save_flow()

        # 逐步相邻交换，flow_move 同时修正 next_flow 引用
        from flow_runner_p2 import flow_move as _fm
        if dst_fi > src_fi:
            for i in range(src_fi, dst_fi - 1):
                _fm(self.cfg, i, +1, src_gi)
            new_fi = dst_fi - 1
        else:
            for i in range(src_fi, dst_fi, -1):
                _fm(self.cfg, i, -1, src_gi)
            new_fi = dst_fi

        self._sel_flow = new_fi
        self._refresh_tree()
        self._load_flow(src_gi, new_fi)
        fiid = self._tree_iid_flow(src_gi, new_fi)
        try:
            self._tree.selection_set(fiid)
            self._tree.see(fiid)
        except Exception:
            pass
        self.log(f"流程已移动到第 {new_fi+1} 位", "ok")


    def _add_group(self):
        self._save_flow()
        gi = group_add(self.cfg)
        self._sel_group = gi
        self._refresh_tree()
        self.log(f"添加组[{gi+1}]", "ok")
        # 触发双击改名
        iid = self._tree_iid_group(gi)
        self._tree.selection_set(iid)
        self._tree.see(iid)
        self.after(100, lambda: self._on_tree_dblclick())

    def _add_flow(self):
        gi = self._sel_group
        groups = self.cfg.get("flow_groups", [])
        if not (0 <= gi < len(groups)):
            messagebox.showwarning("提示", "请先选择一个流程组")
            return
        self._save_flow()
        n = len(groups[gi].get("flows", []))
        fi = flow_add(self.cfg, f"流程{n+1}", gi)
        self._sel_flow = fi
        self._refresh_tree()
        self._load_flow(gi, fi)
        self.log(f"添加流程[{gi+1}-{fi+1}]", "ok")

    def _del_selected(self):
        sel = self._tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择流程或流程组")
            return
        iid = sel[0]
        if iid.startswith("flow_"):
            _, gi, fi = iid.split("_")
            self._del_flow(int(gi), int(fi))
        elif iid.startswith("grp_"):
            gi = int(iid.split("_")[1])
            self._del_group(gi)

    def _del_group(self, gi):
        groups = self.cfg.get("flow_groups", [])
        if not (0 <= gi < len(groups)): return
        name = groups[gi].get("name", f"组{gi+1}")
        n    = len(groups[gi].get("flows", []))
        if n and not messagebox.askyesno("确认", f"删除组「{name}」及其{n}个流程？"):
            return
        group_delete(self.cfg, gi)
        if not self.cfg.get("flow_groups"):
            group_add(self.cfg, "默认组")
        self._sel_group = 0
        self._sel_flow  = -1
        self._rebuild_cards([])
        self._fnlbl.config(text="(未选择流程)")
        self._refresh_tree()
        self.log(f"删除组「{name}」", "warn")

    def _del_flow(self, gi, fi):
        groups = self.cfg.get("flow_groups", [])
        if not (0 <= gi < len(groups)): return
        flows = groups[gi].get("flows", [])
        if not (0 <= fi < len(flows)): return
        name = flows[fi].get("name", "")
        if not messagebox.askyesno("确认", f"删除流程「{name}」？"): return
        flow_delete(self.cfg, fi, gi)
        self._sel_flow  = -1
        self._rebuild_cards([])
        self._fnlbl.config(text="(未选择流程)")
        self._refresh_tree()
        self.log(f"删除流程「{name}」", "warn")

    def _mv_flow(self, d):
        if self._sel_flow < 0: return
        self._save_flow()
        flow_move(self.cfg, self._sel_flow, d, self._sel_group)
        self._sel_flow += d
        self._refresh_tree()
        self._load_flow(self._sel_group, self._sel_flow)

    def _chain_dlg(self):
        gi, fi = self._sel_group, self._sel_flow
        if fi < 0:
            messagebox.showwarning("提示", "请先选择流程")
            return
        groups = self.cfg.get("flow_groups", [])
        if not (0 <= gi < len(groups)): return
        flows = groups[gi].get("flows", [])
        if not (0 <= fi < len(flows)): return
        f = flows[fi]
        win = tk.Toplevel(self)
        win.title("串联设置（组内）")
        win.configure(bg=T["bg"])
        win.grab_set()
        win.resizable(False, False)
        fr = tk.Frame(win, bg=T["card"], padx=16, pady=12)
        fr.pack(fill="both", expand=True, padx=12, pady=12)
        tk.Label(fr, text=f"「{f.get('name','')}」完成后触发（组内）：",
                 bg=T["card"], fg=T["text"], font=("Microsoft YaHei", 9)
                 ).pack(anchor="w", pady=4)
        opts = ["无（任务结束）"] + [
            f"{i+1}: {ff.get('name','')}"
            for i, ff in enumerate(flows) if i != fi]
        sv = tk.StringVar()
        nf = int(f.get("next_flow", -1))
        sv.set(f"{nf+1}: {flows[nf].get('name','')}"
               if 0 <= nf < len(flows) else "无（任务结束）")
        ttk.Combobox(fr, textvariable=sv, values=opts, width=26,
                     state="readonly", font=("Microsoft YaHei", 9)).pack(anchor="w", pady=4)
        def ok():
            val = sv.get()
            f["next_flow"] = -1 if val.startswith("无") else int(val.split(":")[0])-1
            self._refresh_tree(); win.destroy()
        _btn(fr, "确认", T["success"], ok).pack(anchor="w", pady=6)

    # ══════════════════════════════════════════════════════
    #  步骤操作
    # ══════════════════════════════════════════════════════

    def _add_step(self):
        gi, fi = self._sel_group, self._sel_flow
        if fi < 0:
            messagebox.showwarning("提示", "请先选择流程")
            return
        self._save_flow()
        stype = self._new_sv.get().split("(")[0].strip()
        groups = self.cfg.get("flow_groups", [])
        f = groups[gi]["flows"][fi]
        step_add(f, stype)
        self._rebuild_cards(f["steps"])
        self.log(f"添加步骤：{STEP_LABELS.get(stype, stype)}", "info")

    def _del_step(self, idx):
        gi, fi = self._sel_group, self._sel_flow
        if fi < 0: return
        self._save_flow()
        f = self.cfg["flow_groups"][gi]["flows"][fi]
        step_delete(f, idx)
        self._rebuild_cards(f["steps"])

    def _mv_step(self, idx, d):
        gi, fi = self._sel_group, self._sel_flow
        if fi < 0: return
        self._save_flow()
        f = self.cfg["flow_groups"][gi]["flows"][fi]
        step_move(f, idx, d)
        self._rebuild_cards(f["steps"])

    def _rebuild_cards(self, steps):
        for w in self._sf.winfo_children(): w.destroy()
        self._step_cards.clear()
        for i, s in enumerate(steps):
            c = StepCard(self._sf, s, i, on_delete=self._del_step,
                         on_move=self._mv_step, app=self)
            c.pack(fill="x", pady=3)
            self._step_cards.append(c)

    def _save_flow(self, save_to_disk=False):
        gi, fi = self._sel_group, self._sel_flow
        groups = self.cfg.get("flow_groups", [])
        if not (0 <= gi < len(groups)): return
        flows = groups[gi].get("flows", [])
        if not (0 <= fi < len(flows)): return
        f = flows[fi]
        # 保存所有步骤卡片参数到内存
        for c in self._step_cards: c.save()
        try: f["loop_count"] = int(float(self._loop_e.get()))
        except: pass
        try: f["pre_delay"]  = float(self._pd_e.get())
        except: pass
        if save_to_disk:
            save_config(self.cfg)
            self.log(f"已保存所有配置到文件", "ok")

    def _load_flow(self, gi, fi):
        groups = self.cfg.get("flow_groups", [])
        if not (0 <= gi < len(groups)): return
        flows = groups[gi].get("flows", [])
        if not (0 <= fi < len(flows)): return
        f = flows[fi]
        grp_name = groups[gi].get("name", f"组{gi+1}")
        self._fnlbl.config(text=f"[{gi+1}-{fi+1}] {grp_name} / {f.get('name','流程')}")
        self._loop_e.delete(0,"end"); self._loop_e.insert(0, str(f.get("loop_count", 1)))
        self._pd_e.delete(0,"end");   self._pd_e.insert(0,   str(f.get("pre_delay",  0)))
        self._rebuild_cards(f.get("steps", []))

    # ══════════════════════════════════════════════════════
    #  录制脚本
    # ══════════════════════════════════════════════════════

    def _toggle_rec(self):
        if self._recorder.is_recording():
            events = self._recorder.stop()
            if events:
                d    = self.cfg.get("scripts_dir", _SCRIPT_DIR)
                name = self._rec_name_e.get().strip() or f"script_{int(time.time())}"
                path = os.path.join(d, f"{name}.json")
                try:
                    RecorderEngine.save(events, path)
                    self.log(f"录制完成：{name}（{len(events)}事件）", "ok")
                except Exception as e:
                    self.log(f"保存失败: {e}", "err")
            else:
                self.log("录制内容为空", "warn")
            self._rec_btn.config(text="● 开始录制", bg=T["danger"])
            self._rec_stat.config(text="未录制", fg=T["text2"])
            self._refresh_scripts()
        else:
            self._recorder.start()
            self._rec_btn.config(text="■ 停止录制", bg=T["warning"])
            self._rec_stat.config(text="录制中...", fg=T["danger"])
            self.log("开始录制", "warn")

    def _refresh_scripts(self):
        self._script_lb.delete(0, "end")
        d = self.cfg.get("scripts_dir", "")
        if d and os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".json"):
                    self._script_lb.insert("end", fn)

    def _del_script(self):
        sel = self._script_lb.curselection()
        if not sel: return
        fname = self._script_lb.get(sel[0])
        if not messagebox.askyesno("确认", f"删除脚本「{fname}」？"): return
        try:
            os.remove(os.path.join(self.cfg.get("scripts_dir",""), fname))
            self._refresh_scripts()
            self.log(f"删除脚本：{fname}", "warn")
        except Exception as e:
            self.log(f"删除失败: {e}", "err")

    # ══════════════════════════════════════════════════════
    #  运行控制
    # ══════════════════════════════════════════════════════

    def _start(self):
        if self._runner and self._runner.is_running():
            messagebox.showwarning("提示", "任务已在运行中")
            return
        self._save_flow()
        save_config(self.cfg)

        # 解析起始 组+流程
        try:
            gi = int(self._start_grp_var.get().split(":")[0]) - 1
        except Exception:
            gi = 0
        try:
            fi = int(self._start_flow_var.get().split(":")[0]) - 1
        except Exception:
            fi = 0

        def on_flow(grp_i, flow_i, name):
            fiid = self._tree_iid_flow(grp_i, flow_i)
            def _ui():
                try:
                    self._tree.selection_set(fiid)
                    self._tree.see(fiid)
                except Exception: pass
                self._llbl.config(text=f"当前：{name}")
            self.after(0, _ui)

        def on_done(r):
            def _ui():
                self._set_status(False)
                self.log(
                    f"{'✓' if r==State.DONE else '✗'} 任务{r}，"
                    f"总循环{self._runner.get_stats().get('total_loops',0)}次",
                    "ok" if r == State.DONE else "err")
            self.after(0, _ui)

        self._runner = FlowRunner(
            cfg=self.cfg, log_callback=self.log,
            on_flow_change=on_flow, on_task_done=on_done)
        self._runner.start(group_idx=gi, flow_idx=fi)
        self._set_status(True)
        self.after(200, self.iconify)

    def _pause(self):
        if not self._runner: return
        if self._runner.is_paused():
            self._runner.resume(); self._set_status(True, paused=False)
        elif self._runner.is_running():
            self._runner.pause(); self._set_status(True, paused=True)

    def _stop(self):
        if self._runner:
            threading.Thread(target=self._runner.stop, daemon=True).start()
        self._set_status(False)

    def _set_status(self, running, paused=False):
        c, t = ((T["warning"], "已暂停") if paused
                else (T["success"], "运行中") if running
                else (T["text2"], "未运行"))
        self.after(0, lambda: [
            self._dot.config(fg=c),
            self._stxt.config(text=t, fg=c),
        ])

    # ══════════════════════════════════════════════════════
    #  热键
    # ══════════════════════════════════════════════════════

    def _start_hotkey_listener(self):
        self._hk_listener  = None
        self._hk_stop_flag = threading.Event()
        self._hk_pressed   = set()

        def _key_to_str(key):
            try: return key.name.upper()
            except AttributeError:
                try: return key.char.upper() if key.char else ""
                except: return ""

        def _on_press(key):
            if self._hk_stop_flag.is_set(): return False
            ks = _key_to_str(key)
            self._hk_pressed.add(ks)
            def check(cfg_key, action):
                hk = self.cfg.get(cfg_key, "").strip().upper()
                if hk and ks == hk:
                    if self._recorder.is_recording():
                        self._recorder._filter_key = ks
                    self.after(0, action)
            check("hotkey_start",      self._start)
            check("hotkey_stop",       self._stop)
            check("hotkey_pause",      self._pause)
            check("hotkey_rec_toggle", self._toggle_rec)

        def _on_release(key):
            if self._hk_stop_flag.is_set(): return False
            self._hk_pressed.discard(_key_to_str(key))

        try:
            from pynput import keyboard as _kb
            self._hk_listener = _kb.Listener(
                on_press=_on_press, on_release=_on_release)
            self._hk_listener.daemon = True
            self._hk_listener.start()
            log.info("全局热键监听已启动")
        except Exception as e:
            log.warning(f"全局热键监听启动失败: {e}")

    def _stop_hotkey_listener(self):
        self._hk_stop_flag.set()
        if self._hk_listener:
            try: self._hk_listener.stop()
            except Exception: pass

    # ══════════════════════════════════════════════════════
    #  设置对话框
    # ══════════════════════════════════════════════════════

    def _settings(self):
        win = tk.Toplevel(self)
        win.title("设置")
        win.configure(bg=T["bg"])
        win.grab_set()
        win.resizable(False, False)
        f = tk.Frame(win, bg=T["card"], padx=16, pady=12)
        f.pack(fill="both", expand=True, padx=12, pady=12)

        path_fields = [
            ("paddle_exe_path", "PaddleOCR-json.exe 路径", False),
            ("tesseract_path",  "Tesseract.exe 路径",      False),
            ("scripts_dir",     "录制脚本保存目录",         True),
        ]
        entries = {}
        for key, label, is_dir in path_fields:
            tk.Label(f, text=label+":", bg=T["card"], fg=T["text2"],
                     font=("Microsoft YaHei", 9)).pack(anchor="w", pady=(4,0))
            row = tk.Frame(f, bg=T["card"]); row.pack(fill="x", pady=2)
            tf = tk.Frame(row, bg=T["border"], padx=1, pady=1)
            tf.pack(side="left", fill="x", expand=True)
            e = tk.Entry(tf, bg=T["card2"], fg=T["text"], insertbackground=T["text"],
                          relief="flat", font=("Microsoft YaHei", 9))
            e.insert(0, self.cfg.get(key,"").replace("\\","/"))
            e.pack(fill="x", ipady=3)
            entries[key] = e
            def _browse(e=e, d=is_dir):
                p = (filedialog.askdirectory() if d
                     else filedialog.askopenfilename(
                         filetypes=[("EXE","*.exe"),("All","*.*")]))
                if p:
                    e.delete(0,"end"); e.insert(0, p.replace("\\","/"))
            _btn(row, "浏览", T["border"], _browse).pack(side="left", padx=4)

        _sep(f)
        tk.Label(f, text="快捷键配置（单个功能键，如 F6）：",
                 bg=T["card"], fg=T["text"],
                 font=("Microsoft YaHei", 9, "bold")).pack(anchor="w", pady=(4,2))
        hk_fields = [
            ("hotkey_start",      "启动任务"),
            ("hotkey_stop",       "停止任务"),
            ("hotkey_pause",      "暂停/继续"),
            ("hotkey_rec_toggle", "录制开始/停止"),
        ]
        hk_entries = {}
        for key, label in hk_fields:
            row = tk.Frame(f, bg=T["card"]); row.pack(fill="x", pady=2)
            tk.Label(row, text=label+":", bg=T["card"], fg=T["text2"],
                     font=("Microsoft YaHei", 9), width=14, anchor="w").pack(side="left")
            tf = tk.Frame(row, bg=T["border"], padx=1, pady=1)
            tf.pack(side="left", padx=4)
            e = tk.Entry(tf, bg=T["card2"], fg=T["text"], insertbackground=T["text"],
                          relief="flat", font=("Microsoft YaHei", 9), width=6)
            e.insert(0, self.cfg.get(key, ""))
            e.pack(ipady=3)
            hk_entries[key] = e
            tk.Label(row, text="（留空=禁用）", bg=T["card"], fg=T["text2"],
                     font=("Microsoft YaHei", 8)).pack(side="left")

        def save():
            for k, e in entries.items():
                raw = e.get().strip()
                self.cfg[k] = os.path.normpath(raw) if raw else ""
            for k, e in hk_entries.items():
                self.cfg[k] = e.get().strip().upper()
            save_config(self.cfg)
            self.log("设置已保存", "ok")
            self._stop_hotkey_listener()
            self._start_hotkey_listener()
            messagebox.showinfo("成功", "设置已保存")
            win.destroy()

        _btn(f, "保存设置", T["success"], save).pack(anchor="w", pady=8)

    # ══════════════════════════════════════════════════════
    #  日志
    # ══════════════════════════════════════════════════════

    def log(self, msg, level="info"):
        def _do():
            ts   = time.strftime("%H:%M:%S")
            line = f"[{ts}] {msg}\n"
            self._log_t.config(state="normal")
            self._log_t.insert("end", line, level)
            self._log_t.see("end")
            self._log_t.config(state="disabled")
            try:
                os.makedirs(os.path.join(_SCRIPT_DIR, "log"), exist_ok=True)
                with open(os.path.join(_SCRIPT_DIR, "log",
                          f"flow_runner_{time.strftime('%Y%m%d')}.log"),
                          "a", encoding="utf-8") as lf:
                    lf.write(line)
            except: pass
        self.after(0, _do)

    def _clear_log(self):
        self._log_t.config(state="normal")
        self._log_t.delete("1.0", "end")
        self._log_t.config(state="disabled")

    # ══════════════════════════════════════════════════════
    #  关闭
    # ══════════════════════════════════════════════════════

    def _on_close(self):
        if self._runner and self._runner.is_running():
            if not messagebox.askyesno("确认", "任务正在运行，确认退出？"): return
            self._runner.stop(timeout=3)
        elif self._runner:
            try:
                from flow_runner_p2 import _stop_paddle
                _stop_paddle()
            except Exception: pass
        self._stop_hotkey_listener()
        self._save_flow()
        try: self.cfg["window_geometry"] = self.geometry()
        except: pass
        save_config(self.cfg)
        self.destroy()


if __name__ == "__main__":
    import ctypes
    try: ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except: pass
    App().mainloop()
