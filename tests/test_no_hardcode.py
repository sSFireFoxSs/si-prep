"""하드코딩 자동 점검 — 문서마다 다른 이름(시트·열·문서 종류·파일)이 src/ 코드 문자열에 없어야 한다. 독스트링·주석은 설명이라 보지 않는다.

- 합성 설정(shop)에 나오는 이름: 늘 검사
- 실제 문서 이름: 진단표(docs/intake/*.md, 커밋 안 됨)의 실제 용어를 읽어 검사, 진단표가 없으면 건너뜀.
  실패해도 실제 용어는 출력하지 않는다(개수와 위치만)
- 걸리는 기준: 코드 문자열(앞뒤 공백 뺌)이 이름과 같거나, 4글자 이상 이름이 문자열 안에 있음.
  2~3글자 일반 단어(경로·이름·번호 등)는 오류 문장에도 쓰이므로 문자열 전체가 그 이름일 때만 본다
"""

import ast
import re
from pathlib import Path

import pytest
import yaml

import real_terms
from conftest import SHOP_DIR as SHOP

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "si_prep"


def _code_strings():
    """(파일 이름, 줄, 글자) — src의 문자열 리터럴(f-string 조각 포함), 모듈·클래스·함수 독스트링 제외"""
    out = []
    for path in sorted(SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    docs.add(id(first.value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                out.append((path.name, node.lineno, node.value))
    return out


def _selector_names(sel, names):
    if isinstance(sel, dict):
        for k in ("header_contains", "header_pattern"):
            if isinstance(sel.get(k), str):
                names.add(sel[k])
    elif isinstance(sel, list):
        for s in sel:
            _selector_names(s, names)


def _shop_names():
    """shop 설정의 시트 이름·열 이름(선택자 글자)·문서 종류(id·이름)·파일 이름"""
    project = yaml.safe_load((SHOP / "project.yaml").read_text(encoding="utf-8"))
    names = set()
    for t in project["doc_types"]:
        names |= {t["id"], t["name"]}
    for d in project["documents"]:
        names |= {Path(f).stem for f in d["files"]}
    for rule in project["link_rules"]:
        for slot in rule.get("sheets") or []:
            if isinstance(slot, list):
                names |= set(slot)
    for path in sorted((SHOP / "profiles").glob("*.yaml")):
        p = yaml.safe_load(path.read_text(encoding="utf-8"))
        names |= {e["name"] for e in p.get("sheets") or []}
        names |= set(p.get("overview_sheets") or [])
        if isinstance(p.get("version"), dict) and p["version"].get("cover_sheet"):
            names.add(p["version"]["cover_sheet"])
        for o in p.get("sheet_overrides") or []:
            names |= set(o.get("sheets") or [])
        for part in [p] + list(p.get("sheet_overrides") or []):
            for sel in (part.get("columns") or {}).values():
                _selector_names(sel, names)
            tables = part.get("tables") or {}                       # 표 머리글 신호 정규식(양식 글자)
            if (tables.get("header_row") or {}).get("pattern"):
                names.add(tables["header_row"]["pattern"])
    return {n for n in names if isinstance(n, str) and n.strip()}


def _hits(names, strings):
    """[(이름, [(파일, 줄)])] — 걸리는 기준은 모듈 설명. 영문·숫자만인 이름(예: 'fo')은 낱말 단위로 찾는다"""
    out = []
    for name in sorted(names):
        if re.fullmatch(r"[A-Za-z0-9_.]+", name):
            rx = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")
            inside = lambda s: rx.search(s)
        else:
            inside = lambda s: name in s
        found = [(f, line) for f, line, s in strings if s.strip() == name or (len(name) >= 4 and inside(s))]
        if found:
            out.append((name, found))
    return out


def test_shop_names_not_in_src_strings():
    names = _shop_names() - real_terms.ALLOWED_GENERIC_WORDS
    assert len(names) > 20                                   # 이름을 실제로 모았는지
    hits = _hits(names, _code_strings())
    if hits:   # 합성 이름이라 그대로 보여도 됨
        pytest.fail("\n".join(f"{n!r}: {where}" for n, where in hits), pytrace=False)


@pytest.mark.skipif(not real_terms.has_intake(), reason="진단표 없음(실제 용어 검사 건너뜀)")
def test_real_terms_not_in_src_strings():
    terms = real_terms.load_real_terms() - real_terms.ALLOWED_GENERIC_WORDS
    hits = _hits(terms, _code_strings())
    if hits:   # assert를 쓰면 pytest가 용어를 화면에 찍으므로 개수와 위치만 담아 실패시킨다
        where = sorted({f"{f}:{line}" for _, found in hits for f, line in found})
        pytest.fail(f"실제 용어 {len(hits)}개가 src 코드 문자열에 있음(용어는 출력 안 함): {where}", pytrace=False)
