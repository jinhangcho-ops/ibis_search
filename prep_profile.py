"""테이블의 모양과 컬럼별 통계(profile), 그 통계로 만든 전처리 추천(suggest)."""
import ibis

import parse
import result
from prep import type_text
from prep_ops import chars, date_pattern, stats

# 빈 값을 뜻하는 글자로 흔한 것. ""는 blank로 센다.
MARKERS = ["", "-", "N/A", "n/a", "NA", "null", "NULL", "None", "없음", "?"]
INT_SHAPE = r"^[+-]?[0-9]+$"
# 기호·숫자·단위 순서의 글자(₩1,200, 1,200원, 45%, 3 kg). 이런 모양일 때만 글자를 지우고 숫자로 바꾸라고 추천한다(a1b2 같은 코드는 아니다).
UNIT_SHAPE = r"^[^0-9A-Za-z가-힣]{0,3}[0-9][0-9,]*(\.[0-9]+)?\s*[^0-9]{0,5}$"
DATE_FORMATS = [("%Y%m%d", "YYYYMMDD"), ("%Y-%m-%d %H:%M:%S", "YYYY-MM-DD HH:MM:SS"), ("%Y-%m-%d", "YYYY-MM-DD")]  # 앞의 것이 우선
FEW_NULLS = 0.05  # 빈 값이 이 비율보다 적으면 그 행을 빼라고 추천한다.


def count(cond):
    """참인 행의 수를 세는 집계 식."""
    return cond.sum()


def text_metrics(col, i):
    """문자 컬럼의 통계 식. rest는 빈 값도 빈 값 표시도 아닌 값이고, 아래 *_num·*_int·*_date는 그 중 해당하는 값의 수다."""
    stripped = col.strip()
    rest = col.notnull() & ~col.isin(MARKERS)
    cleaned = stripped.re_replace(r"[^0-9.+\-]", "")
    unit = rest & ibis.coalesce(stripped.re_search(UNIT_SHAPE), False)
    is_int = lambda s: ibis.coalesce(s.re_search(INT_SHAPE), False) & s.try_cast("int64").notnull()
    metrics = {f"min_len{i}": chars(col).min(), f"max_len{i}": chars(col).max(), f"blank{i}": count(col == ""), f"spaces{i}": count(col != stripped),
               f"numeric{i}": count(stripped.try_cast("float64").notnull()), f"rest{i}": count(rest),
               f"rest_num{i}": count(rest & stripped.try_cast("float64").notnull()), f"rest_int{i}": count(rest & is_int(stripped)),
               f"clean_num{i}": count(unit & cleaned.try_cast("float64").notnull()), f"clean_int{i}": count(unit & is_int(cleaned)),
               f"lower{i}": col.lower().nunique(where=col.notnull())}
    metrics.update({f"mark{j}_{i}": count(col == m) for j, m in enumerate(MARKERS) if m})
    metrics.update({f"date{j}_{i}": count(rest & ibis.coalesce(stripped.re_search(date_pattern(fmt)), False)) for j, (fmt, _) in enumerate(DATE_FORMATS)})
    return metrics


def suggestions(info, found, i, rows):
    """컬럼 하나의 추천 [{"text", "why", "ops" 또는 "keep": False}]. found는 집계 결과, i는 컬럼 번호."""
    out = []
    add = lambda text, why, **what: out.append({"text": text, "why": why, **what})
    if info["kind"] == "string":
        rest = found[f"rest{i}"]
        if info["spaces"]:
            add("앞뒤 공백 지우기", f"앞뒤에 공백이 있는 값이 {info['spaces']:,}개 있습니다.", ops={"trim": True})
        marks = {m: (info["blank"] if m == "" else found[f"mark{j}_{i}"]) for j, m in enumerate(MARKERS)}
        marks = {m: n for m, n in marks.items() if n}
        if marks:
            add("빈 값 표시를 빈 값으로", "빈 값을 뜻하는 글자가 있습니다: " + ", ".join(f'"{m}" {n:,}개' for m, n in marks.items()), ops={"nulls": list(marks)})
        date = next(((fmt, name, found[f"date{j}_{i}"]) for j, (fmt, name) in enumerate(DATE_FORMATS) if rest and found[f"date{j}_{i}"] == rest), None)
        if date:
            add("날짜로 바꾸기", f"빈 값과 빈 값 표시를 뺀 {rest:,}개가 모두 {date[1]} 모양입니다.",
                ops={"type": {"to": "date", **({"format": date[0]} if date[0] != "%Y-%m-%d" else {})}})
        elif rest and found[f"rest_num{i}"] == rest:
            to = "int" if found[f"rest_int{i}"] == rest else "float"
            add("숫자로 바꾸기", f"빈 값과 빈 값 표시를 뺀 {rest:,}개가 모두 숫자로 바뀝니다.", ops={"type": {"to": to}})
        elif rest and found[f"clean_num{i}"] == rest:
            to = "int" if found[f"clean_int{i}"] == rest else "float"
            add("글자를 지우고 숫자로 바꾸기", f"숫자·부호·소수점이 아닌 글자를 지우면 {rest:,}개가 모두 숫자가 됩니다.", ops={"type": {"to": to, "clean": True}})
        if found[f"lower{i}"] < info["unique"]:
            add("소문자로 통일", f"대소문자만 다른 값이 있어 서로 다른 값이 {info['unique']:,}개에서 {found[f'lower{i}']:,}개로 줄어듭니다.", ops={"case": "lower"})
    if info["nulls"] and info["unique"]:  # 채울 값이 하나도 없는 컬럼은 채우기를 추천하지 않는다.
        share = info["nulls"] / rows
        why = f"빈 값이 {info['nulls']:,}개({share:.1%})입니다."
        if share < FEW_NULLS:
            add("빈 값인 행 빼기", why + " 5% 미만이라 그 행을 빼도 됩니다.", ops={"fill": {"how": "drop"}})
        elif info["kind"] in ("int", "float"):
            add("빈 값을 중앙값으로 채우기", why, ops={"fill": {"how": "median"}})
        else:
            add("빈 값을 최빈값으로 채우기", why, ops={"fill": {"how": "mode"}})
    if info["unique"] <= 1:
        add("컬럼 빼기", f"서로 다른 값이 {info['unique']}개뿐입니다.", keep=False)
    return out


def profile(t):
    """행 수와 컬럼별 통계, 추천을 집계 조회 한 번으로 구한다. unique는 빈 값을 뺀 서로 다른 값 수다.
    min·max는 숫자·날짜·시간 컬럼만(나머지는 null), 글자 수·blank·spaces·numeric은 문자 컬럼에만 있다."""
    kinds = {name: parse.kind(dtype) for name, dtype in t.schema().items()}
    metrics = {"rows": t.count()}
    for i, (name, kind) in enumerate(kinds.items()):
        col = t[name]
        metrics.update({f"nulls{i}": count(col.isnull()), f"unique{i}": col.nunique(where=col.notnull())})
        if kind in ("int", "float", "date", "time"):
            metrics.update({f"min{i}": col.min(), f"max{i}": col.max()})
        if kind == "string":
            metrics.update(text_metrics(col, i))
    found = stats(t, **metrics)
    columns = []
    for i, (name, kind) in enumerate(kinds.items()):
        info = {"name": name, "type": type_text(t[name].type()), "kind": kind, "nulls": found[f"nulls{i}"] or 0, "unique": found[f"unique{i}"],
                "min": result.plain(found.get(f"min{i}")), "max": result.plain(found.get(f"max{i}"))}
        if kind == "string":
            info.update({key: found[f"{key}{i}"] or 0 for key in ("blank", "spaces", "numeric")})
            info.update({key: found[f"{key}{i}"] for key in ("min_len", "max_len")})
        columns.append({**info, "suggest": suggestions(info, found, i, found["rows"])})
    return {"rows": found["rows"], "columns": columns}
