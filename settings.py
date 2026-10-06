"""사용자 설정(화면 모드, 차트 비율, 차트 저장 모드, 따옴표 해석, 끌어서 조절한 크기, 직전 실행의 행당 시간)을 사용자 폴더의 파일에 저장해 다음 실행 때도 쓴다."""
import json
import os
from pathlib import Path

PATH = Path(os.environ.get("APPDATA") or Path.home()) / "ibis_search" / "settings.json"

# 설정 이름: 고를 수 있는 값. 화면(index.html)의 선택지와 같아야 한다.
CHOICES = {
    "theme": ["light", "dark"],  # 화면 모드. 고른 적이 없으면 Windows 설정을 따른다.
    "ratio": ["auto", "square", "wide"],  # 차트 비율: 데이터 양에 따라 / 1:1 / 16:9
    "image": ["light", "dark"],  # 차트와 집계 표를 그림으로 저장할 때의 모드
    "quotes": ["on", "off"],  # 조건을 넣을 때 따옴표 해석: 값을 감싸는 기호로 / 글자 그대로
    "cond": ["fields", "line"],  # 조건 입력 방식: 칸으로 선택 / 한 줄 입력
}

# 끌어서 조절한 크기(px): (최소, 최대). 화면(index.html)의 SIZES와 같아야 한다. 0을 저장하면 기본 크기로 돌아간다.
SIZES = {"panel": (240, 640), "rows": (120, 1200), "summary": (120, 1200), "chart": (200, 1000)}

# 직전 실행의 행당 시간(나노초/행). 작업 종류(검색·집계·차트·저장)마다 하나. 화면이 예상 시간을 구할 때 쓴다. 상한(MAX_TIME)은 화면(index.html)의 값과 같아야 한다.
TIMES = ["time_search", "time_summary", "time_chart", "time_export"]
MAX_TIME = 10**12


def valid(name, value):
    if name in TIMES:
        return type(value) is int and 1 <= value <= MAX_TIME
    if name in SIZES:
        return type(value) is int and SIZES[name][0] <= value <= SIZES[name][1]
    return value in CHOICES.get(name, [])


def load():
    """저장된 설정 중 쓸 수 있는 값만. 파일이 없거나 읽을 수 없으면 빈 설정."""
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {name: value for name, value in data.items() if valid(name, value)}


def save(changes):
    """바뀐 설정만 받아 기존 설정에 더해 저장한다."""
    if not isinstance(changes, dict) or not changes:
        raise ValueError("저장할 설정이 없습니다.")
    for name, value in changes.items():
        if not valid(name, value) and not (name in SIZES and value == 0 and type(value) is int):
            raise ValueError(f"'{name}' 설정에 쓸 수 없는 값입니다: {value}")
    PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {name: value for name, value in {**load(), **changes}.items() if value != 0}
    PATH.write_text(json.dumps(data), encoding="utf-8")
