"""패키지가 설치되어 import되고, 설치된 버전을 읽을 수 있는지 확인한다.
설치하지 않고 경로만 추가해 import해도 되는지(버전은 0.0.0+local)도 확인한다."""

import importlib
import importlib.metadata
import shutil
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import si_prep

SRC = Path(__file__).resolve().parents[1] / "src"


def test_import_is_regular_package():
    # 빈 폴더만 있어도 namespace package로 import가 될 수 있으므로
    # __init__.py가 있는 일반 패키지인지(__file__이 있는지)까지 본다.
    assert si_prep.__file__ is not None


def test_installed_version_readable():
    installed = version("si_prep")
    assert installed
    assert si_prep.__version__ == installed


def test_import_by_path_without_install(tmp_path):
    # 설치 기록이 전혀 없는 상황: 패키지 폴더만 임시 폴더로 복사(src의 *.egg-info 없이)하고,
    # -S로 site-packages도 끈 채 그 경로만 추가해 import
    shutil.copytree(SRC / "si_prep", tmp_path / "si_prep", ignore=shutil.ignore_patterns("__pycache__"))
    code = f"import sys; sys.path.insert(0, {str(tmp_path)!r}); import si_prep; print(si_prep.__version__)"
    out = subprocess.run([sys.executable, "-S", "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "0.0.0+local"


def test_version_fallback_when_not_installed(monkeypatch):
    def not_installed(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", not_installed)
    try:
        assert importlib.reload(si_prep).__version__ == "0.0.0+local"
    finally:
        monkeypatch.undo()
        importlib.reload(si_prep)  # 설치된 경우 동작으로 되돌림
    assert si_prep.__version__ == version("si_prep")
