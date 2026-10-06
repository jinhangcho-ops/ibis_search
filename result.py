"""결과 계산과 파일 저장. 이 단계에서 처음으로 연산이 실행된다."""
from pathlib import Path

from parse import check_name, type_info

SUMMARY_COLS = ["name", "type", "count", "nulls", "unique", "min", "max", "mean"]
MAX_GROUPS = 50  # 차트에 표시할 최대 그룹 수
MAX_VALUES = 200  # 조건을 만들 때 보여 줄 컬럼 값 목록의 최대 개수
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


def get_values(expr, column, limit=MAX_VALUES):
    """컬럼의 서로 다른 값(빈 값 제외)을 정렬해 limit개까지 문자로 돌려준다. 더 있으면 두 번째 값이 True."""
    check_name(column, expr.columns)
    values = expr.filter(expr[column].notnull()).select(column).distinct().order_by(column).limit(limit + 1)
    values = [str(v) for v in values.to_polars()[column].to_list()]
    return values[:limit], len(values) > limit


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
