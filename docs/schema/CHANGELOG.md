# 출력 스키마 변경 기록

출력 형식은 `src/si_prep/schema.py` 하나로 정의한다. 1.x 안에서는 **추가형 변경만** 한다(보기 값·기본값 있는 선택 칸 추가). 이전 버전 결과 파일은 새 버전 검증을 그대로 통과한다(`schema_version`은 `^1\.\d+$`). 칸을 없애거나 뜻을 바꾸는 변경은 2.0으로 올린다.

| 버전 | 바뀐 것 | 호환 |
| --- | --- | --- |
| 1.4 | `PathPart.basis`에 `table_title` 추가: 한 시트에 표가 여러 개일 때(프로필 `tables`) 그 표의 제목 행 값. 경로에서 시트 이름 단계 다음, 열 분류 단계 앞. 원문 칸 값이라 추정이 아니다(`INFERRED_BASES`에 없음) | 추가형 |
| 1.3 | `PathPart.basis`에 `form_filled` 추가: 사람이 프로필에서 「빈칸 = 위와 같음」(`hierarchy.blank_means_above`)을 선언한 시트에서 병합 없는 빈칸을 위 값으로 채운 단계. 추정이 아니므로 확정 연결·묶음에 들어간다 | 추가형 |
| 1.2 | `GroupRef.sheets` 추가(선택): 묶음을 그 시트들의 항목으로 제한. 경고 kind `read_failed` 추가(지원 형식인데 열지 못함). `group_contains`가 추정 경로 항목을 묶음에서 뺌 | 추가형. 단 `group_contains` 결과가 줄어드는 판단 함수 변경이라 쓰는 쪽에 알림 |
| 1.1 | `Item`·`Link`·`Warning` 모델 구현, `Item.merged_fields` 추가(기본 `{}`). 판단 함수 `path_text`·`path_starts_with`·`group_contains`·`find_duplicate_links`. 계약 예시 `tests/fixtures/output_contract_examples.jsonl` | 처음 구현 |
| 1.0 | 위치(`RowRange`·`Location`·`ChunkSource`)와 청크(`Chunk`). 계약 예시 `tests/fixtures/chunk_contract_examples.jsonl` | — |
