# si-prep 설계

이 문서는 si-prep의 구조를 설명한다. 어디에 무엇이 있는지, 엑셀 한 행이 어떻게 출력이 되는지, 새 양식을 지원하려면 어디를 고치는지를 다룬다.
사용법은 [README](../README.md), 새 문서를 받았을 때의 절차는 [intake/README.md](intake/README.md)에 있다.

---

## 1. 설계 원칙

| 원칙 | 뜻 |
| --- | --- |
| 원문 보존 | 셀 값은 원문 그대로 저장한다. 비교용 글자(공백 제거·소문자)는 따로 만든다 |
| 근거 없는 연결 금지 | 문서에 적힌 단서(같은 경로, 같은 ID, 사람이 승인한 용어 사전)로만 잇는다. 연결마다 근거 글자와 양쪽 원문 위치를 남긴다 |
| 설정과 코드의 경계 | 시트·열·문서 종류 이름은 설정(YAML)에만 둔다. 코드에는 하나도 없어야 한다(`tests/test_no_hardcode.py`가 검사) |
| 같은 입력 같은 결과 | LLM·무작위·현재 시각·dict 순서에 기대지 않는다. ID까지 같다 |
| 멈추지 말고 드러내기 | 못 읽은 곳은 경고로 남기고 나머지를 계속 처리한다. 설정 오류만 실행 전에 멈춘다 |
| 추정은 표시하기 | 원문이 직접 적지 않은 값(위 값으로 채운 칸 등)은 basis로 표시하고, 경로 연결의 근거로 쓰지 않는다 |

---

## 2. 전체 흐름

```
 project.yaml ─┐
 profiles/*.yaml ┼─▶ config ──(검증 실패면 실행 전 에러)
 glossary.yaml ─┘      │
                       ▼
 엑셀 파일 ─▶ reader ─▶ layout ─▶ boundary ─▶ hierarchy ─▶ extract ─▶ (항목들)
              칸 읽기   머리글·열 역할 항목 경계    분류 경로     항목 초안      │
              병합 색인  표 범위       [등록표]     [등록표]                    ▼
                                                                         link [등록표]
                                                                           │
                                                                           ▼
                                                    chunks ◀── run (ID 부여·검증·저장)
                                                                           │
                         <결과 폴더>/ items.jsonl · links.jsonl · warnings.jsonl · chunks.jsonl · report.md
```

- 모든 단계는 경고를 버리지 않고 `issues`(경고 수집기)에 쌓는다.
- ID는 run이 마지막에 한 번에 붙인다. 순서가 고정되므로 같은 입력이면 같은 ID가 나온다.
- 출력은 저장 직전에 `schema.py` 모델로 한 번 더 검증한다. 여기서 실패하면 코드 버그이므로 에러로 멈춘다.
- 결과 파일은 임시 폴더에 다 쓴 뒤 한 번에 바꿔 넣는다. 결과 폴더의 다른 파일은 건드리지 않는다.

### 2.1 모듈

| 모듈 | 역할 | 모르는 것 |
| --- | --- | --- |
| `schema.py` | 출력 4종의 Pydantic 모델. 출력 형식의 유일한 정의. 쓰는 쪽(검색 코드)이 같이 쓰는 판단 함수(`group_contains` 등) | 엑셀·설정 |
| `config.py` | 프로젝트 설정·프로필·용어 사전 모델, 교차 검증, 시트별 덮어쓰기, `--excel` 대조 | 엑셀 내용(대조 때만 시트·머리글을 읽음) |
| `registry.py` | 「이름 → 함수」 등록표 클래스. hierarchy·boundary·link가 같이 쓴다 | |
| `issues.py` | 경고 초안 수집기 | |
| `reader.py` | openpyxl을 쓰는 유일한 모듈. 칸 값·출처(cell / merge_restored / empty)·숨김·수식·테두리. 병합 색인은 시트당 한 번. 데이터 범위는 `max_row`가 아니라 실제 값·병합 경계로 계산. 파일 형식은 확장자 + 파일 시그니처 | 열의 역할 |
| `layout.py` | 시트 선택, 머리글 합치기(" / "), 열 역할 해석(선택자 → 열 문자), 데이터 범위·끝 표시, 한 시트 여러 표, 표 배치 경고 | 분류·연결 |
| `boundary.py` | 항목 경계 등록표 | |
| `hierarchy.py` | 분류 경로 등록표, 병합 복원·빈칸 채우기·테두리 묶음, 시트 이름 루트 | |
| `extract.py` | 항목 초안: raw_fields, merged_fields, title, ID, 상태, 문서 버전 | |
| `normalize.py` | 보여주기용 경로 글자(" › "), 비교 열쇠, 시트 이름 쪼개기. 순수 함수만 | |
| `link.py` | 연결 열쇠 등록표, 내용 비교(check_content) | 연결 방향(없음) |
| `chunks.py` | 항목 1개 → B1 청크 1개 | |
| `report.py` | 처리 보고서 `report.md`(0절 「먼저 볼 것」 + 1~12절)와 긴 목록 `report_목록.md` | |
| `run.py`, `__main__.py` | 실행 순서(`build`), ID 부여, 저장(`write`), CLI | |
| `glossary_candidates.py` | 짝 없는 항목에서 용어 사전 초안 후보 만들기(사람이 검토해 옮김) | |
| `export_schema.py` | schema.py·config.py → `docs/schema/`, `docs/config_schema/` JSON Schema | |
| `console.py` | 콘솔에서 못 쓰는 글자를 ?로 바꿔 실행이 멈추지 않게. 결과 파일 인코딩은 건드리지 않음 | |

**reader와 layout을 나눈 이유:** reader는 openpyxl만, layout은 설정 해석만 맡는다. 엑셀 라이브러리를 바꾸거나 설정 규칙을 바꿀 때 한쪽만 고치면 되고, 각각 따로 테스트할 수 있다.

### 2.2 호출 관계

```
run.build(project_yaml)
 ├─ config.load_project(path)                    → Project (프로필·용어 사전 포함, 검증 끝난 상태)
 ├─ for doc in project.documents (설정 순서)
 │   └─ for file in doc.files (설정 순서)
 │       ├─ reader.open_workbook(path, issues)    → Workbook | None (미지원·암호 → unsupported)
 │       ├─ extract.read_doc_version(...)          → DocVersion
 │       └─ for sheet in layout.select_sheets(...) (통합 문서 안의 시트 순서)
 │           ├─ sp = config.sheet_profile(profile, sheet.name)      (시트별 덮어쓰기 적용)
 │           ├─ tables = layout.build_tables(sheet, sp, issues)    (한 시트 여러 표면 표마다)
 │           ├─ groups = boundary.REGISTRY.get(sp.item_boundary.method)(...)
 │           ├─ paths  = hierarchy.REGISTRY.get(sp.hierarchy.method)(...)
 │           └─ drafts += extract.make_items(...)
 ├─ items  = IT-000001 …  (번호 부여), 자기 ID 중복 검사
 ├─ for rule in project.link_rules (설정 순서)
 │   └─ link.REGISTRY.get(rule.key)(rule, index, project, issues) → 연결 초안
 ├─ links  = LK-000001 …
 ├─ chunks = chunks.make_chunks(items, ...)
 ├─ warnings = 모두 모아 정렬한 뒤 WN-000001 …
 └─ run.write(...) → 4개 jsonl + report.md + report_목록.md
```

---

## 3. 엑셀 한 행이 출력이 되기까지

합성 기능 문서 `가상몰_기능정의서_v1.2.xlsx`, 시트 `회원`, **7행** 하나를 따라간다.

원문 (4~5행이 두 줄 머리글, B6:B7·C6:C7은 병합):

| | B | C | D | E | F |
| --- | --- | --- | --- | --- | --- |
| 4 | 분류 (B4:D4 병합) | | | 기능명 (E4:E5 병합) | 설명 (F4:F5 병합) |
| 5 | 1단계 | 2단계 | 3단계 | | |
| 6 | 로그인 | 일반 로그인 | 아이디 입력 | 아이디 입력란 | 영문·숫자 4~20자 |
| 7 | *(병합 빈칸)* | *(병합 빈칸)* | 비밀번호 입력 | 비밀번호 입력란 | 8자 이상 |

1. **reader:** B7은 비어 있지만 병합 범위 B6:B7에 속하므로 `Cell(value="로그인", origin="merge_restored")`. D7은 `origin="cell"`.
2. **layout:** 머리글 4·5행을 합쳐 B=`분류 / 1단계`, E=`기능명`. 프로필 선택자 `{header_contains: "1단계"}` → B. 역할: hierarchy=[B,C,D], title=E, description=F.
3. **boundary(row):** 7행 하나가 항목 하나.
4. **hierarchy(columns):** 프로필 `sheet_as_root: true`이므로 시트 이름이 1단계:
   `회원(sheet_name) › 로그인(merge_restored) › 일반 로그인(merge_restored) › 비밀번호 입력(cell)`
5. **extract:** raw_fields에는 **원문 칸 값만** 넣는다. 병합 빈칸 B7·C7은 빠지고 D·E·F만 들어간다. B7·C7 값은 분류 경로의 basis로만 드러난다.
6. **run:** 순서상 두 번째 항목이므로 `IT-000002`.
7. **link:** 규칙 `fo_test`(key=path)가 테스트 문서의 같은 경로 항목과 잇는다. item_id가 작은 쪽이 item_a.
8. **chunks:** 첫 줄 경로, 나머지는 「머리글: 값」(분류 열·제외 열 빼고).

```jsonc
// items.jsonl
{"item_id":"IT-000002","doc_type":"fo","doc_file":"가상몰_기능정의서_v1.2.xlsx","title":"비밀번호 입력란",
 "category_path":[{"level":1,"value":"회원","basis":"sheet_name"},
                  {"level":2,"value":"로그인","basis":"merge_restored"},
                  {"level":3,"value":"일반 로그인","basis":"merge_restored"},
                  {"level":4,"value":"비밀번호 입력","basis":"cell"}],
 "category_path_text":"회원 › 로그인 › 일반 로그인 › 비밀번호 입력",
 "raw_fields":{"D":{"header":"분류 / 3단계","value":"비밀번호 입력"},
               "E":{"header":"기능명","value":"비밀번호 입력란"},"F":{"header":"설명","value":"8자 이상"}},
 "merged_fields":{},
 "locations":[{"file":"가상몰_기능정의서_v1.2.xlsx","sheet":"회원","rows":{"start":7,"end":7},"cols":["B","C","D","E","F"]}],
 "status":"ok","profile_source":"approved", "...":"..."}

// chunks.jsonl
{"chunk_id":"B1-IT-000002",
 "text":"회원 › 로그인 › 일반 로그인 › 비밀번호 입력\n기능명: 비밀번호 입력란\n설명: 8자 이상",
 "source":{"file":"가상몰_기능정의서_v1.2.xlsx","sheet":"회원","rows":{"start":7,"end":7}},
 "meta":{"item_id":"IT-000002","doc_type":"fo","category_path_text":"회원 › 로그인 › 일반 로그인 › 비밀번호 입력","...":"..."}}
```

(ID 숫자는 예시다. 정확한 값은 `tests/fixtures/expected.py`에 있다.)

---

## 4. 확장 지점: 새 방식은 「함수 하나 + 등록」

### 4.1 등록표 세 개

| 등록표 | 설정에서 고르는 곳 | 구현됨 | 이름만 있음(미구현) |
| --- | --- | --- | --- |
| 분류 표현 `hierarchy.REGISTRY` | 프로필 `hierarchy.method` | `columns`(병합 복원, 선택적 fill_down·blank_means_above·border_groups), `none` | `split_cell`, `numbering`, `indent`, `parent_id` |
| 항목 경계 `boundary.REGISTRY` | 프로필 `item_boundary.method` | `row` | `continuation`, `merged_block` |
| 연결 열쇠 `link.REGISTRY` | `link_rules[].key` | `path`, `sheet_to_path`, `path_prefix`, `id_ref`, `glossary` | `name_similarity` |

### 4.2 「알려진 이름」과 「구현된 이름」

- **알려진 이름**은 config의 판별 유니온(`method` 값으로 갈라지는 Pydantic 모델)에서 나온다. `colums` 같은 오타는 실행 전에 설정 에러다.
- **구현된 이름**은 등록표에 함수가 붙은 이름이다. 알려졌지만 미구현이면 실행은 멈추지 않고 그 시트(또는 그 규칙)만 건너뛰며 `unsupported` 경고를 남긴다. 설정 검사도 같은 등록표에 물어 미리 알린다.

### 4.3 함수 모양

```python
@hierarchy.REGISTRY.register("columns")
def columns(table, groups, sp, issues) -> list[list[Step]]: ...   # 항목마다 분류 경로 하나

@boundary.REGISTRY.register("row")
def by_row(table, sp, issues) -> list[RowGroup]: ...             # 데이터 행을 항목 단위로 묶음

@link.REGISTRY.register("path")
def by_path(rule, index, project, issues) -> list[LinkDraft]: ...  # 규칙 하나 실행, 방향 없음
```

- 함수는 같은 입력이면 같은 결과여야 한다.
- 함수는 등급(grade)을 정하지 않는다. method만 정하고, grade는 schema가 method로 고정한다.

### 4.4 새 방식 추가 순서 (예: 들여쓰기 `indent`)

1. `config.py`: 옵션 모델이 이미 있으면 그대로 쓴다.
2. `hierarchy.py`: `@REGISTRY.register("indent")` 함수 하나를 쓴다.
3. `tests/fixtures/make_fixtures.py`에 시트를 더하고 `expected.py`에 나와야 할 경로를 적는다.
4. 테스트를 더한다. 「indent → unsupported」였던 기존 기대값은 이유를 적고 바꾼다.
5. 새 basis 값이 필요하면 스키마에 보기를 더한다(1.x 추가형).

다른 파일(extract, run 등)은 고치지 않는다. 고쳐야 한다면 확장 지점 설계가 틀린 것이다.

---

## 5. 설정

### 5.1 원칙

- 형식은 YAML, 검증은 Pydantic(`extra="forbid"`: 모르는 키는 에러).
- 검증은 **실행 전에 전부** 한다. 하나라도 틀리면 출력을 만들지 않고 틀린 곳을 모두 모아 보여준다.
- 열은 **역할**로 지정한다. 선택자: `{header_contains: "1단계"}`(합친 머리글에 이 글자가 있는 열), `{col: "B"}`(열 문자), `{header_pattern: "<정규식>", all: true}`(hierarchy에서만, 맞는 열을 모두 왼쪽부터).
- 시트는 이름 또는 `*`·`?` 패턴(대소문자 구분)으로 고른다. 정규식보다 설정을 쓰는 사람이 읽기 쉬워서다.
- `approved: true`가 아닌 설정에서 나온 결과는 `profile_source: "auto"`(시험 실행)로 표시한다.

### 5.2 두 층

| 파일 | 담는 것 |
| --- | --- |
| `project.yaml` | `doc_types`(문서 종류 선언), `documents`(종류·프로필·파일 목록, 이 순서가 ID 순서), `link_rules`, `glossary`, `doc_priority` |
| 프로필 `profiles/*.yaml` (문서 종류마다) | `sheets`(읽을 시트·뺄 시트와 이유), `header_rows`, `data_start_row`, `stop_markers`, `columns`(역할 → 선택자), `hierarchy`, `item_boundary`, `sheet_as_root`, `root_separators`, `overview_sheets`, `version`, `id_pattern`, `hidden_rows`, `tables`, `sheet_overrides` |

키 모양은 `docs/config_schema/*.schema.json`에도 있다. 교차 검사는 `python -m si_prep.config <project.yaml>`에서 한다. 예시 전체는 `examples/shop/`.

### 5.3 연결 규칙

**연결에는 방향이 없다.** `docs: [fo, test]`와 `[test, fo]`는 같은 규칙이고, 만들어지는 Link에도 방향이 없다. 쌍 하나를 한 번만 저장하고, 쓰는 쪽이 양쪽에서 찾는다.

| key | 결과 | 찾는 쪽 | 설정 검사 조건 |
| --- | --- | --- | --- |
| `path` | 항목↔항목, path_exact / path_normalized | 필요 없음(대칭) | |
| `sheet_to_path` | 항목↔묶음 | `root_separators`가 있는 프로필 쪽 | 한쪽에만 있어야 함 |
| `path_prefix` | 항목↔묶음 | 규칙의 `group`이 아닌 쪽 | `group` 필수 |
| `id_ref` | 항목↔항목, 명시적 | `ref_ids` 열이 있는 프로필 쪽 | 한쪽에만 있어야 함. 다른 쪽에 `id` 열 |
| `glossary` | `match: exact`면 항목↔항목, `prefix`면 항목↔묶음 | exact는 대칭, prefix는 `group`이 아닌 쪽 | 용어 사전 필수, prefix면 `group` 필수 |

- `sheets`: `docs`와 같은 순서의 두 칸. `overview` / `detail` / 시트 이름·패턴 목록 / `null`(전체).
- `check_content: true`: path·glossary(exact) 연결에서 양쪽 설명 열이 다르면 `content_mismatch` 경고.

### 5.4 분류 빈칸 처리 (`hierarchy: {method: columns}`)

| 설정 | 병합 빈칸 | 병합 아닌 빈칸 |
| --- | --- | --- |
| 기본 | 복원(merge_restored, 확정) | 중간 단계면 basis=empty + `merge_unrestored`, 뒤쪽이면 버림 |
| `fill_down: true` | 복원 | 위 행 값으로 채움(filled_down, **추정**). 이 행에서 새 값이 나오면 그 아래 단계는 채우지 않음 |
| + `blank_means_above: true` | 복원 | 사람이 원문을 보고 「이 시트는 빈칸 = 위와 같음」이라고 선언. 채운 단계는 form_filled(**확정**) |
| + `border_groups: true` | 복원 | 가로 테두리로 나뉜 묶음 안에서만 채움. 선 아래 첫 칸이 비면 채우지 않고 empty |

선언은 시트 단위다(`sheet_overrides`로 시트마다 다르게 줄 수 있다). 테두리는 셀 서식만 읽는다. 조건부 서식·표 스타일로 그린 선은 못 읽는다.

---

## 6. 출력 스키마 (`src/si_prep/schema.py`, v1.4)

모든 모델은 `extra="forbid"`. `schema_version`은 `^1\.\d+$` 모양만 통과한다. 1.x 안의 변경은 보기 값·선택 칸을 더하는 것만 한다(이전 결과 파일도 그대로 통과).

### 6.1 항목 (`items.jsonl`)

| 필드 | 뜻 |
| --- | --- |
| `item_id` | `IT-000001` 모양. 입력이 바뀌면 달라질 수 있다. 버전 사이 추적은 원문 ID로 한다 |
| `category_path` | 단계 목록. 단계마다 `value`와 `basis` |
| `category_path_text` | 보여주기용 「 › 」 글자. 빈 단계는 빼지 않고 `(빈칸)` |
| `raw_fields` | 열 문자 → {머리글, 원문 값}. 원문 칸 값만(병합으로 복원한 값은 넣지 않음) |
| `merged_fields` | 이 행에 걸친 세로 병합 중 시작 칸이 위 행인 것: {머리글, 시작 칸 값, source_row} |
| `title`, `source_id`, `ref_ids` | 제목, 자기 ID, 참조 ID(원문에 있는 글자만) |
| `locations` | 파일·시트·행 범위·열 |
| `status` | 아래 표 |
| `profile_source` | `approved` / `auto` |

**basis**

| 값 | 뜻 | 추정 여부 |
| --- | --- | --- |
| `sheet_name` | 시트 이름 단계 | 확정 |
| `cell` | 그 칸의 원문 | 확정 |
| `merge_restored` | 병합 범위의 시작 칸 값 | 확정 |
| `form_filled` | 사람이 선언한 시트에서 위 값으로 채움 | 확정 |
| `table_title` | 한 시트 여러 표에서 그 표의 제목 행 값 | 확정 |
| `filled_down` | 선언 없이 위 값으로 채움 | **추정** |
| `empty` | 비어 있음 | **추정** |
| `split_cell`, `numbering` | 미구현 방식용 | — |

추정 단계(`INFERRED_BASES`)가 있는 항목은 status가 `ambiguous`이고, **경로를 쓰는 연결(path·sheet_to_path·path_prefix·glossary·묶음 포함)에서 빠진다.** 항목과 청크는 그대로 남고, ID 연결(id_ref)도 그대로 만든다.

**status** (여러 개면 `unparsed > ambiguous > not_written > ok` 순서로 하나)

| 값 | 언제 |
| --- | --- |
| `unparsed` | 일부 칸을 해석하지 못함(참조 칸에 맞는 ID 없음, 자기 ID가 id_pattern과 다름, 수식 오류 값 등) |
| `ambiguous` | 경로에 추정 단계가 있음 |
| `not_written` | description 역할 열이 비어 있음 |
| `ok` | 위에 해당 없음 |

### 6.2 연결 (`links.jsonl`)

- 두 모양 중 하나: 항목↔항목(`item_a`, `item_b`, item_a < item_b) 또는 항목↔묶음(`item`, `group` = 문서 종류 + 경로 앞부분 + 선택 `sheets`).
- 묶음에 드는지는 **단계 단위 앞부분 비교**다(`group_contains`). 묶음 `회원`은 `회원가입 › …` 항목에 걸리지 않는다.
- `evidence_text`가 비면 에러다(근거 없는 연결 금지). `evidence_locations`는 1개 이상.
- method → grade는 모델이 고정한다.

| method | grade |
| --- | --- |
| id_ref | explicit |
| path_exact, path_normalized, glossary | structural |
| name_similarity | inferred (미구현이라 지금은 나오지 않음) |

### 6.3 경고 (`warnings.jsonl`)

| kind | 언제 |
| --- | --- |
| `content_mismatch` | check_content 규칙에서 양쪽 설명이 다름 |
| `unparsed` | 값은 있으나 규칙으로 해석 못함 |
| `unsupported` | 미지원 파일(.xls·암호·가짜 확장자), 알려졌지만 미구현 방식 |
| `unsupported_layout` | 머리글 없는 열의 값 덩어리, 머리글 위 칸, 반복 머리글, 테두리로 묶음을 구분할 수 없는 열 등. 읽는 방식은 그대로 두고 알림 |
| `merge_unrestored` | 분류 중간 단계가 비었는데 복원 못함 |
| `link_unconfirmed` | sheet_to_path·path_prefix에서 대상 묶음을 못 찾음, 요약↔상세 규칙의 요약 쪽 짝 없음 |
| `version_mismatch` | 표지 버전 ≠ 파일 이름 버전 |
| `sheet_skipped` | 숨김 시트, 차트 시트 |
| `hidden_content` | 숨김 행·열을 처리했거나 건너뜀 |
| `header_not_found` | 머리글이 비었거나 필수 역할 열을 못 찾음 → 그 시트(또는 표) 건너뜀 |
| `duplicate_id` | 같은 문서 종류 안에서 자기 ID가 두 번 이상 |
| `ref_unresolved` | 참조 ID가 대상 문서에 없음 |
| `formula_no_value` | 수식 칸에 저장된 계산값 없음 |
| `read_failed` | 지원 형식인데 열지 못함 |

경고 번호는 발생 순서가 아니라 모두 모은 뒤 문서 → 파일 → 시트 → 행 → kind 순서로 정렬해 붙인다.

### 6.4 청크 (`chunks.jsonl`)

- `chunk_id`는 `B1-`, `B0-R-`, `B0-S-` 중 하나로 시작한다. si-prep은 B1만 만든다. B0(비교용 기준선 청크)는 검색 쪽이 만들고 이 모델로 검증한다.
- B1 `text`: 첫 줄 category_path_text, 다음 줄부터 열 순서대로 「머리글: 값」, 병합 값은 「머리글 (병합 L8): 값」.
- 들어가지 않는 칸: 빈 칸, `exclude_from_text` 열, 머리글 없는 열, 뺀 시트·숨김 시트, 표 밖 행.
- `meta`는 평평한 글자 값만(검색 DB 필터용).

---

## 7. 처리 규칙 (주요)

| 주제 | 규칙 |
| --- | --- |
| 결정성 | 집합·dict 순회에 기대지 않고 항상 정렬된 순서 |
| ID 순서 | 항목: documents → files → 시트 → 행. 연결: link_rules 순서 → 짝 순서 |
| 데이터 범위 | `max_row`를 믿지 않는다. 서식만 남은 먼 칸 때문에 범위가 부풀지 않게 값·병합 경계로 다시 계산 |
| 파일 형식 | 확장자 + 파일 시그니처(zip / OLE). 이름만 `.xlsx`인 옛 형식은 `unsupported` |
| 수식 | 저장된 계산값을 쓴다. 없으면 `formula_no_value` |
| 날짜 | ISO 글자(`2026-10-04`, 시각이 있으면 `2026-10-04T09:30:00`) |
| 숨김 | 숨김 시트는 건너뜀. 숨김 행·열은 읽고 `hidden_content`. 프로필 `hidden_rows: skip`이면 숨김 행을 빼고 위치를 남김 |
| 빈 행 | 자기 칸의 원문이 모두 비면 건너뜀(경고 없음) |
| 표 아래 각주 | `stop_markers`로 끊는다. 남은 「값이 하나뿐이고 역할 열이 빈 마지막 행」은 항목으로 만들되 `unparsed` |
| 한 시트 여러 표 | 프로필 `tables`를 설정한 시트만 표마다 나눠 읽는다(제목 행 신호 + 머리글 신호). 설정이 없는 시트는 한 표로 읽는다 |
| 경로 열쇠 | 단계별 공백 제거·소문자, 연속 중복 단계 제거. 글자까지 같으면 path_exact, 열쇠만 같으면 path_normalized |
| ID 비교 | 앞뒤 공백만 빼고 대소문자는 구분 |
| 용어 사전 | 단계 **전체**가 사전 단어일 때만 대표어로 바꿔 비교. 실제로 바꾼 단어가 있을 때만 method=glossary |
| 원문은 데이터 | 셀 문장을 실행·평가하지 않는다. 정규식은 설정에서 온 것만. 네트워크를 쓰지 않는다 |
| 범위 밖 | 취소선·글자색·칸 메모는 읽지 않는다 |

---

## 8. 테스트

### 8.1 합성 시나리오

`tests/fixtures/make_fixtures.py`가 openpyxl로 가상 쇼핑몰 엑셀을 만든다. 실제 문서의 내용·이름은 쓰지 않는다. 기대값은 `tests/fixtures/expected.py`에 숫자·ID·위치까지 적는다.
아래 표는 **설계 목표**다(`expected.FINAL`). 아직 구현하지 않은 방식(split_cell·numbering·continuation·indent)의 시트는 지금 `unsupported` 경고 후 건너뛰며, 테스트는 지금 구현 기준 기대값(`expected.BEFORE_1008`)과 비교한다. `tests/test_expected.py`가 이 표의 줄 수와 `expected.SCENARIOS`가 같은지 확인한다.

| 파일 | 시트·상황 | 나와야 할 것 |
| --- | --- | --- |
| `가상몰_기능정의서_v1.2.xlsx` (fo) | 표지(버전 `v1.3`), 개정이력, 메뉴 시트 `회원`·`주문`·`고객센터`, 요약 시트 `요약`. 두 줄 머리글(4·5행), 분류 열 3단계 병합 | 표지·개정이력 제외. `version_mismatch` 1건 |
| | `고객센터`(흔한 SI 양식 구조): 1행 시트 제목, 2행 업데이트 날짜, 맨 앞 `NO.` 열(역할 없음), 4칸 병합 상단 머리글 「분류」 + 1~4단계, 1단계 12행 세로 병합, 여러 줄 설명, 대부분 빈 `비고` 열 | 항목 12개, 경로 최대 5단계, NO.·비고는 raw_fields에만, 경고 없음 |
| | `회원` 10행: 1단계 있음, 2단계 빈칸(병합 아님), 3단계 있음 | `merge_unrestored` 1건, `회원 › 회원탈퇴 › (빈칸) › 탈퇴 사유`, status `ambiguous`, path 연결 없음 |
| | 설명 칸이 빈 항목 1개 | status `not_written` |
| | `회원` 9행: 3단계 빈칸 | 경로 2단계에서 끝(뒤쪽 빈 단계 버림), 경고 없음 |
| | `요약` 2행: 1행은 메뉴 시트와 설명 같음, 1행은 다름 | 연결 2개(path_exact), `content_mismatch` 1건 |
| | 데이터 아래 `※ 참고` 행 | 그 행부터 무시 |
| `가상몰_관리자기능정의서.xlsx` (bo) | 메뉴 시트 `회원관리`·`주문관리`, 1단계 열에 메뉴 이름(`sheet_as_root: false`) | 항목 6개, 경고 없음 |
| `가상몰_테스트케이스.xlsx` (test) | 시트 `테스트케이스`: 머리글 1줄, fo와 같은 분류 경로 4건 | fo_test: path_exact 3, path_normalized 1(`배송지 변경` ↔ `배송지변경`) |
| | 시트 `BO테스트케이스`: bo와 같은 경로 3건 | bo_test: path_exact 2, path_normalized 1. FO 시트와 섞이지 않음 |
| | 담당자별 결과 열 `결과(검수자1~3)`, 프로필 `exclude_from_text` | 결과 열은 raw_fields에만, 청크 본문에서 빠짐 |
| | `요구사항 ID` 칸: `REQ-001` / `REQ-001, REQ-002` / `REQ-999`(없음) / 빈칸 | test_req 연결 3개(explicit), `ref_unresolved` 1건 |
| | `요구사항 ID` 칸에 패턴과 맞지 않는 글자 1건 | `unparsed` 1건, status `unparsed` |
| `가상몰_정책정의서.xlsx` (policy) | 시트 `주문 - 결제`, `회원 - 로그인`, `쿠폰 - 발급`(fo에 없음) | 항목↔묶음 연결 3개. `쿠폰 - 발급`은 `link_unconfirmed` 1건 |
| | 서술형 시트 `주문 - 배송`: 머리글 B1:C1 병합 「세부 구분」 + 정책 내용, 시트별 덮어쓰기 | 항목 3개(시트 이름 + 2단), 묶음 `주문 › 배송`과 연결 3개 |
| | 목록형 시트 `결제 수단 목록`: 시트 이름에 ` - ` 없음. 규칙 sheets `[["* - *"], null]`로 연결 대상에서 제외 | 항목 3개, 연결·`link_unconfirmed` 없음 |
| `가상몰_요구사항정의서.xlsx` (req) | 자기 ID 열 `REQ-001~003`, 대분류 병합(`고객`) | req_fo_glossary: `고객 › 로그인` ↔ 묶음 `회원 › 로그인` (glossary) |
| | 같은 ID `REQ-003` 두 번 | `duplicate_id` 1건 |
| `가상몰_변형.xlsx` (variation) | `빈칸채움`(fill_down 켬)과 `빈칸채움_끔`(같은 내용) — 분류 3단계, 병합 없음 | 아래 「fill_down 케이스」 표 |
| | `한칸경로`: `회원 > 로그인 > 아이디 찾기` | 설계: basis `split_cell` 3단계 (미구현 → `unsupported`) |
| | `번호`: `1 회원`, `1.1 로그인`, `2.3.1 …`(2.3 없음) | 설계: basis `numbering`, 조상 없으면 `unparsed` (미구현 → `unsupported`) |
| | `이어지는행`: ID 칸이 빈 다음 2행 | 설계: 항목 1개, 3행 범위 (미구현 → `unsupported`) |
| | `오른쪽메모`: 본 표 오른쪽에 빈 열 하나 건너 메모 덩어리 | 본 표 항목은 정상, 메모 덩어리만 `unsupported_layout` 1건 |
| | `역할겹침`: description 선택자에 열 2개가 걸림 | `header_not_found` 1건, 항목 0 |
| | `숨김`(숨김 시트) | `sheet_skipped`, 항목 0 |
| | `표두개`: 빈 행 3줄로 나뉜 표 2개 | 설계: `unsupported_layout` + 시트 건너뜀 |
| | `들여쓰기`: method `indent` | `unsupported`, 항목 0 |
| | `숨김행수식`: 그냥 숨긴 행 + 그룹 접기 숨김 행, 계산값 없는 수식 1칸 | `hidden_content` 1건, `formula_no_value` 1건 |
| | `숨김건너뜀`: 숨김 행 2개, `hidden_rows: skip` | 숨김 행은 항목 없음, `hidden_content` 1건 |
| | `내용병합`: 설명 열이 3행 세로 병합 | 아래 두 항목은 merged_fields에 값, status `not_written` 아님, 청크에 병합 표시 줄 |
| | `분류패턴`: 시트 두 개, 분류 열 2개·3개, `header_pattern` 선택자 하나 | 두 시트 모두 처리, 덮어쓰기 없음 |
| | `분류열부족`: hierarchy 선택자 3개 중 1개가 머리글에 없음 | `header_not_found` 1건, 항목 0 |
| | `각주`: 표 아래 빈 행 1줄 + 번호 열에만 값이 있는 각주 행 | 각주 행은 항목 + `unparsed` 1건 |
| | `부푼범위`: 데이터 아래 먼 행에 서식만 있는 칸 | 실제 데이터 행까지만 처리, 경고 없음 |
| | `표안빈열`: 머리글 범위 안에 값이 거의 없는 빈 열 | 표의 일부로 처리 |
| | `대각선표`: 아래·오른쪽으로 떨어진 두 번째 표 | 설계: `unsupported_layout` + 시트 건너뜀 |
| | `왼쪽덩어리`: 본 표 왼쪽 밖, 빈 열로 떨어진 값 덩어리 | 덩어리만 `unsupported_layout` 1건, 본 표 정상 |
| | `차트`: 차트 시트 | `sheet_skipped` 1건, 항목 0 |
| | `빈시트`: 아무 칸도 없는 시트 | `header_not_found` 1건, 항목 0 |
| | `표여러개`: 한 시트에 표 5개(제목 행 + 「번호」 머리글), 표3은 분류 열 없음 | 표마다 항목(경로 = 표 제목 › 분류1), 표3만 건너뜀 + `header_not_found` 1건 |
| (variation 파일) | `가상몰_옛형식.xls` | `unsupported` 1건, 다른 파일은 정상 |
| | `가상몰_가짜확장자.xlsx`: 이름은 .xlsx인데 실제로는 옛 형식 | `unsupported` 1건 |

**fill_down 케이스** (분류 열: 상위 / 중간 / 하위, 병합 없음)

| 행 | 원문 (상위 / 중간 / 하위) | fill_down 켬 | fill_down 끔 |
| --- | --- | --- | --- |
| 1 | A / B / — | `A › B`, ok | `A › B`, ok |
| 2 | — / — / C | `A › B › C` (A·B filled_down), ambiguous | `(빈칸) › (빈칸) › C` + `merge_unrestored`, ambiguous |
| 3 | — / D / — | `A › D` (하위 C는 번지지 않음), ambiguous | `(빈칸) › D` + `merge_unrestored`, ambiguous |
| 4 | — / E / — | `A › E`, ambiguous | `(빈칸) › E` + `merge_unrestored`, ambiguous |
| 5 | — / — / — | 별도 항목, `A › E` (filled_down), ambiguous | 별도 항목, `(빈칸) › (빈칸) › (빈칸)` + `merge_unrestored`, ambiguous |

### 8.2 테스트 종류

| 종류 | 파일 | 확인하는 것 |
| --- | --- | --- |
| 모듈 단위 | `tests/test_<모듈>.py` | 각 모듈의 규칙. 스키마는 통과·거부 사례 모두 |
| 설정 검증 | `test_config.py`, `test_profile.py`, `test_check.py` | 오타 키·없는 문서 종류·잘못된 정규식·key별 조건 위반이 실행 전 에러 |
| 끝까지 | `test_run.py`, `test_expected.py` | 합성 프로젝트 전체 실행 결과가 기대값과 같음 |
| 결정성 | `test_run.py` | 두 번 실행한 결과 파일이 바이트까지 같음 |
| 계약 | `test_schema_contract.py`, `test_output_contract.py` | 검색 쪽과 같이 쓰는 예시 파일이 통과 |
| 스키마 내보내기 | `test_export_schema.py` | 커밋된 JSON Schema가 지금 코드로 만든 것과 같음 |
| 하드코딩 | `test_no_hardcode.py` | 합성 설정의 시트·열·문서 종류 이름이 `src/` 문자열에 없음 |

---

## 9. 참고한 오픈소스

소스를 읽고 **방식만** 참고했다. 의존성으로 넣지 않았고 코드를 복사하지 않았다.

| 도구 (라이선스) | 가져온 것 | 안 가져온 것과 이유 |
| --- | --- | --- |
| Docling (MIT), 엑셀 백엔드 | 병합 색인을 시트당 한 번 만들기, `max_row` 대신 실제 값·병합 경계, 값 있는 칸 덩어리 찾기(감지까지만). 까다로운 엑셀 상황(부푼 max_row, 표 안 빈 열, 대각선 표, 왼쪽 덩어리, 차트 시트)을 합성 데이터로 | 나뉜 덩어리를 각각 표로 처리하기(머리글·역할을 추측해야 함), 숨김 시트 처리, 칸 값을 문자열로 바꾸기, .xls 변환(외부 프로그램 의존) |
| Unstructured (Apache-2.0), xlsx 파티션 | 위·아래 끝 「값이 하나뿐인 행」 신호 → 각주 행 `unparsed`, 파일 시그니처로 형식 판단, 빈 시트·가짜 확장자 상황 | 행 범위가 겹치는 덩어리 합치기(옆 메모가 본 표에 섞임), 첫 행 머리글 고정, 병합 미복원 |
| StrictDoc (Apache-2.0) | 연결 안 된 항목을 「숫자 + 다시 찾는 목록」으로 보고 → 처리 보고서 4절, 중복·없는 ID를 반드시 드러내기 | 관계 방향(부모·자식), 깨진 참조에서 빌드 멈추기(남이 쓴 엑셀은 깨진 참조가 흔함), 정해진 열 이름 단어로 머리글 찾기 |
| sphinx-needs (MIT) | 연결 종류를 설정에서 이름 붙여 선언 → `link_rules` | outgoing·incoming 방향 저장, 필터 문자열을 `eval()`로 평가(설정 값을 코드로 실행하지 않음) |

---

## 10. 설계 판단 몇 가지

1. **빈 분류 단계는 `(빈칸)`으로 드러낸다.** 빼면 틀린 주소가 정상처럼 보이고, 청크 첫 줄 때문에 검색까지 오해한다.
2. **빈 단계·추정 단계가 있는 항목은 경로 연결에서 뺀다.** 빈칸을 무시하고 비교하면 다른 경로와 잘못 이어질 수 있다. 대신 경고와 보고서 6절로 드러낸다.
3. **사람이 확인한 양식 규칙은 추정이 아니다.** 「빈칸 = 위와 같음」을 사람이 프로필에 선언하면(`blank_means_above`) 채운 값은 form_filled로 확정 취급한다.
4. **연결은 방향 없는 쌍이다.** 같은 사실을 두 번 저장하지 않는다. 어느 쪽에 번호가 적혔는지는 방향이 아니라 근거라서 evidence에 남는다.
5. **링크의 profile_source는 프로젝트 설정과 양쪽 프로필이 모두 approved일 때만 approved다.** 시험 실행 결과가 공식 결과처럼 보이지 않게 한다.
6. **항목 번호는 위치가 아니다.** 정답지·외부 참조는 파일·시트·행·원문 ID로 한다. 새 버전 문서는 파일을 바꾸고 전체를 다시 만든다.
