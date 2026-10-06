# ibis_search

DB·DW 또는 내 데이터 파일에 붙어, 테이블·조인·기간·조건을 입력해 검색하는 Windows 프로그램입니다.

## 프로그램 받기

GitHub 저장소의 Actions 탭 → `build-exe` → `Run workflow`를 누르면 Windows용 프로그램 폴더가 만들어집니다. 완료된 실행 화면 아래 Artifacts에서 `ibis_search-windows`(zip)를 내려받아 압축을 풀고 `ibis_search.exe`를 실행하면 검색 화면이 프로그램 창으로 열립니다. 폴더 안의 다른 파일은 지우지 않습니다.

서명되지 않은 프로그램이라 Windows SmartScreen 경고가 나오면 [추가 정보] → [실행]을 누릅니다.

## 사용법

왼쪽 패널에서 위에서부터 차례로 입력하고 [검색]을 누르면 오른쪽에 결과 표가 나옵니다. [검색]은 패널 아래쪽에 항상 보입니다.

1. 연결
   - 내 폴더 파일: 폴더 경로를 넣고 [찾기]를 누르면 그 폴더의 `.duckdb`, `.parquet`, `.csv` 파일을 찾습니다. 목록에서 고르고 [연결]을 누릅니다. 이름이 `.`으로 시작하는 폴더는 찾지 않습니다.
   - DB 주소: 연결 주소(예: `duckdb://data.duckdb`, `mssql://host:1433/db`)와 아이디, 비밀번호를 넣고 [연결]을 누릅니다. 필요 없는 항목은 비웁니다.
2. 테이블: 스키마(DB에서만)와 기준 테이블을 고릅니다.
3. 조인
   ```
   customers left customer_id=id
   ```
   형식: `테이블 [inner|left|right|outer] 왼쪽컬럼=오른쪽컬럼` (종류를 빼면 inner, 컬럼 이름이 같으면 이름만, 여러 개는 쉼표)
4. 기간 (한쪽은 비워도 됩니다)
   ```
   order_date 2025-07-01 ~ 2025-07-31
   order_date 2025-07-01 ~
   ```
5. 조건 (줄끼리는 AND, 한 줄 안에서 `or`로 나누면 OR)
   ```
   amount >= 1000
   status = 완료
   amount between 1000 5000
   status in 완료, 취소
   status except 완료, 취소
   status like 완
   status is not null
   status = 완료 or amount >= 3000
   title = 'black or white'
   name in 'Kim, Lee', Park
   ```
   연산자: `=`, `!=`, `>=`, `<=`, `>`, `<`, `between`, `in`, `except`(적은 값 제외), `like`(문자 컬럼에서 포함 검색, 대소문자 구분 없음), `is null`, `is not null`
   값에 `or`나 쉼표가 들어 있으면 작은따옴표나 큰따옴표로 감쌉니다. 따옴표는 빼고 검색합니다.
   따옴표가 실제로 들어 있는 값을 찾으려면 입력칸 아래의 체크(따옴표를 값을 감싸는 기호로 읽기)를 끄고 추가합니다. 그 줄은 따옴표를 글자 그대로 찾고, 목록에 "따옴표 그대로"라고 표시됩니다. 체크는 추가할 때의 상태가 그 줄에만 적용됩니다.
6. 정렬 (먼저 넣은 줄이 우선)
   ```
   amount desc
   status
   ```
   형식: `컬럼 [asc|desc]` (빼면 asc)
7. 표시 컬럼 (비우면 전체)
   ```
   status, amount
   ```
   표시하지 않는 컬럼도 조건과 정렬에는 쓸 수 있습니다.
8. 검색: 볼 행 수를 정하고 [검색]을 누릅니다.

3~7은 한 줄씩 입력하고 Enter나 [추가]를 누르면 목록에 들어가고, `×`로 뺍니다. 형식이 맞지 않거나 없는 컬럼이면 그 자리에서 이유를 알려 줍니다. 1~7단계에서는 테이블 이름과 컬럼 정보만 읽고, [검색]을 누를 때 연산합니다.

Parquet·CSV 파일은 파일 이름이 테이블 이름이 됩니다. 이름이 같은 파일이 여럿이면 `폴더_이름_확장자`(예: `sub_orders_csv`)로 구분합니다.

### 결과

- 집계 표는 [집계 계산]을 누르면 지금 조건으로 계산합니다(컬럼별 개수, 빈 값, 고유값, 최소, 최대, 평균). 큰 테이블에서는 오래 걸릴 수 있어 검색과 따로 계산하고, 새로 검색하면 지워집니다.
- 검색, 집계, 저장, 차트가 진행되는 동안에는 누른 버튼이 잠깁니다.
- 결과 표의 문자열은 [검색] 아래에서 정한 글자 수까지만 보이고(기본 40, 0이면 전체), 잘린 값은 마우스를 올리면 전체가 보입니다.
- 결과 표 아래의 [CSV], [Excel], [Parquet]을 누르면 조건에 맞는 전체 행을 파일로 저장합니다(Excel은 1,048,575행까지). CSV는 Excel에서 바로 열어도 한글이 깨지지 않습니다.
- 차트는 X 컬럼, Y 컬럼(개수일 때는 [Y 없음]), 집계 방식(개수·합계·평균), 종류(막대·선)를 골라 [그리기]를 누릅니다. [X 순] 또는 [값 큰 순]으로 최대 50개 그룹까지 표시하고, 표시 컬럼과 상관없이 전체 컬럼에서 고릅니다.
- 차트 크기는 데이터 양에 따라 바뀝니다. 그룹이 5개 이하면 정방형(1:1)이고, 그룹이 늘수록 넓어져 25개 이상이면 16:9가 됩니다. [비율 자동] 대신 [1:1]이나 [16:9]를 골라 고정할 수 있습니다.
- 차트 아래의 [PNG], [JPG]를 누르면 그린 차트를 화면에 보이는 비율 그대로 그림 파일로 저장합니다. 그 왼쪽에서 그림의 모드([라이트]는 흰 배경, [다크]는 어두운 배경)를 고릅니다. 화면 모드와 따로 정합니다.

연결을 바꾸다 실패하면(없는 파일, 틀린 주소 등) 이전 연결이 그대로 유지됩니다.

스크롤바는 스크롤할 때만 내용 위에 반투명하게 나타납니다.

### 화면 모드

왼쪽 패널 오른쪽 위의 [다크 모드] / [라이트 모드]를 누르면 화면 모드가 바뀝니다. 처음에는 Windows 설정을 따르고, 한 번 고르면 다음 실행 때도 그 모드로 열립니다.

화면 모드, 차트 비율, 차트 그림의 모드, 따옴표 체크는 고를 때마다 `%APPDATA%\ibis_search\settings.json`에 저장되어 다음 실행 때도 그대로 쓰입니다. 이 파일을 지우면 처음 상태로 돌아갑니다.

비밀번호는 프로그램이 켜져 있는 동안 메모리에만 둡니다. 차트는 프로그램에 들어 있는 Chart.js 4.5.1(MIT)을 사용해 인터넷 없이 동작합니다.

## 소스로 실행하기

exe를 만들지 않고 같은 프로그램 창을 띄울 수 있습니다.

```bash
pip install -r requirements.txt
```

```bash
python desktop.py
```

DuckDB, Parquet, CSV 외의 DB에 접속하려면 해당 백엔드를 추가로 설치합니다. 설치되지 않은 DB에 접속하면 이 명령을 안내합니다.

```bash
pip install 'ibis-framework[mssql]'      # [] 안은 DB 이름: oracle, clickhouse, snowflake 등
```

## DB별 드라이버

접속하기 전에 그 DB에 필요한 드라이버가 있는지 확인하고, 없으면 설치 방법이나 다운로드 주소를 알려 줍니다. 주소 뒤에 `?키=값&키=값`을 붙이면 그 DB의 추가 접속 설정으로 넘어갑니다.

| DB | 주소 예 | 따로 설치할 것 |
|---|---|---|
| DuckDB | `duckdb://data.duckdb` | 없음 |
| SQLite | `sqlite://data.db` | 없음 |
| MSSQL | `mssql://host:1433/db` | [ODBC Driver 17/18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server) |
| PostgreSQL | `postgres://host:5432/db` | 없음 |
| MySQL | `mysql://host:3306/db` | 없음 |
| Oracle | `oracle://host:1521/db` | 없음 |
| ClickHouse | `clickhouse://host:8123/db` | 없음 |
| Trino | `trino://host:8080/catalog/schema` | 없음 |
| Snowflake | `snowflake://계정/데이터베이스/스키마?warehouse=WH` | 없음 |
| BigQuery | `bigquery://프로젝트/데이터셋` | 없음 (처음 접속 시 Google 로그인) |
| Databricks | `databricks://?server_hostname=호스트&http_path=경로&access_token=토큰` | 없음 |
| Athena | `athena://?s3_staging_dir=s3://버킷/경로&region_name=ap-northeast-2` | 없음 (AWS 자격 증명) |
| Druid, Exasol, Impala, Materialize, RisingWave, SingleStore | `druid://host:8082/druid/v2/sql` 등 | 없음 |
| Spark, Flink | `pyspark://`, `flink://` | [Java](https://adoptium.net/). exe에는 포함되지 않아 소스로 실행할 때만 사용합니다 (`pip install 'ibis-framework[pyspark]'`) |

MSSQL은 설치된 ODBC 드라이버 중 최신 버전을 자동으로 고릅니다. 다른 드라이버를 쓰려면 주소 끝에 `?driver=드라이버이름`을 붙입니다. 아이디·비밀번호를 모두 비우면 Windows 인증으로 접속합니다.

## 라이선스

MIT 라이선스로 배포합니다. 전문은 [LICENSE](LICENSE)에 있습니다. 함께 들어 있는 Chart.js(`static/chart.umd.min.js`)도 MIT 라이선스입니다.
