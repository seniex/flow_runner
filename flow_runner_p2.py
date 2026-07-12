"""
flow_runner_p2.py  —— Part 2: 流程执行引擎

变更（流程组版）：
  - FlowRunner.start() 接收 (group_idx, flow_idx) 指定起始
  - _run_task 只在组内按 next_flow 串联；-1 或越界则结束
  - 组间不串联
  - 新增 group_*/flow_in_group_* 配置工具函数
"""

import sys, os, time, copy, threading, json, logging

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

try:
    from flow_runner_p1 import (
        StepExecutor, FLOW_DEFAULT, FLOW_GROUP_DEFAULT,
        load_config, save_config, make_step, log,
    )
    _P1_OK = True
except ImportError as e:
    _P1_OK = False
    log = logging.getLogger("flow_runner_p2")
    log.error(f"无法 import flow_runner_p1: {e}")


def _stop_paddle():
    try:
        import flow_runner_p1 as _p1
        if _p1._bg:
            _p1._bg._get_paddle_engine().stop()
            log.info("PaddleOCR-json 引擎已停止")
    except Exception as e:
        log.warning(f"停止 PaddleOCR-json 失败: {e}")

def _start_paddle(cfg):
    try:
        import flow_runner_p1 as _p1
        if not _p1._bg:
            return
        exe = cfg.get("paddle_exe_path", "").strip()
        if not exe or not os.path.exists(exe):
            return
        eng = _p1._bg._get_paddle_engine()
        if eng._proc and eng._proc.poll() is None:
            return
        log.info("启动 PaddleOCR-json 引擎...")
        eng.start(exe)
        log.info("PaddleOCR-json 引擎就绪")
    except Exception as e:
        log.warning(f"启动 PaddleOCR-json 失败: {e}")


# ══════════════════════════════════════════════════════════
#  状态常量
# ══════════════════════════════════════════════════════════
class State:
    IDLE    = "idle"
    RUNNING = "running"
    PAUSED  = "paused"
    DONE    = "done"
    ABORTED = "aborted"


# ══════════════════════════════════════════════════════════
#  FlowEngine — 单流程执行器（不变）
# ══════════════════════════════════════════════════════════
class FlowEngine:
    def __init__(self, flow_cfg, global_cfg, stop_event, pause_event,
                 log_callback=None, on_loop_done=None):
        self.flow_cfg    = flow_cfg
        self.global_cfg  = global_cfg
        self.stop_event  = stop_event
        self.pause_event = pause_event
        self.log_cb      = log_callback
        self.on_loop_done = on_loop_done
        self.state       = State.IDLE
        self.loop_index  = 0
        self.step_index  = 0

    def run(self):
        name       = self.flow_cfg.get("name", "流程")
        loop_total = int(self.flow_cfg.get("loop_count", 1))
        steps      = self.flow_cfg.get("steps", [])
        pre_delay  = float(self.flow_cfg.get("pre_delay", 0.0))
        infinite   = (loop_total == 0)

        self._log(
            f"▶ 流程「{name}」开始，"
            f"循环{'∞' if infinite else loop_total}次，"
            f"共{len(steps)}步",
            "ok"
        )
        self.state      = State.RUNNING
        self.loop_index = 0

        if pre_delay > 0:
            self._log(f"  执行前等待 {pre_delay}s", "info")
            if not self._sleep(pre_delay):
                return self._finish(State.ABORTED, name)

        loop_n = 0
        while infinite or loop_n < loop_total:
            if self._stopped():
                return self._finish(State.ABORTED, name)

            self._log(
                f"  ── 第 {loop_n+1}/{'∞' if infinite else loop_total} 次循环 ──",
                "info"
            )
            self.step_index = 0

            result = self._run_steps(steps)
            if result == StepExecutor.ABORT:
                return self._finish(State.ABORTED, name)

            loop_n += 1
            self.loop_index = loop_n
            self._log(f"  ✓ 第{loop_n}次循环完成", "ok")

            if self.on_loop_done:
                try:
                    self.on_loop_done(name, loop_n, loop_total)
                except Exception as e:
                    log.error(f"on_loop_done 回调异常: {e}")

            if infinite or loop_n < loop_total:
                if not self._sleep(0.05):
                    return self._finish(State.ABORTED, name)

        return self._finish(State.DONE, name)

    def _run_steps(self, steps):
        total = len(steps)
        for i, step in enumerate(steps):
            if self._stopped():
                return StepExecutor.ABORT
            self._wait_if_paused()
            if self._stopped():
                return StepExecutor.ABORT

            self.step_index = i
            step_name = step.get("name", step.get("type", f"步骤{i+1}"))
            self._log(f"  [{i+1}/{total}] {step_name}", "info")

            executor = StepExecutor(
                cfg          = self.global_cfg,
                stop_event   = self.stop_event,
                log_callback = self.log_cb,
            )
            try:
                result = executor.exec_step(step)
            except Exception as e:
                self._log(f"  步骤[{step_name}]异常: {e}", "err")
                log.exception("步骤执行异常")
                result = StepExecutor.ABORT

            if result == StepExecutor.ABORT:
                self._log(f"  步骤[{step_name}]终止流程", "err")
                return StepExecutor.ABORT

        return StepExecutor.OK

    def _finish(self, state, name):
        self.state = state
        symbol = "✓" if state == State.DONE else "✗"
        level  = "ok" if state == State.DONE else "err"
        self._log(f"{symbol} 流程「{name}」{state}", level)
        return state

    def _stopped(self):
        return self.stop_event.is_set()

    def _wait_if_paused(self):
        if self.pause_event.is_set():
            self.state = State.PAUSED
            self._log("⏸ 已暂停，等待继续...", "warn")
            while self.pause_event.is_set():
                if self._stopped():
                    return
                time.sleep(0.1)
            self.state = State.RUNNING
            self._log("▶ 继续执行", "ok")

    def _sleep(self, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self._stopped():
                return False
            self._wait_if_paused()
            if self._stopped():
                return False
            time.sleep(max(0, min(0.05, deadline - time.time())))
        return True

    def _log(self, msg, level="info"):
        log.log(getattr(logging, level.upper(), logging.INFO), msg)
        if self.log_cb:
            try:
                self.log_cb(msg, level)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════
#  FlowRunner — 顶层调度器（流程组版）
# ══════════════════════════════════════════════════════════
class FlowRunner:
    """
    管理流程组内的流程串联执行。

    执行逻辑：
      1. 从指定 (group_idx, flow_idx) 开始
      2. 每个流程执行完（loop_count次）后读取 next_flow 字段
      3. next_flow 只在本组内有效，-1 或越界 → 任务结束
      4. 组间不串联
      5. 任意步骤 ABORT → 整个任务终止
    """

    def __init__(self, cfg=None, log_callback=None,
                 on_flow_change=None, on_task_done=None):
        """
        on_flow_change: fn(group_idx, flow_idx, flow_name)
        on_task_done:   fn(result)
        """
        self.cfg            = cfg or load_config()
        self.log_cb         = log_callback
        self.on_flow_change = on_flow_change
        self.on_task_done   = on_task_done

        self._stop_event    = threading.Event()
        self._pause_event   = threading.Event()
        self._thread        = None
        self._state         = State.IDLE
        self._cur_group_idx = -1
        self._cur_flow_idx  = -1

        self.stats = {
            "total_loops": 0,
            "flow_loops":  {},
            "start_time":  None,
            "end_time":    None,
        }

    # ── 公开接口 ─────────────────────────────────────────

    def start(self, group_idx=0, flow_idx=0):
        """
        启动执行任务（后台线程）。
        group_idx: 起始流程组索引
        flow_idx:  起始流程在组内的索引
        """
        if self._state in (State.RUNNING, State.PAUSED):
            self._log("任务已在运行中", "warn")
            return

        groups = self.cfg.get("flow_groups", [])
        if not groups:
            self._log("没有配置任何流程组，请先添加流程组", "warn")
            return
        if not (0 <= group_idx < len(groups)):
            self._log(f"起始流程组索引越界: {group_idx}", "err")
            return
        flows = groups[group_idx].get("flows", [])
        if not flows:
            self._log(f"流程组[{group_idx+1}]没有流程", "warn")
            return
        if not (0 <= flow_idx < len(flows)):
            self._log(f"起始流程索引越界: {flow_idx}", "err")
            return

        self._stop_event.clear()
        self._pause_event.clear()
        self._state = State.RUNNING
        self.stats = {
            "total_loops": 0,
            "flow_loops":  {},
            "start_time":  time.time(),
            "end_time":    None,
        }

        self._thread = threading.Thread(
            target=self._run_task,
            args=(group_idx, flow_idx),
            daemon=True,
            name="FlowRunner",
        )
        self._thread.start()
        grp_name = groups[group_idx].get("name", f"组{group_idx+1}")
        flow_name = flows[flow_idx].get("name", f"流程{flow_idx+1}")
        self._log(f"▶ 任务启动，从「{grp_name}」-「{flow_name}」开始", "ok")

    def stop(self, timeout=8.0):
        if self._state not in (State.RUNNING, State.PAUSED):
            return
        self._log("■ 停止请求...", "warn")
        self._stop_event.set()
        self._pause_event.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._state = State.IDLE
        _stop_paddle()
        self._log("■ 已停止", "warn")

    def pause(self):
        if self._state == State.RUNNING:
            self._pause_event.set()
            self._state = State.PAUSED
            self._log("⏸ 已请求暂停", "warn")

    def resume(self):
        if self._state == State.PAUSED:
            self._pause_event.clear()
            self._state = State.RUNNING
            self._log("▶ 继续执行", "ok")

    def is_running(self):
        return self._state == State.RUNNING

    def is_paused(self):
        return self._state == State.PAUSED

    def get_state(self):
        return self._state

    def get_current_pos(self):
        """返回 (group_idx, flow_idx)"""
        return (self._cur_group_idx, self._cur_flow_idx)

    def get_stats(self):
        return copy.deepcopy(self.stats)

    # ── 内部执行链 ──────────────────────────────────────

    def _run_task(self, start_group_idx, start_flow_idx):
        groups      = self.cfg.get("flow_groups", [])
        group_idx   = start_group_idx
        group_cfg   = groups[group_idx]
        flows       = group_cfg.get("flows", [])
        cur_idx     = start_flow_idx
        task_result = State.DONE

        _start_paddle(self.cfg)

        while 0 <= cur_idx < len(flows):
            if self._stop_event.is_set():
                task_result = State.ABORTED
                break

            flow_cfg  = flows[cur_idx]
            flow_name = flow_cfg.get("name", f"流程{cur_idx+1}")
            self._cur_group_idx = group_idx
            self._cur_flow_idx  = cur_idx

            if self.on_flow_change:
                try:
                    self.on_flow_change(group_idx, cur_idx, flow_name)
                except Exception as e:
                    log.error(f"on_flow_change 回调异常: {e}")

            self._log(f"\n{'─'*40}", "info")
            self._log(
                f"执行流程 [{cur_idx+1}/{len(flows)}] 「{flow_name}」",
                "ok"
            )

            engine = FlowEngine(
                flow_cfg     = flow_cfg,
                global_cfg   = self.cfg,
                stop_event   = self._stop_event,
                pause_event  = self._pause_event,
                log_callback = self.log_cb,
                on_loop_done = self._on_loop_done,
            )
            result = engine.run()

            if result == State.ABORTED:
                task_result = State.ABORTED
                self._log(f"流程「{flow_name}」终止，任务中断", "err")
                break

            # 组内串联
            next_idx = int(flow_cfg.get("next_flow", -1))
            if 0 <= next_idx < len(flows):
                next_name = flows[next_idx].get("name", f"流程{next_idx+1}")
                self._log(
                    f"「{flow_name}」→ 下一流程[{next_idx+1}]「{next_name}」",
                    "ok"
                )
                cur_idx = next_idx
            else:
                self._log(f"「{flow_name}」完成，任务结束", "ok")
                break

        _stop_paddle()
        self.stats["end_time"] = time.time()
        elapsed = self.stats["end_time"] - (self.stats["start_time"] or time.time())
        self._state         = State.IDLE
        self._cur_group_idx = -1
        self._cur_flow_idx  = -1

        symbol = "✓" if task_result == State.DONE else "✗"
        self._log(
            f"{symbol} 任务{task_result}，"
            f"耗时 {elapsed/60:.1f}分钟，"
            f"总循环 {self.stats['total_loops']} 次",
            "ok" if task_result == State.DONE else "err"
        )

        if self.on_task_done:
            try:
                self.on_task_done(task_result)
            except Exception as e:
                log.error(f"on_task_done 回调异常: {e}")

    def _on_loop_done(self, flow_name, loop_idx, loop_total):
        self.stats["total_loops"] += 1
        self.stats["flow_loops"].setdefault(flow_name, 0)
        self.stats["flow_loops"][flow_name] += 1
        self._log(
            f"  📊 「{flow_name}」已完成 "
            f"{loop_idx}/{'∞' if not loop_total else loop_total} 次"
            f" | 总计 {self.stats['total_loops']} 次",
            "info"
        )

    def _log(self, msg, level="info"):
        log.log(getattr(logging, level.upper(), logging.INFO), msg)
        if self.log_cb:
            try:
                self.log_cb(msg, level)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════
#  配置工具函数（供 GUI 调用）
# ══════════════════════════════════════════════════════════

# ── 流程组操作 ──────────────────────────────────────────

def group_add(cfg, name=None):
    """添加新流程组，返回组索引"""
    groups = cfg.setdefault("flow_groups", [])
    g = copy.deepcopy(FLOW_GROUP_DEFAULT)
    g["name"] = name or f"组{len(groups)+1}"
    groups.append(g)
    return len(groups) - 1

def group_delete(cfg, group_idx):
    """删除流程组"""
    groups = cfg.get("flow_groups", [])
    if 0 <= group_idx < len(groups):
        del groups[group_idx]

def group_rename(cfg, group_idx, name):
    """重命名流程组"""
    groups = cfg.get("flow_groups", [])
    if 0 <= group_idx < len(groups):
        groups[group_idx]["name"] = name

# ── 组内流程操作 ──────────────────────────────────────────

def flow_add(cfg, name="新流程", group_idx=0):
    """在指定流程组末尾添加新流程，返回流程索引"""
    groups = cfg.setdefault("flow_groups", [])
    if not groups:
        group_add(cfg)
    if not (0 <= group_idx < len(groups)):
        group_idx = len(groups) - 1
    f = copy.deepcopy(FLOW_DEFAULT)
    f["name"] = name
    flows = groups[group_idx].setdefault("flows", [])
    flows.append(f)
    return len(flows) - 1

def flow_delete(cfg, flow_idx, group_idx=0):
    """
    删除组内指定流程，修正同组内所有 next_flow 引用。
    """
    groups = cfg.get("flow_groups", [])
    if not (0 <= group_idx < len(groups)):
        return
    flows = groups[group_idx].get("flows", [])
    if not (0 <= flow_idx < len(flows)):
        return
    del flows[flow_idx]
    for f in flows:
        nf = int(f.get("next_flow", -1))
        if nf == flow_idx:
            f["next_flow"] = -1
        elif nf > flow_idx:
            f["next_flow"] = nf - 1

def flow_move(cfg, flow_idx, direction, group_idx=0):
    """组内流程上移/下移，交换 next_flow 引用"""
    groups = cfg.get("flow_groups", [])
    if not (0 <= group_idx < len(groups)):
        return
    flows = groups[group_idx].get("flows", [])
    new_idx = flow_idx + direction
    if not (0 <= new_idx < len(flows)):
        return
    flows[flow_idx], flows[new_idx] = flows[new_idx], flows[flow_idx]
    for f in flows:
        nf = int(f.get("next_flow", -1))
        if nf == flow_idx:
            f["next_flow"] = new_idx
        elif nf == new_idx:
            f["next_flow"] = flow_idx

def flow_move_to_group(cfg, src_group_idx, src_flow_idx, dst_group_idx, copy_mode=False):
    """
    将流程从 src 组移动（或复制）到 dst 组末尾。
    移动时：从 src 组删除（修正 next_flow），next_flow 重置为 -1。
    复制时：深拷贝一份，next_flow 重置为 -1。
    返回 (dst_group_idx, new_flow_idx) 或 None。
    """
    groups = cfg.get("flow_groups", [])
    if not (0 <= src_group_idx < len(groups) and
            0 <= dst_group_idx < len(groups)):
        return None

    src_flows = groups[src_group_idx].get("flows", [])
    if not (0 <= src_flow_idx < len(src_flows)):
        return None

    flow_copy = copy.deepcopy(src_flows[src_flow_idx])
    flow_copy["next_flow"] = -1   # 重置串联

    dst_flows = groups[dst_group_idx].setdefault("flows", [])
    dst_flows.append(flow_copy)
    new_idx = len(dst_flows) - 1

    if not copy_mode:
        # 移动：删除源
        flow_delete(cfg, src_flow_idx, src_group_idx)

    return (dst_group_idx, new_idx)

# ── 步骤操作 ──────────────────────────────────────────────

def step_add(flow_cfg, step_type):
    s = make_step(step_type)
    flow_cfg.setdefault("steps", []).append(s)
    return len(flow_cfg["steps"]) - 1

def step_delete(flow_cfg, index):
    steps = flow_cfg.get("steps", [])
    if 0 <= index < len(steps):
        del steps[index]

def step_move(flow_cfg, index, direction):
    steps     = flow_cfg.get("steps", [])
    new_index = index + direction
    if 0 <= new_index < len(steps):
        steps[index], steps[new_index] = steps[new_index], steps[index]


# ══════════════════════════════════════════════════════════
#  自测
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    if not _P1_OK:
        print("错误：flow_runner_p1.py 未找到"); import sys; sys.exit(1)

    print("=== flow_runner Part 2 流程引擎自测 ===\n")

    cfg = load_config()
    cfg["flow_groups"] = []

    gi = group_add(cfg, "测试组")
    i1 = flow_add(cfg, "测试流程1", gi)
    cfg["flow_groups"][gi]["flows"][i1]["loop_count"] = 2
    cfg["flow_groups"][gi]["flows"][i1]["next_flow"]  = 1
    step_add(cfg["flow_groups"][gi]["flows"][i1], "wait")
    cfg["flow_groups"][gi]["flows"][i1]["steps"][0]["seconds"] = 0.1

    i2 = flow_add(cfg, "测试流程2", gi)
    cfg["flow_groups"][gi]["flows"][i2]["loop_count"] = 1
    step_add(cfg["flow_groups"][gi]["flows"][i2], "wait")
    cfg["flow_groups"][gi]["flows"][i2]["steps"][0]["seconds"] = 0.05

    def on_log(msg, level):
        tag = {"ok":"✓","err":"✗","warn":"!","info":" "}.get(level," ")
        print(f"[{tag}] {msg}")

    done_result = []
    runner = FlowRunner(
        cfg=cfg, log_callback=on_log,
        on_flow_change=lambda gi,fi,n: print(f">>> 切换 组{gi+1}-流程[{fi+1}]「{n}」"),
        on_task_done=lambda r: done_result.append(r),
    )
    runner.start(group_idx=gi, flow_idx=0)
    deadline = time.time() + 10
    while runner.is_running() and time.time() < deadline:
        time.sleep(0.05)
    assert done_result and done_result[0] == State.DONE, f"期望DONE，得到{done_result}"
    print(f"\n统计: {json.dumps(runner.get_stats(), ensure_ascii=False)}")
    print("✓ 组内串联测试通过\n")

    # 测试 flow_move_to_group
    cfg2 = load_config(); cfg2["flow_groups"] = []
    g0 = group_add(cfg2, "A组"); g1 = group_add(cfg2, "B组")
    flow_add(cfg2, "流程X", g0); flow_add(cfg2, "流程Y", g0)
    cfg2["flow_groups"][g0]["flows"][0]["next_flow"] = 1
    pos = flow_move_to_group(cfg2, g0, 0, g1, copy_mode=False)
    assert len(cfg2["flow_groups"][g0]["flows"]) == 1
    assert len(cfg2["flow_groups"][g1]["flows"]) == 1
    assert cfg2["flow_groups"][g0]["flows"][0]["next_flow"] == -1  # 修正
    assert cfg2["flow_groups"][g1]["flows"][0]["name"] == "流程X"
    assert cfg2["flow_groups"][g1]["flows"][0]["next_flow"] == -1  # 重置
    print("✓ flow_move_to_group 测试通过\n")

    print("=== Part 2 全部测试通过 ===")
