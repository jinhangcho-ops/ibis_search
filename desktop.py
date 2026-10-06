"""검색 화면을 프로그램 창으로 연다. exe의 실행 파일이자 유일한 실행 방법."""
import os
import threading

import webview
from werkzeug.serving import make_server

from app import KEY, app

server = make_server("127.0.0.1", 0, app)  # 0: 비어 있는 포트를 자동으로 고른다.
threading.Thread(target=server.serve_forever, daemon=True).start()

webview.settings["ALLOW_DOWNLOADS"] = True  # 결과·차트 내보내기
# 스크롤바를 내용 위에 겹쳐 그리고, 스크롤할 때만 보이게 한다(창을 만들기 전에 정해야 한다). 이미 있는 값 뒤에 덧붙인다.
ARGS = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"
os.environ[ARGS] = (os.environ.get(ARGS, "") + " --enable-features=OverlayScrollbar").strip()
# 열쇠를 아는 이 창만 화면을 열 수 있다(브라우저로 주소만 열면 거부된다).
webview.create_window("Ibis 검색", f"http://127.0.0.1:{server.server_port}/?key={KEY}", width=1400, height=900)
webview.start()  # 창을 닫으면 여기서 끝나고, 서버 스레드도 함께 종료된다.
