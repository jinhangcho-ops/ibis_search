"""사용자 설정(화면 모드, 차트 비율, 차트 저장 모드, 따옴표 해석, 조건 입력 방식, 전체 행 수 세기, 끌어서 조절한 크기, 직전 실행의 행당 시간)을 사용자 폴더의 파일에 저장해 다음 실행 때도 쓴다."""
import json
import os
import re
from pathlib import Path

PATH = Path(os.environ.get("APPDATA") or Path.home()) / "ibis_search" / "settings.json"

# 설정 이름: 고를 수 있는 값. 화면(index.html)의 선택지와 같아야 한다.
CHOICES = {
    "theme": ["light", "dark"],  # 화면 모드. 고른 적이 없으면 Windows 설정을 따른다.
    "ratio": ["auto", "square", "wide"],  # 차트 비율: 데이터 양에 따라 / 1:1 / 16:9
    "image": ["light", "dark"],  # 차트와 집계 표를 그림으로 저장할 때의 모드
    "quotes": ["on", "off"],  # 조건을 넣을 때 따옴표 해석: 값을 감싸는 기호로 / 글자 그대로
    "cond": ["fields", "line"],  # 조건 입력 방식: 칸으로 선택 / 한 줄 입력
    "count": ["on", "off"],  # 검색할 때 전체 행 수를 셀지: 센다 / 세지 않는다
}

# 끌어서 조절한 크기(px)와 전처리가 미리 볼 행 수(sample): (최소, 최대). 크기는 화면(index.html)의 SIZES와 같아야 한다. 0을 저장하면 기본값으로 돌아간다.
SIZES = {"panel": (240, 640), "rows": (120, 1200), "summary": (120, 1200), "chart": (200, 1000), "sample": (1000, 1_000_000)}

# 직전 실행의 행당 시간(나노초/행). 작업 종류(검색·집계·차트·저장·전처리의 모양 보기·미리보기·실행)와 기준 테이블 행 수의 구간(10배 단위)마다 하나.
# 이름은 time_종류_구간이고 구간은 행 수의 자릿수 - 1(1,000행 미만은 모두 2)이다. 화면이 예상 시간을 구할 때 같은 구간의 값만 쓴다.
# 구간과 상한(MAX_TIME)은 화면(index.html)과 같아야 한다.
TIME = re.compile(r"time_(search|summary|chart|export|profile|preview|run)_([2-9]|1[0-2])")
MAX_TIME = 10**12


def valid(name, value):
    if TIME.fullmatch(name):
        return type(value) is int and 1 <= value <= MAX_TIME
    if name in SIZES:
        return type(value) is int and SIZES[name][0] <= value <= SIZES[name][1]
    return value in CHOICES.get(name, [])


def read(name):
    """설정 폴더의 JSON 파일에 든 객체. 파일이 없거나 읽을 수 없으면 None."""
    try:
        data = json.loads((PATH.parent / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write(name, data):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    (PATH.parent / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def load():
    """저장된 설정 중 쓸 수 있는 값만. 파일이 없거나 읽을 수 없으면 빈 설정."""
    return {name: value for name, value in (read(PATH.name) or {}).items() if valid(name, value)}


def save(changes):
    """바뀐 설정만 받아 기존 설정에 더해 저장한다."""
    if not isinstance(changes, dict) or not changes:
        raise ValueError("저장할 설정이 없습니다.")
    for name, value in changes.items():
        if not valid(name, value) and not (name in SIZES and value == 0 and type(value) is int):
            raise ValueError(f"'{name}' 설정에 쓸 수 없는 값입니다: {value}")
    write(PATH.name, {name: value for name, value in {**load(), **changes}.items() if value != 0})


MAX_SEARCHES = 100  # 저장해 둘 수 있는 검색 수
MAX_SEARCH_SIZE = 20_000  # 검색 하나의 크기(JSON 글자 수)


def searches():
    """이름을 붙여 저장한 검색 {이름: 검색}. 연결 정보는 들어 있지 않다."""
    return read("searches.json") or {}


def save_search(name, search):
    """검색을 그 이름으로 저장한다(같은 이름은 덮어쓴다). search가 None이면 그 이름을 지운다. 바뀐 전체를 돌려준다."""
    name = name.strip() if isinstance(name, str) else ""
    if not 1 <= len(name) <= 50:
        raise ValueError("검색 이름은 1자 이상 50자 이하로 입력하세요.")
    found = searches()
    if search is None:
        found.pop(name, None)
    elif not isinstance(search, dict):
        raise ValueError("저장할 검색이 올바르지 않습니다.")
    elif len(json.dumps(search, ensure_ascii=False)) > MAX_SEARCH_SIZE:
        raise ValueError("저장할 검색이 너무 큽니다.")
    elif name not in found and len(found) >= MAX_SEARCHES:
        raise ValueError(f"저장한 검색은 {MAX_SEARCHES}개까지입니다. 쓰지 않는 것을 지우세요.")
    else:
        found[name] = search
    write("searches.json", found)
    return found
