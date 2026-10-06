"""PC 전체와 이 프로그램의 메모리·CPU 점유율. 프로그램 쪽에는 화면을 그리는 WebView2 같은 자식 프로세스도 더한다."""
import psutil

ME = psutil.Process()
last = {}  # 직전에 잰 CPU 시간(초): 모든 코어의 전체(total)·쉰 시간(idle)·이 프로그램이 쓴 시간(mine)


def usage():
    """PC 전체(pc_*)와 이 프로그램의 메모리(%, MB)·CPU(%). CPU는 직전 호출 뒤로 쓴 양이고 전체 코어가 100이다. 첫 호출의 CPU는 0.
    요청마다 스레드가 달라 psutil.cpu_percent(스레드별로 직전 값을 기억)는 쓰지 않고 CPU 시간의 차이로 직접 구한다."""
    memory = mine = 0
    for process in [ME, *ME.children(recursive=True)]:
        try:
            with process.oneshot():
                memory += process.memory_info().rss
                times = process.cpu_times()
                mine += times.user + times.system
        except psutil.Error:  # 재는 사이에 끝난 프로세스
            continue
    times = psutil.cpu_times()
    now = {"total": times.user + times.system + times.idle, "idle": times.idle, "mine": mine}
    passed = now["total"] - last.get("total", now["total"])
    share = lambda used: round(min(max(used / passed * 100, 0), 100)) if passed > 0 else 0
    cpu = {"pc_cpu": share(passed - (now["idle"] - last.get("idle", 0))), "cpu": share(now["mine"] - last.get("mine", 0))}
    last.update(now)
    ram = psutil.virtual_memory()
    return {"pc_memory": round(ram.percent), "memory": round(memory / ram.total * 100), "memory_mb": round(memory / 2**20), **cpu}
