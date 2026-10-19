"""si-prep: SI 프로젝트 산출물 전처리 도구."""

import importlib.metadata

# 버전은 pyproject.toml 한 곳에서만 정하고, 설치 기록에서 읽는다.
# 설치하지 않고 경로만 추가해 import한 경우(설치 기록 없음)에는 로컬 표시 버전을 쓴다.
try:
    __version__ = importlib.metadata.version("si_prep")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0+local"
