"""실제 용어 읽기(real_terms): 진단표의 「실제 용어」 절만 읽는다. 열 이름은 흔한 양식 단어라 오탐이 나므로 읽지 않는다"""

import real_terms

INTAKE = """# 진단표

## 실제 용어

- 시트: 가나시트, 다라시트
- 메뉴: 마바메뉴 (괄호 설명)

## 열 이름과 역할

| 시트 | 열 이름 → 역할 | 비고 |
| --- | --- | --- |
| 가나시트 | `흔한열이름` → id, `기대결과열` → title | |
"""


def test_load_real_terms_reads_only_real_terms_section(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("## 실제 용어\n\n- 시트: 읽으면안됨\n", encoding="utf-8")
    (tmp_path / "2026-10-13_가상.md").write_text(INTAKE, encoding="utf-8")
    monkeypatch.setattr(real_terms, "INTAKE_DIR", tmp_path)
    assert real_terms.load_real_terms() == {"가나시트", "다라시트", "마바메뉴"}


def _load(tmp_path, monkeypatch, body):
    (tmp_path / "2026-10-13_가상.md").write_text(f"# 진단표\n\n## 실제 용어\n\n{body}\n", encoding="utf-8")
    monkeypatch.setattr(real_terms, "INTAKE_DIR", tmp_path)
    return real_terms.load_real_terms()


def test_parentheses_inside_name_kept(tmp_path, monkeypatch):
    # 시트 이름 안의 괄호는 이름의 일부(공백 없이 붙음). 공백 뒤 괄호만 설명으로 뺀다
    terms = _load(tmp_path, monkeypatch, "- 시트: 가나목록(관리자), 다라 (설명), 마바(1)(2)")
    assert terms == {"가나목록(관리자)", "다라", "마바(1)(2)"}


def test_backticks_keep_comma_and_spaced_parentheses(tmp_path, monkeypatch):
    # 쉼표+공백이나 공백 뒤 괄호가 이름에 있으면 백틱으로 감싼다 — 백틱 안은 그대로, 뒤 설명 괄호는 뺀다
    terms = _load(tmp_path, monkeypatch, "- 시트: `가나, 다라`, `마바 (사)` (설명), 아자,차카")
    assert terms == {"가나, 다라", "마바 (사)", "아자,차카"}
