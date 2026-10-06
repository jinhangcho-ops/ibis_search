"""데이터 연결. 폴더의 파일을 열거나, 연결 주소로 DB에 접속한다."""
import os
from pathlib import Path
from urllib.parse import quote_plus, urlsplit

import ibis

import drivers

def find_files(folder):
    """폴더에서 DuckDB 파일과 Parquet·CSV 파일을 찾는다. 확장자는 대소문자를 가리지 않는다.
    이름이 .으로 시작하는 폴더(.venv, .git 등)는 들어가지 않는다."""
    files = []
    for root, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        files += [Path(root, name) for name in names]
    files.sort()
    duckdb_files = [p for p in files if p.suffix.lower() == ".duckdb"]
    flat_files = [p for p in files if p.suffix.lower() in (".parquet", ".csv")]
    return duckdb_files, flat_files


def open_duckdb(path):
    return ibis.duckdb.connect(path, read_only=True)


def table_names(paths):
    """파일별 테이블 이름. 보통은 파일 이름이고, 이름이 겹치는 파일만 '폴더_이름_확장자'로 한다
    (예: sub_orders_csv). 그래도 겹치면 _2, _3을 붙인다. 대소문자는 가리지 않는다."""
    stems = [p.stem.lower() for p in paths]
    root = os.path.commonpath([p.parent for p in paths]) if paths else ""
    names, used = [], set()
    for p in paths:
        name = p.stem
        if stems.count(name.lower()) > 1:
            name = "_".join(p.relative_to(root).with_suffix("").parts) + "_" + p.suffix[1:].lower()
        base, n = name, 1
        while name.lower() in used:
            n += 1
            name = f"{base}_{n}"
        used.add(name.lower())
        names.append(name)
    return names


def open_flat_files(paths):
    """Parquet·CSV 파일을 Polars 백엔드(LazyFrame)에 table_names의 이름으로 등록한다."""
    con = ibis.polars.connect()
    for p, name in zip(paths, table_names(paths)):
        read = con.read_parquet if p.suffix.lower() == ".parquet" else con.read_csv
        read(p, table_name=name)
    return con


def open_url(url, user="", password=""):
    """duckdb://, mssql://, postgres:// 등 Ibis가 지원하는 주소로 접속한다.
    드라이버를 먼저 확인하고, 아이디·비밀번호는 입력한 것만 주소에 넣는다(비밀번호 특수문자는 인코딩)."""
    extra = drivers.prepare(url, password)
    if user or password:
        parts = urlsplit(url)
        login = user + (":" + quote_plus(password, safe="") if password else "")
        url = parts._replace(netloc=f"{login}@{parts.netloc}").geturl()
    return ibis.connect(url, **extra)


def close(con):
    """연결을 닫아 파일·접속을 놓는다. 닫기를 지원하지 않는 백엔드는 그냥 둔다."""
    try:
        con.disconnect()
    except Exception:
        pass


def list_schemas(con):
    """스키마 목록. 지원하지 않는 백엔드(Polars 등)는 빈 목록."""
    return sorted(con.list_databases()) if hasattr(con, "list_databases") else []


def list_tables(con, schema=None):
    return con.list_tables(database=schema) if schema else con.list_tables()


def get_table(con, name, schema=None):
    return con.table(name, database=schema) if schema else con.table(name)


def mask(message, password):
    """메시지에서 비밀번호(원래 값과 주소에 넣은 인코딩 값)를 ***로 가린다."""
    for secret in (quote_plus(password, safe=""), password) if password else ():
        message = message.replace(secret, "***")
    return message
