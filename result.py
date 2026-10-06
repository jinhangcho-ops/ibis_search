"""결과 계산과 파일 저장. 이 단계에서 처음으로 연산이 실행된다."""
from pathlib import Path

from parse import type_info

SUMMARY_COLS = ["name", "type", "count", "nulls", "unique", "min", "max", "mean"]
MAX_GROUPS = 50  # 차트에 표시할 최대 그룹 수
EXCEL_MAX_ROWS = 1_048_575  # Excel 시트 한 장의 행 수(제목 줄 제외)


def write_excel(expr, path):
    if get_count(expr) > EXCEL_MAX_ROWS:
        raise ValueError(f"Excel은 {EXCEL_MAX_ROWS:,}행까지 저장할 수 있습니다. CSV나 Parquet으로 저장하세요.")
    expr.to_polars().write_excel(path)


# 확장자: 저장 함수
EXPORTS = {
    ".csv": lambda expr, path: expr.to_csv(path),
    ".xlsx": write_excel,
    ".parquet": lambda expr, path: expr.to_parquet(path),
}


def columns(expr):
    """[(컬럼, 한글 타입)]"""
    return [(name, type_info(dtype)[0]) for name, dtype in expr.schema().items()]


def get_rows(expr, limit):
    return expr.limit(limit).to_polars()


def get_count(expr):
    return expr.count().to_pyarrow().as_py()


def get_summary(expr):
    return expr.describe().to_polars().sort("pos").select(SUMMARY_COLS)


def get_chart(expr, x, y, agg, order="x", max_groups=MAX_GROUPS):
    """x별로 y를 집계한다(count는 y 없이 행 수). order가 "x"면 x 순, "value"면 값이 큰 순으로 최대 max_groups개."""
    if agg == "count":
        value = expr.count()
    elif agg not in ("sum", "mean"):
        raise ValueError("집계 방식은 count, sum, mean 중 하나입니다.")
    else:
        if y not in expr.columns or not expr[y].type().is_numeric():
            raise ValueError("합계·평균은 숫자 컬럼을 Y로 골라야 합니다.")
        value = getattr(expr[y], agg)()
    grouped = expr.group_by(x).aggregate(value=value)
    keys = [grouped.value.desc(), grouped[x]] if order == "value" else [grouped[x]]
    return grouped.order_by(keys).limit(max_groups).to_polars()


def export(expr, path):
    """조건에 맞는 전체 행을 파일로 저장한다. 형식은 확장자(.csv, .xlsx, .parquet)로 정한다."""
    suffix = Path(path).suffix.lower()
    if suffix not in EXPORTS:
        raise ValueError(f"파일 이름은 {', '.join(EXPORTS)} 중 하나로 끝나야 합니다.")
    EXPORTS[suffix](expr, path)
