"""사용자 설정(화면 모드, 차트 비율, 차트 저장 모드, 따옴표 해석)을 사용자 폴더의 파일에 저장해 다음 실행 때도 쓴다."""
import json
import os
from pathlib import Path

PATH = Path(os.environ.get("APPDATA") or Path.home()) / "ibis_search" / "settings.json"

# 설정 이름: 고를 수 있는 값. 화면(index.html)의 선택지와 같아야 한다.
CHOICES = {
    "theme": ["light", "dark"],  # 화면 모드. 고른 적이 없으면 Windows 설정을 따른다.
    "ratio": ["auto", "square", "wide"],  # 차트 비율: 데이터 양에 따라 / 1:1 / 16:9
    "image": ["light", "dark"],  # 차트 그림을 저장할 때의 모드
    "quotes": ["on", "off"],  # 조건을 넣을 때 따옴표 해석: 값을 감싸는 기호로 / 글자 그대로
}


def load():
    """저장된 설정 중 쓸 수 있는 값만. 파일이 없거나 읽을 수 없으면 빈 설정."""
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {name: data[name] for name, values in CHOICES.items() if data.get(name) in values}


def save(changes):
    """바뀐 설정만 받아 기존 설정에 더해 저장한다."""
    if not isinstance(changes, dict) or not changes:
        raise ValueError("저장할 설정이 없습니다.")
    for name, value in changes.items():
        if value not in CHOICES.get(name, []):
            raise ValueError(f"'{name}' 설정에 쓸 수 없는 값입니다: {value}")
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps({**load(), **changes}), encoding="utf-8")
