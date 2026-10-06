"""창을 띄우지 않고 서버 동작을 확인한다. 데이터는 실행할 때마다 임시 폴더에 지어내 만든다. 프로젝트 폴더에서 실행한다.

    python tests.py

확인마다 OK/FAIL 한 줄을 찍고, 하나라도 실패하면 종료 코드 1로 끝난다.
"""
import datetime as dt
import io
import os
import random
import re
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # 콘솔 인코딩이 달라도 한글을 찍을 수 있게 한다.
# 실제 설정 파일과 임시 폴더를 건드리지 않게, settings·app을 불러오기 전에 임시 폴더 하나로 돌린다.
ROOT = Path(tempfile.mkdtemp(prefix="ibis_search_tests_"))
tempfile.tempdir = str(ROOT)  # 프로그램이 만드는 임시 폴더(내보내기)도 이 안에 생긴다.
os.environ["APPDATA"] = str(ROOT / "appdata")
sys.dont_write_bytecode = True  # 프로젝트 폴더에 __pycache__를 남기지 않는다.

import duckdb
import polars as pl

import settings
import source
from app import KEY, app, state

# 지어낸 데이터: 고객 40명과 주문 300건. 고객 번호 41~45는 고객 표에 없다(조인에서 빈 값이 된다).
random.seed(1)
STATUSES, NOTES = ["new", "paid", "shipped", "refunded"], [None, "=1+1", "red or blue", "a, b", "'vip'", "vip"]
customers = [{"id": i, "name": f"customer{i:02d}", "city": random.choice(["Seoul", "Busan", "Daegu", "Jeju"])} for i in range(1, 41)]
orders = []
for i in range(1, 301):
    day = dt.date(2024, 1, 1) + dt.timedelta(days=random.randrange(180))
    orders.append({"order_id": i, "customer_id": random.randint(1, 45), "status": random.choice(STATUSES),
                   "amount": random.randint(1, 500) * 100, "ordered_on": day,
                   "paid_at": dt.datetime.combine(day, dt.time(random.randrange(24), random.randrange(60))),
                   "note": random.choice(NOTES)})
DATA = ROOT / "data"
fails, done = [], []


def make_data():
    (DATA / "flat").mkdir(parents=True)
    con = duckdb.connect(str(DATA / "shop.duckdb"))
    for name, rows in (("customers", customers), ("orders", orders)):
        frame = pl.DataFrame(rows)
        con.execute(f"create table {name} as select * from frame")
    con.close()
    pl.DataFrame(customers[:5]).write_parquet(DATA / "flat" / "buyers.parquet")
    pl.DataFrame(orders[:5]).write_csv(DATA / "flat" / "sales.csv")


def check(name, got, want):
    ok = got == want
    print("OK  " if ok else "FAIL", name, "" if ok else f"-> {got!r} (기대 {want!r})")
    done.append(name)
    if not ok:
        fails.append(name)


def raised(work):
    try:
        work()
    except Exception as e:
        return type(e).__name__


def main():
    make_data()
    c = app.test_client()
    got = lambda api, **body: c.post(api, json=body).get_json()
    error = lambda api, **body: got(api, **body).get("error", "")
    query = lambda **body: got("/api/query", base="orders", **body)
    n = lambda keep: sum(1 for o in orders if keep(o))
    tables = lambda: sorted(c.get("/api/tables").get_json().get("tables", []))

    print("== 열쇠")
    check("열쇠 없는 요청은 403", c.get("/api/tables").status_code, 403)
    r = c.get("/?key=" + KEY)
    nonce = re.search(r"script-src 'nonce-([^']+)'", r.headers.get("Content-Security-Policy", ""))
    check("화면의 스크립트는 모두 CSP의 nonce를 가짐", r.text.count("<script") == r.text.count(f'<script nonce="{nonce and nonce.group(1)}"') > 0, True)
    check("그 뒤로는 쿠키로 통과, 최근 연결은 아직 없음", c.get("/api/recent").get_json(), {"recent": None})

    print("== 연결")
    found = got("/api/files", path=str(DATA))
    check("/api/files", ([Path(f).name for f in found["files"]], [Path(f).name for f in found["flat"]]), (["shop.duckdb"], ["buyers.parquet", "sales.csv"]))
    duck = found["files"][0]
    check("Parquet·CSV 파일 연결", got("/api/connect", kind="folder", path=str(DATA), files=found["flat"]), {"schemas": []})
    check("파일마다 테이블 하나", (tables(), got("/api/query", base="sales")["count"]), (["buyers", "sales"], 5))
    check("Parquet·CSV 연결은 SQL을 보여 줄 수 없음", error("/api/sql", base="sales"), "이 연결의 조회는 SQL로 보여 줄 수 없습니다.")
    got("/api/connect", kind="url", url=f"duckdb://{duck}")
    check("주소로 연결", tables(), ["customers", "orders"])
    check("/api/recent", c.get("/api/recent").get_json()["recent"], {"kind": "url", "url": f"duckdb://{duck}", "user": ""})
    e = error("/api/connect", kind="url", url="nosuch://someone:inline-pw-1@host/db", user="me", password="field-pw-2")
    check("연결 오류에서 비밀번호를 가림", ("***" in e, "inline-pw-1" in e, "field-pw-2" in e), (True, False, False))
    check("연결에 실패하면 이전 연결을 다시 엶", tables(), ["customers", "orders"])
    check("DuckDB 파일 연결", "main" in got("/api/connect", kind="folder", path=str(DATA), file=duck).get("schemas", []), True)
    check("최근 연결에 주소 안의 비밀번호를 남기지 않음", source.recent({"kind": "url", "url": "postgres://me:secret@host/db", "user": "me"}),
          {"kind": "url", "url": "postgres://me@host/db", "user": "me"})
    check("짧은 비밀번호는 주소의 비밀번호 자리에서만 가림", source.mask("db://me:ab@host/ab", ["ab"]), "db://me:***@host/ab")

    print("== 테이블·컬럼")
    check("/api/tables", tables(), ["customers", "orders"])
    check("/api/columns", got("/api/columns", base="orders")["columns"], [["order_id", "정수"], ["customer_id", "정수"], ["status", "문자"],
          ["amount", "정수"], ["ordered_on", "날짜"], ["paid_at", "날짜시간"], ["note", "문자"]])
    check("/api/rowcount", got("/api/rowcount", base="orders"), {"rows": len(orders)})
    check("/api/values", got("/api/values", base="orders", column="status"), {"values": sorted(STATUSES), "more": False})

    print("== 검색")
    name_of, city_of = {p["id"]: p["name"] for p in customers}, {p["id"]: p["city"] for p in customers}
    join = ["customers left customer_id=id"]
    r = query(joins=join, sorts=["amount desc", "order_id"], columns=["order_id, name"], limit=5, offset=5)
    top = sorted(orders, key=lambda o: (-o["amount"], o["order_id"]))[5:10]
    check("조인·정렬·표시 컬럼·건너뛰기", r, {"count": len(orders), "rows": {"columns": ["order_id", "name"],
          "rows": [{"order_id": o["order_id"], "name": name_of.get(o["customer_id"])} for o in top]}})
    march = lambda o: dt.date(2024, 3, 1) <= o["paid_at"].date() <= dt.date(2024, 3, 31)
    check("기간(끝 날짜는 그날 끝까지)", query(periods=["paid_at 2024-03-01 ~ 2024-03-31"]).get("count"), n(march))
    note = lambda o: o["note"] or ""
    for name, cond, keep in [
        ("= != 비교", ["status != paid", "amount >= 20000"], lambda o: o["status"] != "paid" and o["amount"] >= 20000),
        ("between", ["ordered_on between 2024-02-01 2024-02-29"], lambda o: dt.date(2024, 2, 1) <= o["ordered_on"] <= dt.date(2024, 2, 29)),
        ("in", ["status in new, paid"], lambda o: o["status"] in ("new", "paid")),
        ("except", ["status except new, paid"], lambda o: o["status"] not in ("new", "paid")),
        ("like", ["note like VIP"], lambda o: "vip" in note(o)),
        ("is null", ["note is null"], lambda o: o["note"] is None),
        ("is not null", ["note is not null"], lambda o: o["note"] is not None),
        ("or", ["status = new or amount < 5000"], lambda o: o["status"] == "new" or o["amount"] < 5000),
        ("따옴표로 감싼 값", ["note in 'a, b', 'red or blue'"], lambda o: note(o) in ("a, b", "red or blue")),
        ("any 묶음", [{"any": ["status = new", "note is null"]}], lambda o: o["status"] == "new" or o["note"] is None),
        ("quotes: false", [{"line": "note = 'vip'", "quotes": False}], lambda o: note(o) == "'vip'"),
    ]:
        check("조건 " + name, query(conditions=cond).get("count"), n(keep))
    check("행 수 0과 상한 초과는 거절", [error("/api/query", base="orders", limit=v)[:4] for v in (0, 10001)], ["행 수는"] * 2)
    r = query(limit=7, count=False)
    check("count: false", (r["count"], len(r["rows"]["rows"])), (None, 7))
    check("/api/sql", "SELECT" in got("/api/sql", base="orders", conditions=["amount > 100"]).get("sql", ""), True)
    check("/api/cancel은 도는 작업이 없어도 되고 다음 검색은 정상", (got("/api/cancel"), query().get("count")), ({"ok": True}, len(orders)))

    print("== 집계·차트")
    rows = {row["name"]: row for row in got("/api/summary", base="orders")["summary"]["rows"]}
    amounts, days = [o["amount"] for o in orders], [o["ordered_on"] for o in orders]
    check("집계: 모든 컬럼", list(rows), list(orders[0]))
    got_amount = {**rows["amount"], "mean": round(rows["amount"]["mean"], 6)}
    check("집계: 숫자", got_amount, {"name": "amount", "type": "int64", "count": len(orders), "nulls": 0, "unique": len(set(amounts)),
          "min": min(amounts), "max": max(amounts), "mean": round(sum(amounts) / len(amounts), 6)})
    check("집계: 날짜의 최소·최대", (rows["ordered_on"]["min"], rows["ordered_on"]["max"]), (str(min(days)), str(max(days))))
    check("집계: 문자는 평균 없음, 빈 값 수", (rows["note"]["mean"], rows["note"]["nulls"]), (None, n(lambda o: o["note"] is None)))
    r = got("/api/summary", base="orders", summary_columns=["note", "amount"])
    check("집계: 고른 컬럼만 그 순서로", [row["name"] for row in r["summary"]["rows"]], ["note", "amount"])
    labels, sizes = sorted(STATUSES), Counter(o["status"] for o in orders)
    r = got("/api/chart", base="orders", x="status", series=[{"agg": "count"}])
    check("차트: 계열 하나", (r["labels"], r["datasets"]), (labels, [{"series": 0, "split": None, "values": [sizes[s] for s in labels]}]))
    total = {s: sum(o["amount"] for o in orders if o["status"] == s) for s in labels}
    by_value = sorted(labels, key=lambda s: (-total[s], s))
    r = got("/api/chart", base="orders", x="status", order="value", series=[{"y": "amount", "agg": "sum"}, {"y": "amount", "agg": "mean"}])
    check("차트: 계열 둘, 값이 큰 순", (r["labels"], r["datasets"][0]["values"], [round(v, 6) for v in r["datasets"][1]["values"]]),
          (by_value, [total[s] for s in by_value], [round(total[s] / sizes[s], 6) for s in by_value]))
    cells = Counter((o["status"], city_of[o["customer_id"]]) for o in orders if o["customer_id"] in city_of)
    cities = Counter(city for _, city in cells.elements())
    r = got("/api/chart", base="orders", joins=join, x="status", split="city", series=[{"agg": "count"}])
    check("차트: 값별로 나눔", (r["datasets"], r["more_splits"]), ([{"series": 0, "split": city, "values": [cells.get((s, city)) for s in labels]}
          for city in sorted(cities, key=lambda v: (-cities[v], v))], False))

    print("== 저장")
    export = lambda kind: c.post("/api/export", json={"base": "orders", "sorts": ["order_id"], "columns": ["order_id, note"], "format": kind}).data
    data = export("csv")
    check("CSV: BOM, 전체 행, 수식 값 앞에 '", (data[:3], len(data.decode("utf-8").splitlines()), b"'=1+1" in data), (b"\xef\xbb\xbf", len(orders) + 1, True))
    check("Excel: 수식 값 앞에 '", "'=1+1" in zipfile.ZipFile(io.BytesIO(export("xlsx"))).read("xl/sharedStrings.xml").decode("utf-8"), True)
    check("Parquet: 값을 그대로", pl.read_parquet(io.BytesIO(export("parquet")))["note"].to_list(), [o["note"] for o in orders])
    check("모르는 형식은 거절", error("/api/export", base="orders", format="txt")[:6], "파일 이름은")

    print("== 설정·저장한 검색·사용량")
    check("/api/usage", sorted(c.get("/api/usage").get_json()), ["cpu", "memory", "memory_mb", "pc_cpu", "pc_memory"])
    check("설정 저장", (got("/api/settings", theme="dark"), settings.load()), ({"ok": True}, {"theme": "dark"}))
    check("쓸 수 없는 설정 값은 거절", (error("/api/settings", theme="blue")[:11], settings.load()), ("'theme' 설정에", {"theme": "dark"}))
    saved = {"base": "orders", "conditions": ["amount > 100"], "limit": "20"}
    check("검색 저장", got("/api/searches", name="mine", search=saved), {"searches": {"mine": saved}})
    got("/api/searches", name="mine", search={"base": "customers"})
    check("같은 이름은 덮어씀", c.get("/api/searches").get_json(), {"searches": {"mine": {"base": "customers"}}})
    check("검색 지우기", got("/api/searches", name="mine", search=None), {"searches": {}})
    check("빈 이름은 거절", error("/api/searches", name=" ", search=saved), "검색 이름은 1자 이상 50자 이하로 입력하세요.")

    print("== 기다리기·연결 해제")
    check("within: 시간을 넘기면 TimeoutError", raised(lambda: source.within(0.05, lambda: time.sleep(0.3), "늦음")), "TimeoutError")
    wake = threading.Event()
    threading.Timer(0.05, wake.set).start()
    check("within: 밖에서 깨우면 InterruptedError", raised(lambda: source.within(5, lambda: time.sleep(0.3), "늦음", wake)), "InterruptedError")
    check("/api/disconnect", got("/api/disconnect"), {"ok": True})
    check("연결을 끊은 뒤", c.get("/api/tables").get_json(), {"error": "먼저 연결하세요."})


try:
    main()
except Exception as e:  # 확인 도중 멈춰도 정리하고 실패로 끝낸다.
    print("FAIL 중단됨 ->", repr(e))
    fails.append("중단됨")
finally:
    if state["con"] is not None:
        source.close(state["con"])
    shutil.rmtree(ROOT, ignore_errors=True)
print(f"\n확인 {len(done)}개, 실패:", ", ".join(fails) or "없음")
sys.exit(1 if fails else 0)
