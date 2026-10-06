"""Ibis 검색 화면의 서버. 따로 실행하지 않고 desktop.py가 프로그램 창 안에서 띄운다."""
import functools
import json
import operator
import secrets
import shutil
import tempfile
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request
from werkzeug.exceptions import HTTPException

import parse
import result
import settings
import source

app = Flask(__name__, static_folder="static")
state = {"con": None, "password": "", "opened": None}  # 연결은 메모리에만 둔다. opened는 다시 열 때 쓸 요청 값.
KEY = secrets.token_urlsafe(32)  # 실행할 때마다 새로 만드는 열쇠. desktop.py가 창 주소에 넣는다.


def to_json(df):
    """Polars DataFrame → {columns, rows}. 날짜는 ISO 문자열이 된다."""
    return {"columns": df.columns, "rows": json.loads(df.write_json())}


def get_con():
    if state["con"] is None:
        raise ValueError("먼저 연결하세요.")
    return state["con"]


def predicate(cond, expr):
    """조건 하나를 Ibis 식으로. 문자열, 따옴표 해석을 끈 {"line": ..., "quotes": False},
    화면에서 or로 이은 묶음 {"any": [조건, ...]} 중 하나다. 묶음 안은 or, 조건끼리는 and."""
    if isinstance(cond, str):
        return parse.parse_condition(cond, expr)[1]
    if "any" in cond:
        if not cond["any"]:
            raise ValueError("or로 묶을 조건이 없습니다.")
        return functools.reduce(operator.or_, [predicate(c, expr) for c in cond["any"]])
    return parse.parse_condition(cond["line"], expr, cond.get("quotes", True))[1]


def build(body, select=True):
    """요청의 테이블·조인·기간·조건·정렬·표시 컬럼 줄을 Ibis 식 하나로 만든다.
    select=False면 줄은 모두 검사하되 표시 컬럼은 적용하지 않는다(컬럼 목록, 차트)."""
    con, schema = get_con(), body.get("schema") or None
    tables = source.list_tables(con, schema)
    get_table = lambda name: source.get_table(con, name, schema)
    expr = parse.apply_joins(
        get_table(body["base"]),
        [parse.parse_join(line, tables) for line in body.get("joins", [])],
        get_table,
    )
    preds = [p for line in body.get("periods", []) for p in parse.parse_period(line, expr)[1]]
    preds += [predicate(cond, expr) for cond in body.get("conditions", [])]
    keys = [parse.parse_sort(line, expr)[1] for line in body.get("sorts", [])]
    cols = [c for line in body.get("columns", []) for c in parse.parse_columns(line, expr)[1]]
    return parse.apply(expr, preds, keys, cols if select else [])


@app.errorhandler(Exception)
def on_error(e):
    if isinstance(e, HTTPException):  # 404, 405, 잘못된 JSON 등은 원래 상태 코드로
        return jsonify(error=e.description), e.code
    return jsonify(error=source.mask(str(e), state["password"])), 400


@app.before_request
def only_window():
    """프로그램 창의 요청만 받는다. 창은 첫 주소의 key로 들어와 쿠키를 받고, 그 뒤로는 쿠키로 확인한다."""
    given = request.args.get("key") or request.cookies.get("key", "")
    if not secrets.compare_digest(given.encode(), KEY.encode()):
        abort(403, "프로그램 창에서만 열 수 있습니다.")


@app.get("/")
def index():
    response = app.send_static_file("index.html")
    response.set_cookie("key", KEY, httponly=True, samesite="Strict")
    for name, value in settings.load().items():  # 저장된 설정을 쿠키로 알려 준다. 화면이 그리기 전에 읽는다.
        response.set_cookie(name, str(value), samesite="Strict")
    return response


@app.post("/api/settings")
def save_settings():
    settings.save(request.json)
    return jsonify(ok=True)


@app.post("/api/files")
def files():
    """폴더에서 찾은 파일. files는 DuckDB 파일(하나를 골라 연다), flat은 Parquet·CSV 파일(여러 개를 골라 연다)."""
    duckdb_files, flat_files = source.find_files(request.json["path"])
    if not duckdb_files and not flat_files:
        raise ValueError("DuckDB·Parquet·CSV 파일이 없습니다.")
    return jsonify(files=[*map(str, duckdb_files)], flat=[*map(str, flat_files)])


def open_con(info):
    """연결 요청 값(folder는 path와 file 또는 files, url은 url·user·password)으로 연결을 연다.
    file은 DuckDB 파일 하나, files는 고른 Parquet·CSV 파일들이다(파일마다 테이블 하나)."""
    if info["kind"] == "folder":
        if "files" in info:  # 그 폴더에서 찾은 파일 중 고른 것만 연다.
            chosen = [p for p in source.find_files(info["path"])[1] if str(p) in info["files"]]
            if not chosen:
                raise ValueError("Parquet·CSV 파일을 하나 이상 고르세요.")
            return source.open_flat_files(chosen)
        if not info.get("file"):
            raise ValueError("파일을 고르세요.")
        return source.open_duckdb(info["file"])
    return source.open_url(info["url"], info.get("user", ""), info.get("password", ""))


@app.post("/api/connect")
def connect():
    """새 연결이 실패하면 이전 연결을 다시 열어 둔다."""
    body = request.json
    keys = ("path", "file", "files") if body["kind"] == "folder" else ("url", "user", "password")
    new, old = {"kind": body["kind"], **{k: body[k] for k in keys if k in body}}, state["opened"]
    if state["con"] is not None:  # 이전 연결을 닫아야 같은 파일을 다시 열 수 있다.
        source.close(state["con"])
        state.update(con=None, password="", opened=None)
    try:
        con = open_con(new)
    except Exception as e:
        message = source.mask(str(e), new.get("password", ""))  # 복원 뒤에는 이전 비밀번호로만 가려지므로 여기서 가린다.
        if old:
            try:
                state.update(con=open_con(old), password=old.get("password", ""), opened=old)
            except Exception:
                message += " 이전 연결도 다시 열 수 없어 연결이 끊겼습니다."
        raise ValueError(message) from None
    state.update(con=con, password=new.get("password", ""), opened=new)
    return jsonify(schemas=source.list_schemas(con))


@app.post("/api/disconnect")
def disconnect():
    """연결을 끊고 파일·접속을 놓는다. 연결이 없으면 아무 일도 하지 않는다."""
    if state["con"] is not None:
        source.close(state["con"])
    state.update(con=None, password="", opened=None)
    return jsonify(ok=True)


@app.get("/api/tables")
def tables():
    return jsonify(tables=source.list_tables(get_con(), request.args.get("schema") or None))


@app.post("/api/columns")
def columns():
    return jsonify(columns=result.columns(build(request.json, select=False)))


@app.post("/api/values")
def values():
    """조건을 만들 때 고를 수 있게 컬럼의 값 목록을 돌려준다. 화면에서 [목록]을 누를 때만 부른다."""
    found, more = result.get_values(build(request.json, select=False), request.json.get("column", ""))
    return jsonify(values=found, more=more)


@app.post("/api/query")
def query():
    expr = build(request.json)
    return jsonify(
        count=result.get_count(expr),
        rows=to_json(result.get_rows(expr, parse.parse_limit(request.json.get("limit", 20)))),
    )


@app.post("/api/summary")
def summary():
    """컬럼별 집계. 큰 테이블에서는 오래 걸리므로 검색과 따로, 화면에서 요청할 때만 계산한다."""
    columns = request.json.get("summary_columns") or []  # 화면에서 고른 컬럼. 없으면 표시 컬럼(없으면 전체).
    rows = result.get_summary(build(request.json, select=not columns), columns)
    return jsonify(summary={"columns": result.SUMMARY_COLS, "rows": rows})


@app.post("/api/export")
def export():
    """조건에 맞는 전체 행을 임시 파일로 만들어 조금씩 내려보내고, 다 보내면 지운다."""
    folder = tempfile.mkdtemp()
    path = Path(folder, "result." + request.json.get("format", ""))
    try:
        result.export(build(request.json), path)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise

    bom = b"\xef\xbb\xbf" if path.suffix == ".csv" else b""  # Excel이 CSV의 한글을 바로 읽도록 맨 앞에 붙인다.

    def stream():
        try:
            yield bom
            with open(path, "rb") as f:
                yield from iter(lambda: f.read(1 << 20), b"")
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    headers = {"Content-Disposition": f"attachment; filename={path.name}", "Content-Length": path.stat().st_size + len(bom)}
    return Response(stream(), mimetype="application/octet-stream", headers=headers)


@app.post("/api/chart")
def chart():
    """x별 집계. series는 [{"y", "agg"}]이고, split을 주면 그 컬럼의 값마다 계열을 나눈다."""
    body = request.json
    labels, datasets, more = result.get_chart(
        build(body, select=False), body["x"], body.get("series") or [], body.get("split") or None, body.get("order", "x"))
    return jsonify(labels=[str(v) for v in labels], datasets=datasets, more_splits=more,
                   max_groups=result.MAX_GROUPS, max_splits=result.MAX_SPLITS)
