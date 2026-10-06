"""이 프로그램이 쓰는 메모리와 CPU. 화면을 그리는 WebView2 같은 자식 프로세스도 더한다."""
import time

import psutil

ME = psutil.Process()
last = {"at": None, "cpu": 0.0}  # 직전에 잰 시각과 그때까지 쓴 CPU 시간(초)


def usage():
    """메모리(MB)와, 직전 호출 뒤로 쓴 CPU(%, PC의 전체 코어가 100). 첫 호출의 CPU는 0."""
    memory = cpu = 0
    for process in [ME, *ME.children(recursive=True)]:
        try:
            with process.oneshot():
                memory += process.memory_info().rss
                times = process.cpu_times()
                cpu += times.user + times.system
        except psutil.Error:  # 재는 사이에 끝난 프로세스
            continue
    now = time.monotonic()
    percent = 0 if last["at"] is None else max(0, cpu - last["cpu"]) / max(now - last["at"], 0.001) / psutil.cpu_count() * 100
    last.update(at=now, cpu=cpu)
    return {"memory": round(memory / 2**20), "cpu": round(min(percent, 100))}
