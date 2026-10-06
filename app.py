"""Ibis 검색 화면의 서버. 따로 실행하지 않고 desktop.py가 프로그램 창 안에서 띄운다."""
import functools
import json
import operator
import secrets
import shutil
import tempfile
import threading
from pathlib import Path

from flask import Flask, Response, abort, g, jsonify, request
from werkzeug.exceptions import HTTPException

import monitor
import parse
import result
import settings
import source

app = Flask(__name__, static_folder="static")
# 연결은 메모리에만 둔다. passwords는 오류 문구에서 가릴 값, opened는 다시 열 때 쓸 요청 값, rows는 세어 둔 테이블 행 수, cancel은 지금 도는 데이터 작업의 취소 신호.
state = {"con": None, "passwords": [], "opened": None, "rows": {}, "cancel": threading.Event()}
turn = threading.Lock()  # 연결 하나를 같이 쓰므로 요청은 한 번에 하나만 처리한다. 메모리·CPU 요청과 취소 요청만 기다리지 않는다.
KEY = secrets.token_urlsafe(32)  # 실행할 때마다 새로 만드는 열쇠. desktop.py가 창 주소에 넣는다.
QUERY_TIMEOUT = 1800  # 데이터 작업 하나를 기다리는 시간(초). 넘으면 멈춘다.


def to_json(df):
    """Polars DataFrame → {columns, rows}. 날짜는 ISO 문자열이 된다."""
    return {"columns": df.columns, "rows": json.loads(df.write_json())}


def get_con():
    if state["con"] is None:
        raise ValueError("먼저 연결하세요.")
    return state["con"]


def run(work, drop=lambda value: None):
    """데이터 작업을 따로 돌려 QUERY_TIMEOUT초까지, 취소 요청이 오기 전까지만 기다린다. 그만두면 DB에도 멈추라고 한다.
    그만둔 작업이 뒤에서 늦게 끝나면 결과는 버린다(치울 것이 있으면 drop으로)."""
    state["cancel"] = threading.Event()  # 작업마다 새로 만들어 지난 취소가 남지 않게 한다.
    try:
        return source.within(QUERY_TIMEOUT, work, f"{QUERY_TIMEOUT // 60}분 안에 끝나지 않아 멈췄습니다.", state["cancel"], drop)
    except (TimeoutError, InterruptedError) as e:
        source.interrupt(state["con"])
        raise ValueError(str(e) or "취소했습니다.") from None


def predicate(cond, expr):
    """조건 하나를 Ibis 식으로. 문자열, 따옴표 해석을 끈 {"line": ..., "quotes": False},
    화면에서 or로 이은 묶음 {"any": [조건, ...]} 중 하나다. 묶음 안은 or, 조건끼리는 and."""
    if isinstance(cond, str):
        return parse.parse_condition(cond, expr)
    if "any" in cond:
        if not cond["any"]:
            raise ValueError("or로 묶을 조건이 없습니다.")
        return functools.reduce(operator.or_, [predicate(c, expr) for c in cond["any"]])
    return parse.parse_condition(cond["line"], expr, cond.get("quotes", True))


def build(body, select=True):
    """요청의 테이블·조인·기간·조건·정렬·표시 컬럼 줄을 Ibis 식 하나로 만든다.
    select=False면 줄은 모두 검사하되 표시 컬럼은 적용하지 않는다(컬럼 목록, 차트)."""
    con, schema = get_con(), body.get("schema") or None
    tables = source.list_tables(con, schema)
    parse.check_name(body["base"], tables, "테이블")
    get_table = lambda name: source.get_table(con, name, schema)
    expr = parse.apply_joins(
        get_table(body["base"]),
        [parse.parse_join(line, tables) for line in body.get("joins", [])],
        get_table,
    )
    preds = [p for line in body.get("periods", []) for p in parse.parse_period(line, expr)]
    preds += [predicate(cond, expr) for cond in body.get("conditions", [])]
    keys = [parse.parse_sort(line, expr) for line in body.get("sorts", [])]
    cols = [c for line in body.get("columns", []) for c in parse.parse_columns(line, expr)]
    return parse.apply(expr, preds, keys, cols if select else [])


@app.errorhandler(Exception)
def on_error(e):
    if isinstance(e, HTTPException):  # 404, 405, 잘못된 JSON 등은 원래 상태 코드로
        return jsonify(error=e.description), e.code
    return jsonify(error=source.mask(str(e), state["passwords"])), 400


@app.before_request
def only_window():
    """프로그램 창의 요청만 받는다. 창은 첫 주소의 key로 들어와 쿠키를 받고, 그 뒤로는 쿠키로 확인한다."""
    given = request.args.get("key") or request.cookies.get("key", "")
    if not secrets.compare_digest(given.encode(), KEY.encode()):
        abort(403, "프로그램 창에서만 열 수 있습니다.")


@app.before_request
def wait_turn():
    if request.path not in ("/api/usage", "/api/cancel"):
        turn.acquire()
        g.turn = True


@app.teardown_request
def end_turn(error):
    if g.pop("turn", False):
        turn.release()


@app.get("/api/usage")
def usage():
    return jsonify(monitor.usage())


@app.post("/api/cancel")
def cancel():
    """지금 도는 데이터 작업을 그만두게 한다. 없으면 아무 일도 하지 않는다."""
    state["cancel"].set()
    return jsonify(ok=True)


@app.post("/api/rowcount")
def rowcount():
    """기준 테이블의 전체 행 수. 예상 시간을 구할 때 쓴다. 테이블마다 한 번만 세고 연결이 바뀔 때까지 기억한다."""
    schema, base = request.json.get("schema") or None, request.json["base"]
    if (schema, base) not in state["rows"]:
        table = source.get_table(get_con(), base, schema)
        state["rows"][schema, base] = run(lambda: result.get_count(table))
    return jsonify(rows=state["rows"][schema, base])


@app.get("/")
def index():
    nonce = secrets.token_urlsafe(16)  # 응답마다 새로 만들어, 이 값이 붙은 스크립트만 실행되게 한다.
    html = Path(app.static_folder, "index.html").read_text(encoding="utf-8").replace("<script", f'<script nonce="{nonce}"')
    response = Response(html, mimetype="text/html")
    response.headers["Content-Security-Policy"] = (
        f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'unsafe-inline'; connect-src 'self'; "
        "img-src data: blob:; base-uri 'none'; form-action 'none'")
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
    passwords = source.passwords(new)
    if state["con"] is not None:  # 이전 연결을 닫아야 같은 파일을 다시 열 수 있다.
        source.close(state["con"])
        state.update(con=None, passwords=[], opened=None)
    state["rows"] = {}
    try:
        con = open_con(new)
    except Exception as e:
        message = source.mask(str(e), passwords)  # 복원 뒤에는 이전 비밀번호로만 가려지므로 여기서 가린다.
        if old:
            try:
                state.update(con=open_con(old), passwords=source.passwords(old), opened=old)
            except Exception:
                message += " 이전 연결도 다시 열 수 없어 연결이 끊겼습니다."
        raise ValueError(message) from None
    state.update(con=con, passwords=passwords, opened=new)
    try:
        settings.write("recent.json", source.recent(new))
    except OSError:  # 적어 두지 못해도 연결은 된 것이다.
        pass
    return jsonify(schemas=source.list_schemas(con))


@app.get("/api/recent")
def recent():
    """마지막으로 연결에 성공한 폴더나 주소(비밀번호 없음). 없으면 null. 화면이 연결 칸을 채울 때 쓴다."""
    return jsonify(recent=settings.read("recent.json"))


@app.post("/api/disconnect")
def disconnect():
    """연결을 끊고 파일·접속을 놓는다. 연결이 없으면 아무 일도 하지 않는다."""
    if state["con"] is not None:
        source.close(state["con"])
    state.update(con=None, passwords=[], opened=None, rows={})
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
    expr, column = build(request.json, select=False), request.json.get("column", "")
    found, more = run(lambda: result.get_values(expr, column))
    return jsonify(values=found, more=more)


def paged(body):
    """(검색 식, 행 수, 건너뛸 행 수)"""
    return build(body), parse.parse_limit(body.get("limit", 20)), parse.parse_offset(body.get("offset", 0))


@app.post("/api/query")
def query():
    """count를 false로 주면 전체 행 수를 세지 않고 null로 돌려준다. offset을 주면 그만큼 건너뛴 다음 행부터 준다(count는 그대로)."""
    body = request.json
    expr, limit, offset = paged(body)
    count, rows = run(lambda: (result.get_count(expr) if body.get("count", True) else None, result.get_rows(expr, limit, offset)))
    return jsonify(count=count, rows=to_json(rows))


@app.post("/api/sql")
def sql():
    """/api/query가 행을 가져올 때 실행할 SQL. 실행하지는 않는다."""
    return jsonify(sql=result.get_sql(*paged(request.json)))


@app.get("/api/searches")
def searches():
    return jsonify(searches=settings.searches())


@app.post("/api/searches")
def save_search():
    """search가 null이면 그 이름을 지운다."""
    return jsonify(searches=settings.save_search(request.json.get("name"), request.json.get("search")))


@app.post("/api/summary")
def summary():
    """컬럼별 집계. 큰 테이블에서는 오래 걸리므로 검색과 따로, 화면에서 요청할 때만 계산한다."""
    columns = request.json.get("summary_columns") or []  # 화면에서 고른 컬럼. 없으면 표시 컬럼(없으면 전체).
    expr = build(request.json, select=not columns)
    rows = run(lambda: result.get_summary(expr, columns))
    return jsonify(summary={"columns": result.SUMMARY_COLS, "rows": rows})


@app.post("/api/export")
def export():
    """조건에 맞는 전체 행을 임시 파일로 만들어 조금씩 내려보내고, 다 보내면 지운다."""
    expr = build(request.json)
    folder = tempfile.mkdtemp()
    path = Path(folder, "result." + request.json.get("format", ""))

    def write():
        try:
            result.export(expr, path)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise

    run(write, lambda done: shutil.rmtree(folder, ignore_errors=True))  # 그만둔 뒤에 늦게 다 만든 파일도 지운다.

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
    expr = build(body, select=False)
    labels, datasets, more = run(lambda: result.get_chart(
        expr, body["x"], body.get("series") or [], body.get("split") or None, body.get("order", "x")))
    return jsonify(labels=[str(v) for v in labels], datasets=datasets, more_splits=more,
                   max_groups=result.MAX_GROUPS, max_splits=result.MAX_SPLITS)
