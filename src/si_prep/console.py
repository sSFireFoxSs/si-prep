"""화면 출력 설정. 윈도 cp949 콘솔에서 화면에 못 쓰는 글자(› 등) 때문에 실행이 멈추지 않게,
프로그램 시작 때 표준 출력·오류의 인코딩은 그대로 두고 못 쓰는 글자만 ?로 바꾼다(errors=replace).
인코딩을 UTF-8로 바꾸면 PowerShell 리다이렉트·파이프가 cp949로 읽어 한글이 깨지므로 인코딩은 건드리지 않는다.
PYTHONIOENCODING이 설정돼 있으면 사람이 정한 것이므로 그대로 따른다. 결과 파일 쓰기(run.write 등)는 건드리지 않는다.
"""

import os
import sys


def replace_unencodable(*streams) -> None:
    """streams(기본: sys.stdout, sys.stderr)의 errors만 replace로(인코딩은 그대로). PYTHONIOENCODING이 있거나
    reconfigure가 없는 스트림(테스트 캡처 등)은 그대로"""
    if os.environ.get("PYTHONIOENCODING"):
        return
    for stream in streams or (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
