"""실행 — 설정 검사 → 읽기 → 표 → 경계 → 경로 → 항목 → 연결 → 청크 → 번호 → 4개 파일.

- 번호: 항목은 documents → files → 시트 → 행 순서. 연결은 link_rules 순서 → item_a·item_b(또는 item·group) 순서.
  경고는 모두 모은 뒤 정렬해 붙인다(documents → files → 시트 → 첫 위치 행 → kind → 첫 위치 열 → message,
  위치 없는 경고는 그 시트(없으면 파일)의 맨 앞). 경고의 item_ids는 위치(파일·시트·행)가 항목 행 범위에 걸치는 항목.
- 아직 만들지 않은 방식(시트)·연결 key(규칙)는 건너뛰고 unsupported. 열지 못한 파일도 나머지는 처리한다.
- approved가 아니어도 실행한다(시험 실행, profile_source auto — 평가에 쓰지 않는다).
- 쓰기: 모든 줄을 schema 모델로 검증한 뒤, 임시 폴더에 4개를 다 쓰고 결과 폴더의 4개를 바꿔 넣는다.
  결과 폴더의 다른 파일은 건드리지 않는다. 한 줄에 한 객체, UTF-8(한글 그대로), LF.
  검증·임시 쓰기 단계 실패는 결과 폴더가 전부 이전 그대로. 마지막 바꿔 넣기 중 실패하면 섞일 수 있으므로
  ReplaceError → 종료 코드 3과 「바뀐 파일 / 안 바뀐 파일 / 다시 실행하세요」.
- 처리 보고서(report.md, 긴 목록 전체 report_목록.md)도 같은 임시 폴더에 써서 함께 바꿔 넣는다.
- --out 위치: 저장소 밖이나 저장소의 out 폴더 아래만. 저장소 안 그 밖의 곳은 오류(종료 코드 1).
"""

import json
import os
import shutil
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

from si_prep import boundary, chunks, extract, hierarchy, layout, link, reader, report
from si_prep.config import (ConfigError, check_project, glossary_group_lines, id_ref_targets, needs_id,
                            profile_source, sheet_profile, slot_selects)
from si_prep.issues import Issues
from si_prep.layout import col_number
from si_prep.registry import Unimplemented
from si_prep.schema import Warning_, find_duplicate_links, has_inferred_step

OUTPUT_FILES = ("items.jsonl", "links.jsonl", "warnings.jsonl", "chunks.jsonl")
REPO_ROOT = Path(__file__).resolve().parents[2]
USAGE = "사용법: python -m si_prep --project <project.yaml> --out <결과 폴더(저장소 밖 또는 저장소의 out 폴더 아래, 예: out\\<프로젝트>)>"


@dataclass
class SheetStat:
    doc_type: str
    file: str
    sheet: str
    items: int = 0
    chunks: int = 0
    paths: set = field(default_factory=set)
    chunk_lines: int = 0


@dataclass
class RunResult:
    items: list
    links: list
    warnings: list
    chunks: list
    sheet_stats: list = field(default_factory=list)
    inferred_by_doc: dict = field(default_factory=dict)    # 문서 종류 → 추정 경로라 연결에서 빠지는 항목 수
    empty_body: list = field(default_factory=list)          # (문서 종류, 파일, 시트, 행) 청크를 만들지 않은 항목
    version_missing: list = field(default_factory=list)     # (파일, [「표지」·「파일 이름」])
    roles_missing: list = field(default_factory=list)       # (문서 종류, 파일, 시트, 역할) 선택자에 맞는 열 없음
    trial: bool = False                                     # 승인 전 설정으로 돌린 시험 실행
    config_warnings: int = 0                                # 설정 검사(python -m si_prep.config) 경고 수
    unmatched: list = field(default_factory=list)           # path 규칙별 (rule_id, 왼쪽 종류, 수, 오른쪽 종류, 수)
    glossary_effects: list = field(default_factory=list)    # (줄 번호, 묶음 번호, 생긴 연결, 풀린 짝 없음, 새 내용 차이)
    config: object = None                                   # 검사한 설정(용어 사전 초안 등 뒤 단계용, 출력 안 함)
    index: object = None                                    # link.ItemIndex(항목 초안 + 프로필)
    ids: dict = field(default_factory=dict)                 # id(항목 초안) → 항목 ID (처리 보고서용)
    made_by_rule: dict = field(default_factory=dict)        # 규칙 id → 그 규칙이 만든 연결 초안(건너뛴 규칙은 없음)
    glossary_made: list = field(default_factory=list)       # [(glossary 규칙, 연결 초안)]
    sheet_rows: list = field(default_factory=list)          # (문서, 파일, 시트, 읽음·뺌, 이유, overview, 새 시트)
    structure: list = field(default_factory=list)          # (문서, 파일, 시트, 머리글 줄, 항목, 분류 열, BlankCounts,
                                                            #  fill_down, 선언) — columns 방식 시트만(12절)
    table_counts: list = field(default_factory=list)       # (문서, 파일, 시트, 찾은 표, 건너뛴 표, 제목 없는 표 또는 None)
                                                            #  — tables 설정 시트만(3절)
    above_header: list = field(default_factory=list)       # (파일, 시트, 첫 행, 끝 행, 칸 수) 머리글 위 값 칸(0절 알려진 한계)
    limit_ids: dict = field(default_factory=dict)          # 경고 번호 → 한계 구분(above_header·headerless) — 0절용, 출력 안 함


def _first_file(docs, doc_type):
    return next((f for d in docs if d.doc_type == doc_type for f in d.files), "project.yaml")


def build(project_path, ignore_glossary: bool = False) -> RunResult:
    """실행 결과를 메모리에 만든다(파일은 쓰지 않음). 설정 오류면 ConfigError.
    ignore_glossary: 용어 사전·glossary 규칙 없이(용어 사전 초안 도구용)"""
    checked = check_project(project_path, ignore_glossary=ignore_glossary)
    config, docs = checked.config, checked.documents
    issues = Issues()
    targets = id_ref_targets(config, docs)
    file_rank, sheet_rank = {}, {}
    drafts, stats, version_missing, roles_missing, sheet_rows, structure, table_counts = [], {}, [], [], [], [], []
    above_header = []

    for d in docs:
        source = profile_source(config.approved, d.profile.approved)
        for fi, f in enumerate(d.files):
            file_rank.setdefault(f, (d.index, fi))
            wb = reader.open_workbook(config.input_path / f, issues)
            if wb is None:
                continue
            for si, grid in enumerate(wb.sheets):
                sheet_rank[(f, grid.name)] = si
                entry = layout.sheet_entry(grid.name, d.profile.sheets) if d.profile.sheets else None
                status = ("뺌" if entry is not None and not entry.read else "건너뜀(차트)" if grid.is_chart
                          else "건너뜀(숨김)" if grid.hidden else "읽음")
                sheet_rows.append((d.doc_type, f, grid.name, status, getattr(entry, "reason", None) or "",
                                   slot_selects(grid.name, d.profile, "overview"),
                                   bool(d.profile.sheets) and entry is None))
            version = extract.read_doc_version(wb, d.profile, issues)
            cover = extract.cover_cells(wb, d.profile)   # 표지 버전 읽기가 읽는 칸(머리글 위 칸 경고에서 뺌)
            missing = extract.missing_version_parts(d.profile, version)
            if missing:
                version_missing.append((f, missing))
            for grid in layout.select_sheets(wb, d.profile, issues):
                sp = sheet_profile(d.profile, grid.name)
                try:
                    split = boundary.REGISTRY.get(sp.item_boundary.method)
                    make = hierarchy.REGISTRY.get(sp.hierarchy.method)
                except Unimplemented as e:
                    issues.add("unsupported", f"{f} 시트 \"{grid.name}\": {e.kind} {e.name} 방식은 아직 지원하지 않아 시트를 건너뜁니다",
                               file=f, sheet=grid.name)
                    continue
                required = ("id",) if needs_id(d.doc_type, d.profile, grid.name, targets) else ()
                t_issues = Issues()
                tables = layout.build_tables(grid, sp, f, t_issues, required_roles=required)   # 설정 없으면 표 하나
                issues.items += t_issues.items
                above_header += layout.above_header_warnings(tables, issues, cover)   # 머리글 위 값 칸(알려진 한계)
                if sp.tables is not None:   # 한 시트 여러 표: 처리 보고서 3절 — 찾은 표, 그중 건너뛴 표, 제목 없는 표
                    spans = layout.split_tables(grid, sp.tables, len(sp.header_rows))[0]
                    untitled = sum(s.untitled for s in spans) if sp.tables.first_without_title else None
                    table_counts.append((d.doc_type, f, grid.name, len(spans), len(spans) - len(tables), untitled))
                for table in tables:
                    layout.table_warnings(table, sp, issues)   # 표 배치 경고(떨어진 덩어리·반복 머리글·숨김 열 값)
                    roles_missing += [(d.doc_type, f, grid.name, role) for role, cols in table.matches.items() if not cols]
                    groups = split(table, sp, issues)
                    if sp.hierarchy.method == "columns":
                        structure.append((d.doc_type, f, layout.table_label(table), len(table.header_rows), len(groups),
                                          len(table.roles.get("hierarchy", [])), hierarchy.blank_counts(table, groups),
                                          sp.hierarchy.fill_down, sp.hierarchy.blank_means_above))
                    for dr in extract.make_items(table, groups, make(table, groups, sp, issues), d.doc_type, source,
                                                 version, issues):
                        drafts.append((dr, d.profile))
                if tables:
                    stats.setdefault((d.doc_type, f, grid.name), SheetStat(d.doc_type, f, grid.name))

    extract.check_duplicate_ids([dr for dr, _ in drafts], issues)   # 같은 문서 종류 안 자기 ID 중복
    ids = {id(dr): f"IT-{n:06d}" for n, (dr, _) in enumerate(drafts, start=1)}
    items = [dr.to_item(ids[id(dr)]) for dr, _ in drafts]

    index = link.ItemIndex()
    for dr, profile in drafts:
        index.add(dr, profile)
    link_drafts, path_made, glossary_made, made_by_rule = [], [], [], {}
    for rule in config.link_rules:
        try:
            make_links = link.REGISTRY.get(rule.key)
        except Unimplemented:
            issues.add("unsupported", f"연결 규칙 {rule.id}: {rule.key} 방식은 아직 지원하지 않아 규칙을 건너뜁니다",
                       file=_first_file(docs, rule.docs[0]))
            continue
        made = make_links(rule, index, config, issues)
        if rule.key == "path":
            path_made.append((rule, list(made)))
        if rule.key == "glossary":
            glossary_made.append((rule, list(made)))
        made.sort(key=lambda x: tuple(sorted([ids[id(x.a)], ids[id(x.b)]])) if hasattr(x, "a")
                  else (ids[id(x.item)], x.group.doc_type, x.group.category_path_text))
        link_drafts += made
        made_by_rule[rule.id] = list(made)
    # 모든 규칙 뒤: glossary로 이어진 항목을 반영해 요약 쪽 짝 없음 경고와 규칙별 짝 없음 수를 정한다
    glossary_drafts = [ld for ld in link_drafts if ld.method == "glossary"]
    resolved, unmatched = [], []
    for rule, made in path_made:
        glossary_linked = link.glossary_linked_for(rule, glossary_made)   # 같은 두 쪽 glossary 규칙만(검토 M1)
        resolved += link.warn_overview_unmatched(rule, index, made, glossary_linked, issues)
        left, right = link.unmatched(rule, index, made)
        unmatched.append((rule.id, rule.docs[0], sum(id(d) not in glossary_linked for d in left),
                          rule.docs[1], sum(id(d) not in glossary_linked for d in right)))
    glossary_effects = []
    if config.glossary and config.glossary_data:
        for g, line in enumerate(glossary_group_lines(config.base_dir / config.glossary)):
            glossary_effects.append((line, g, sum(g in ld.glossary_groups for ld in glossary_drafts),
                                     sum(g in r for r in resolved),
                                     sum(g in ld.glossary_groups and getattr(ld, "mismatch", False) for ld in glossary_drafts)))
    links = [ld.to_link(f"LK-{n:06d}", ids) for n, ld in enumerate(link_drafts, start=1)]
    duplicates = find_duplicate_links(links)
    if duplicates:
        raise RuntimeError(f"같은 연결이 두 번 만들어졌습니다(코드 오류): {duplicates}")

    made_chunks, empty_body = [], []
    for dr, _ in drafts:
        stat = stats[(dr.doc_type, dr.doc_file, dr.sheet)]
        stat.items += 1
        stat.paths.add(dr.category_path_text)
        chunk = chunks.make_chunk(dr, ids[id(dr)])
        if chunk is None:
            empty_body.append((dr.doc_type, dr.doc_file, dr.sheet, dr.rows[0]))
            continue
        stat.chunks += 1
        stat.chunk_lines += len(chunk.text.splitlines())
        made_chunks.append(chunk)

    inferred = dict(Counter(dr.doc_type for dr, _ in drafts if has_inferred_step(dr.category_path)))

    attach_duplicate_partners(issues, link_drafts, ids)
    limit_ids = {}
    warnings = _number_warnings(issues, drafts, ids, file_rank, sheet_rank, limit_ids)
    return RunResult(items, links, warnings, made_chunks, list(stats.values()), inferred, empty_body,
                     version_missing, roles_missing, trial=any(x.profile_source == "auto" for x in items + links),   # 용어집만 미승인이어도 연결이 auto
                     config_warnings=len(checked.warnings), unmatched=unmatched, config=config, index=index,
                     glossary_effects=glossary_effects, ids=ids, made_by_rule=made_by_rule,
                     glossary_made=glossary_made, sheet_rows=sheet_rows, structure=structure, table_counts=table_counts,
                     above_header=above_header, limit_ids=limit_ids)


def attach_duplicate_partners(issues, link_drafts, ids) -> None:
    """id_ref가 중복 대상 ID와 이은 연결의 상대(찾는 쪽) 항목을 그 ID의 duplicate_id 경고 item_ids에 넣는다.
    duplicate_id 경고는 위치 = 그 ID 칸들이므로, 연결한 대상 항목의 ID 칸이 위치에 있는 경고를 찾는다"""
    partners = {}
    for d in link_drafts:
        if getattr(d, "dup_target", False):
            key = (d.b.doc_file, d.b.sheet, d.b.rows[0], d.b.id_col)
            partners.setdefault(key, []).append(ids[id(d.a)])
    if not partners:
        return
    for n, issue in enumerate(issues.items):
        if issue.kind != "duplicate_id":
            continue
        extra = [x for l in issue.locations for x in partners.get((l.file, l.sheet, l.rows.start, (l.cols or [None])[0]), [])]
        if extra:
            issues.items[n] = replace(issue, item_ids=tuple(dict.fromkeys(tuple(issue.item_ids) + tuple(extra))))


def _number_warnings(issues, drafts, ids, file_rank, sheet_rank, limit_ids=None):
    """경고 번호 붙이기. limit_ids(dict)를 주면 「알려진 한계」 경고의 번호 → 구분을 채운다(출력 칸 아님)"""
    far = (10 ** 9, 10 ** 9)

    def loc_key(loc):
        return (file_rank.get(loc.file, far), sheet_rank.get((loc.file, loc.sheet), 10 ** 9), loc.rows.start,
                col_number(loc.cols[0]) if loc.cols else 0)

    spans = {}
    for dr, _ in drafts:
        spans.setdefault((dr.doc_file, dr.sheet), []).append((dr.rows[0], dr.rows[1], ids[id(dr)]))

    ordered = []
    for issue in issues:
        locs = sorted(issue.locations, key=loc_key)
        item_ids = list(issue.item_ids)
        for loc in locs:
            for start, end, item_id in spans.get((loc.file, loc.sheet), []):
                if start <= loc.rows.end and loc.rows.start <= end and item_id not in item_ids:
                    item_ids.append(item_id)
        if locs:
            first = loc_key(locs[0])
            key = (first[0], first[1], first[2], issue.kind, first[3], issue.message)
        else:   # 위치 없는 경고: 그 시트(없으면 그 파일)의 맨 앞
            sheet = sheet_rank.get((issue.file, issue.sheet), 10 ** 9) if issue.sheet else -1
            key = (file_rank.get(issue.file, far), sheet, 0, issue.kind, 0, issue.message)
        ordered.append((key, issue, locs, sorted(item_ids)))
    ordered.sort(key=lambda x: x[0])
    if limit_ids is not None:
        limit_ids.update({f"WN-{n:06d}": issue.limit for n, (_, issue, _, _) in enumerate(ordered, start=1) if issue.limit})
    # 위치가 있는 경고의 file·sheet는 (정렬한) 첫 위치를 따른다
    return [Warning_(warning_id=f"WN-{n:06d}", kind=issue.kind, message=issue.message, item_ids=item_ids,
                     locations=locs, file=locs[0].file if locs else issue.file, sheet=locs[0].sheet if locs else issue.sheet)
            for n, (_, issue, locs, item_ids) in enumerate(ordered, start=1)]


class ReplaceError(Exception):
    """마지막 바꿔 넣기 중 실패: 결과 폴더가 이전·이번 실행이 섞였을 수 있음 → 다시 실행해야 함"""

    def __init__(self, replaced, not_replaced, cause):
        super().__init__(f"출력 파일을 바꿔 넣다가 실패했습니다({type(cause).__name__}: {cause})")
        self.replaced, self.not_replaced, self.cause = replaced, not_replaced, cause


def _jsonl(models) -> str:
    return "".join(json.dumps(m.model_dump(mode="json"), ensure_ascii=False) + "\n" for m in models)


def write(result: RunResult, out_dir) -> None:
    """임시 폴더에 4개 + 처리 보고서 2개를 다 쓴 뒤 결과 폴더의 같은 파일들을 바꿔 넣는다. 다른 파일은 건드리지 않는다"""
    out = Path(out_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{out.name}.tmp-", dir=out.parent))
    try:
        contents = dict(zip(OUTPUT_FILES, (result.items, result.links, result.warnings, result.chunks)))
        for name, models in contents.items():
            (tmp / name).write_text(_jsonl(models), encoding="utf-8", newline="\n")
        reports = report.render_all(result)   # report.md + report_목록.md(긴 목록 전체)
        for name, text in reports.items():
            (tmp / name).write_text(text, encoding="utf-8", newline="\n")
        out.mkdir(exist_ok=True)
        replaced = []
        names = OUTPUT_FILES + tuple(reports)
        for name in names:   # 검증·쓰기가 모두 끝난 뒤 바꿔 넣기(각 파일은 원자적으로 교체, 묶음은 아님)
            try:
                os.replace(tmp / name, out / name)
            except OSError as e:
                raise ReplaceError(replaced, [n for n in names if n not in replaced], e) from None
            replaced.append(name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run(project_path, out_dir) -> RunResult:
    result = build(project_path)
    write(result, out_dir)
    return result


def out_location_error(out_dir, repo=None):
    """--out 위치 규칙: 저장소 밖이거나 저장소의 out 폴더 아래(.gitignore·훅으로 보호)면 None.
    저장소 안 그 밖의 곳이면 오류 글자 — 결과·보고서·초안에는 셀 내용이 들어가 git에 올라가거나 읽힐 수 있으므로"""
    root = Path(REPO_ROOT if repo is None else repo).resolve()
    try:
        rel = Path(out_dir).resolve().relative_to(root)
    except ValueError:
        return None
    if rel.parts[:1] == ("out",):
        return None
    return (f"오류: --out({out_dir})이 저장소 안입니다. 결과에는 셀 내용이 들어가므로 저장소의 out 폴더 아래"
            "(예: out\\<프로젝트>)에 두세요")


def summary(result: RunResult) -> str:
    """화면 요약 — 숫자·구조 정보만(셀 내용 없음)"""
    lines = []
    if result.trial:
        lines.append("시험 실행: 승인(approved: true) 전 설정이 섞여 있어 profile_source가 auto인 결과가 있습니다. 평가에 쓰지 마세요")
    kinds = Counter(w.kind for w in result.warnings)
    lines.append(f"항목 {len(result.items)} · 연결 {len(result.links)} · 경고 {len(result.warnings)} · 청크 {len(result.chunks)}")
    if result.config_warnings:
        lines.append(f"설정 검사 경고 {result.config_warnings}개 — 내용은 python -m si_prep.config <project.yaml>로 확인하세요")
    if kinds:
        lines.append("경고 종류: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    lines += ["", "| 문서 | 파일 | 시트 | 항목 수 | 청크 수 | 서로 다른 경로 수 | 청크 평균 줄 수 |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for s in result.sheet_stats:
        avg = f"{s.chunk_lines / s.chunks:.1f}" if s.chunks else "-"
        lines.append(f"| {s.doc_type} | {s.file} | {s.sheet} | {s.items} | {s.chunks} | {len(s.paths)} | {avg} |")
    lines.append("")
    inferred = ", ".join(f"{k} {v}" for k, v in result.inferred_by_doc.items()) or "없음"
    lines.append(f"추정 경로라 연결에서 빠진 항목(문서별): {inferred}")
    if result.unmatched:
        lines.append("규칙별 짝 없는 항목(경고 없음, 추정 경로 제외): "
                     + "; ".join(f"{r} {a} {na} · {b} {nb}" for r, a, na, b, nb in result.unmatched))
    if result.glossary_effects:
        lines.append("용어집 줄별 효과(줄 번호·숫자만, 단어는 안 보임):")
        lines += [f" - {line}줄(groups[{g}]): 연결 {n} · 풀린 짝 없음 {r} · 새 내용 차이 {m}"
                  for line, g, n, r, m in result.glossary_effects]
    lines.append(f"본문이 빈 항목: {len(result.empty_body)}")
    lines += [f" - {t} {f} {s} {r}행" for t, f, s, r in result.empty_body]
    if result.version_missing:
        lines.append("버전을 못 찾은 파일: " + ", ".join(f"{f}({'·'.join(m)})" for f, m in result.version_missing))
    if result.roles_missing:
        lines.append("역할 열을 못 찾은 시트: " + ", ".join(f"{t} {f} {s} {r}" for t, f, s, r in result.roles_missing))
    return "\n".join(lines)


def parse_project_out(argv, usage):
    """--project·--out 두 값만 받는 명령줄 해석(실행·용어집 초안이 같이 씀). 틀리면 usage를 찍고 None"""
    args = list(sys.argv[1:] if argv is None else argv)
    opts = {}
    while args:
        key = args.pop(0)
        if key not in ("--project", "--out") or not args:
            print(usage)
            return None
        opts[key] = args.pop(0)
    if set(opts) != {"--project", "--out"}:
        print(usage)
        return None
    return opts


def main(argv=None) -> int:
    from si_prep.console import replace_unencodable
    replace_unencodable()   # 화면 출력: 인코딩은 그대로, 못 쓰는 글자만 ?(cp949 콘솔에서 멈추지 않게)
    opts = parse_project_out(argv, USAGE)
    if opts is None:
        return 2
    error = out_location_error(opts["--out"])
    if error:
        print(error)
        return 1
    try:
        result = run(opts["--project"], opts["--out"])
    except ConfigError as e:
        print(e)
        return 1
    except ReplaceError as e:   # 섞였을 수 있음: 오류로 알리고 다시 실행하게
        print(e)
        print(f"바뀐 파일: {', '.join(e.replaced) or '없음'}")
        print(f"안 바뀐 파일: {', '.join(e.not_replaced)}")
        print("결과 폴더가 이전 실행과 이번 실행이 섞였을 수 있습니다. 파일을 연 프로그램을 닫고 다시 실행하세요")
        return 3
    print(summary(result))
    print(f"처리 보고서: {Path(opts['--out']) / report.REPORT_FILE} (경로·용어집 단어 등 셀 내용은 이 파일과 {report.LIST_FILE}에만)")
    return 0
