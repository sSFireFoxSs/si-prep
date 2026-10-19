"""합성 데이터 기대값 두 벌.

- FINAL: 설계한 기능이 모두 구현된 뒤 나와야 할 결과. IT·LK·WN 번호까지 비교한다.
- BEFORE_1008: 지금 구현된 기능까지의 결과(미구현 방식은 unsupported로 건너뜀). 번호 없이 위치(파일·시트·행)로만 비교한다.

si_prep 코드를 쓰지 않고, 생성기(make_fixtures.py)가 어느 칸에 무엇을 넣었는지로만 적었다.
tests/test_expected.py가 이 값이 생성된 엑셀 칸과 맞는지 대조한다.
규칙: docs/DESIGN.md 6·7장(출력 모양, 경고 번호 정렬).

경로 단계는 (값, basis, 열 문자) — 열이 없는 단계(sheet_name, 번호 방식의 빈 단계)는 None.
경고 위치는 (시트, 시작 행, 끝 행, 열 목록 또는 None).
"""

REQ = "가상몰_요구사항정의서.xlsx"
FO = "가상몰_기능정의서_v1.2.xlsx"
POLICY = "가상몰_정책정의서.xlsx"
TEST = "가상몰_테스트케이스.xlsx"
BO = "가상몰_관리자기능정의서.xlsx"
TC_BO = "BO테스트케이스"
VAR = "가상몰_변형.xlsx"
XLS = "가상몰_옛형식.xls"
FAKE = "가상몰_가짜확장자.xlsx"
TC = "테스트케이스"


def P(value, basis, col=None):
    return (value, basis, col)


def _item(n, doc_type, file, sheet, rows, path, path_text, *, status="ok", title=None,
          source_id=None, ref_ids=(), raw="", merged=None):
    rows = (rows, rows) if isinstance(rows, int) else rows
    return {"item_id": f"IT-{n:06d}", "doc_type": doc_type, "file": file, "sheet": sheet, "rows": rows,
            "path": path, "path_text": path_text, "status": status, "title": title,
            "source_id": source_id, "ref_ids": list(ref_ids), "raw": list(raw), "merged": merged or {}}


def _link(n, rule_id, method, grade, a=None, b=None, item=None, group=None):
    link = {"link_id": f"LK-{n:06d}", "rule_id": rule_id, "method": method, "grade": grade}
    if item:
        link.update(item=f"IT-{item:06d}", group=group)
    else:
        link.update(item_a=f"IT-{a:06d}", item_b=f"IT-{b:06d}")
    return link


def _warn(n, kind, file, sheet, locations=(), items=()):
    """경고 기대값. 필드는 Warning 모델에 있는 것만(message 제외)."""
    return {"warning_id": f"WN-{n:06d}", "kind": kind, "file": file, "sheet": sheet,
            "locations": [(s, a, b, list(c) if c else None) for s, a, b, c in locations],
            "item_ids": [f"IT-{i:06d}" for i in items]}


# 자주 쓰는 경로 조각
MEMBER, ORDER, CS = P("회원", "sheet_name"), P("주문", "sheet_name"), P("고객센터", "sheet_name")


# ======================================================================
# FINAL
# ======================================================================

FINAL_ITEMS = [
    # ---- 요구사항 (req) — 헤더 1행, B 대분류 C 중분류 D ID E 요구사항명 F 설명
    _item(1, "req", REQ, "요구사항", 2, [P("고객", "cell", "B"), P("로그인", "cell", "C")], "고객 › 로그인",
          title="로그인 기능", source_id="REQ-001", raw="BCDEF"),
    _item(2, "req", REQ, "요구사항", 3, [P("고객", "merge_restored", "B"), P("문의", "cell", "C")], "고객 › 문의",
          title="1:1 문의 기능", source_id="REQ-002", raw="CDEF"),
    _item(3, "req", REQ, "요구사항", 4, [P("주문", "cell", "B"), P("결제", "cell", "C")], "주문 › 결제",
          title="결제 기능", source_id="REQ-003", raw="BCDEF"),
    _item(4, "req", REQ, "요구사항", 5, [P("주문", "cell", "B"), P("배송", "cell", "C")], "주문 › 배송",
          title="배송지 변경 기능", source_id="REQ-003", raw="BCDEF"),

    # ---- 기능정의서 (fo) 회원 — 헤더 4·5행, B~D 분류, E 기능명, F 설명, 시트 이름이 1단계
    _item(5, "fo", FO, "회원", 6, [MEMBER, P("로그인", "cell", "B"), P("일반 로그인", "cell", "C"),
                                   P("아이디 입력", "cell", "D")],
          "회원 › 로그인 › 일반 로그인 › 아이디 입력", title="아이디 입력란", raw="BCDEF"),
    _item(6, "fo", FO, "회원", 7, [MEMBER, P("로그인", "merge_restored", "B"), P("일반 로그인", "merge_restored", "C"),
                                   P("비밀번호 입력", "cell", "D")],
          "회원 › 로그인 › 일반 로그인 › 비밀번호 입력", title="비밀번호 입력란", raw="DEF"),
    _item(7, "fo", FO, "회원", 8, [MEMBER, P("로그인", "merge_restored", "B"), P("간편 로그인", "cell", "C"),
                                   P("소셜 계정 선택", "cell", "D")],
          "회원 › 로그인 › 간편 로그인 › 소셜 계정 선택", status="not_written", title="소셜 로그인 버튼", raw="CDE"),
    _item(8, "fo", FO, "회원", 9, [MEMBER, P("회원가입", "cell", "B"), P("약관 동의", "cell", "C")],
          "회원 › 회원가입 › 약관 동의", title="약관 동의 화면", raw="BCEF"),
    _item(9, "fo", FO, "회원", 10, [MEMBER, P("회원탈퇴", "cell", "B"), P(None, "empty", "C"), P("탈퇴 사유", "cell", "D")],
          "회원 › 회원탈퇴 › (빈칸) › 탈퇴 사유", status="ambiguous", title="탈퇴 사유 선택", raw="BDEF"),
    # 주문
    _item(10, "fo", FO, "주문", 6, [ORDER, P("결제", "cell", "B"), P("결제 수단", "cell", "C"), P("카드 결제", "cell", "D")],
          "주문 › 결제 › 결제 수단 › 카드 결제", title="카드 결제 버튼", raw="BCDEF"),
    _item(11, "fo", FO, "주문", 7, [ORDER, P("결제", "merge_restored", "B"), P("결제 수단", "merge_restored", "C"),
                                    P("무통장 입금", "cell", "D")],
          "주문 › 결제 › 결제 수단 › 무통장 입금", title="입금 계좌 안내", raw="DEF"),
    _item(12, "fo", FO, "주문", 8, [ORDER, P("배송", "cell", "B"), P("배송지변경", "cell", "C")],
          "주문 › 배송 › 배송지변경", title="배송지 변경 화면", raw="BCEF"),
    # 고객센터 (흔한 SI 양식 구조) — B NO., C~F 분류 4단계, G 기능명, H 설명, I 비고
    _item(13, "fo", FO, "고객센터", 6, [CS, P("문의", "cell", "C"), P("문의 작성", "cell", "D"), P("문의 종류", "cell", "E"),
                                       P("주문 문의", "cell", "F")],
          "고객센터 › 문의 › 문의 작성 › 문의 종류 › 주문 문의", title="주문 문의 선택", raw="BCDEFGH"),
    _item(14, "fo", FO, "고객센터", 7, [CS, P("문의", "merge_restored", "C"), P("문의 작성", "merge_restored", "D"),
                                       P("문의 종류", "merge_restored", "E"), P("배송 문의", "cell", "F")],
          "고객센터 › 문의 › 문의 작성 › 문의 종류 › 배송 문의", title="배송 문의 선택", raw="BFGH"),
    _item(15, "fo", FO, "고객센터", 8, [CS, P("문의", "merge_restored", "C"), P("문의 작성", "merge_restored", "D"),
                                       P("문의 종류", "merge_restored", "E"), P("기타 문의", "cell", "F")],
          "고객센터 › 문의 › 문의 작성 › 문의 종류 › 기타 문의", title="기타 문의 선택", raw="BFGH"),
    _item(16, "fo", FO, "고객센터", 9, [CS, P("문의", "merge_restored", "C"), P("문의 작성", "merge_restored", "D"),
                                       P("본문 입력", "cell", "E")],
          "고객센터 › 문의 › 문의 작성 › 본문 입력", title="본문 입력란", raw="BEGH"),
    _item(17, "fo", FO, "고객센터", 10, [CS, P("문의", "merge_restored", "C"), P("문의 작성", "merge_restored", "D"),
                                        P("사진 첨부", "cell", "E")],
          "고객센터 › 문의 › 문의 작성 › 사진 첨부", title="사진 첨부 버튼", raw="BEGHI"),
    _item(18, "fo", FO, "고객센터", 11, [CS, P("문의", "merge_restored", "C"), P("문의 내역", "cell", "D"),
                                        P("목록", "cell", "E")],
          "고객센터 › 문의 › 문의 내역 › 목록", title="문의 목록 화면", raw="BDEGH"),
    _item(19, "fo", FO, "고객센터", 12, [CS, P("문의", "merge_restored", "C"), P("문의 내역", "merge_restored", "D"),
                                        P("상세", "cell", "E"), P("답변 보기", "cell", "F")],
          "고객센터 › 문의 › 문의 내역 › 상세 › 답변 보기", title="답변 보기 화면", raw="BEFGH"),
    _item(20, "fo", FO, "고객센터", 13, [CS, P("문의", "merge_restored", "C"), P("문의 내역", "merge_restored", "D"),
                                        P("상세", "merge_restored", "E"), P("추가 문의", "cell", "F")],
          "고객센터 › 문의 › 문의 내역 › 상세 › 추가 문의", title="추가 문의 버튼", raw="BFGH"),
    _item(21, "fo", FO, "고객센터", 14, [CS, P("문의", "merge_restored", "C"), P("문의 내역", "merge_restored", "D"),
                                        P("삭제", "cell", "E")],
          "고객센터 › 문의 › 문의 내역 › 삭제", title="문의 삭제 버튼", raw="BEGHI"),
    _item(22, "fo", FO, "고객센터", 15, [CS, P("문의", "merge_restored", "C"), P("답변 알림", "cell", "D"),
                                        P("앱 알림", "cell", "E")],
          "고객센터 › 문의 › 답변 알림 › 앱 알림", title="앱 알림 설정", raw="BDEGH"),
    _item(23, "fo", FO, "고객센터", 16, [CS, P("문의", "merge_restored", "C"), P("답변 알림", "merge_restored", "D"),
                                        P("문자 알림", "cell", "E")],
          "고객센터 › 문의 › 답변 알림 › 문자 알림", title="문자 알림 설정", raw="BEGH"),
    _item(24, "fo", FO, "고객센터", 17, [CS, P("문의", "merge_restored", "C"), P("답변 알림", "merge_restored", "D"),
                                        P("메일 알림", "cell", "E")],
          "고객센터 › 문의 › 답변 알림 › 메일 알림", title="메일 알림 설정", raw="BEGH"),
    # 요약 (overview) — B 메뉴가 1단계, 시트 이름은 경로에 안 씀
    _item(25, "fo", FO, "요약", 6, [P("회원", "cell", "B"), P("로그인", "cell", "C"), P("일반 로그인", "cell", "D"),
                                    P("아이디 입력", "cell", "E")],
          "회원 › 로그인 › 일반 로그인 › 아이디 입력", title="아이디 입력란", raw="BCDEFG"),
    _item(26, "fo", FO, "요약", 7, [P("주문", "cell", "B"), P("결제", "cell", "C"), P("결제 수단", "cell", "D"),
                                    P("카드 결제", "cell", "E")],
          "주문 › 결제 › 결제 수단 › 카드 결제", title="카드 결제 버튼", raw="BCDEFG"),

    # ---- 관리자 기능정의서 (bo) — 헤더 4·5행, B~D 분류(1단계 = 메뉴 이름), E 기능명, F 설명, 시트 이름은 경로에 안 씀
    _item(27, "bo", BO, "회원관리", 6, [P("회원관리", "cell", "B"), P("회원 목록", "cell", "C"), P("검색", "cell", "D")],
          "회원관리 › 회원 목록 › 검색", title="회원 검색", raw="BCDEF"),
    _item(28, "bo", BO, "회원관리", 7, [P("회원관리", "merge_restored", "B"), P("회원 목록", "merge_restored", "C"),
                                       P("엑셀 내려받기", "cell", "D")],
          "회원관리 › 회원 목록 › 엑셀 내려받기", title="내려받기 버튼", raw="DEF"),
    _item(29, "bo", BO, "회원관리", 8, [P("회원관리", "merge_restored", "B"), P("회원 상세", "cell", "C")],
          "회원관리 › 회원 상세", title="회원 상세 화면", raw="CEF"),
    _item(30, "bo", BO, "주문관리", 6, [P("주문관리", "cell", "B"), P("주문 목록", "cell", "C"), P("상태 변경", "cell", "D")],
          "주문관리 › 주문 목록 › 상태 변경", title="상태 변경 버튼", raw="BCDEF"),
    _item(31, "bo", BO, "주문관리", 7, [P("주문관리", "merge_restored", "B"), P("주문 목록", "merge_restored", "C"),
                                       P("송장 입력", "cell", "D")],
          "주문관리 › 주문 목록 › 송장 입력", title="송장 입력란", raw="DEF"),
    _item(32, "bo", BO, "주문관리", 8, [P("주문관리", "merge_restored", "B"), P("환불 처리", "cell", "C")],
          "주문관리 › 환불 처리", title="환불 처리 화면", raw="CEF"),

    # ---- 정책정의서 (policy) — 분류 열 없음, 시트 이름을 " - "로 나눠 경로
    _item(33, "policy", POLICY, "주문 - 결제", 2, [P("주문", "sheet_name"), P("결제", "sheet_name")], "주문 › 결제",
          title="결제 한도", raw="BC"),
    _item(34, "policy", POLICY, "주문 - 결제", 3, [P("주문", "sheet_name"), P("결제", "sheet_name")], "주문 › 결제",
          title="결제 취소", raw="BC"),
    _item(35, "policy", POLICY, "회원 - 로그인", 2, [P("회원", "sheet_name"), P("로그인", "sheet_name")], "회원 › 로그인",
          title="로그인 실패 제한", raw="BC"),
    _item(36, "policy", POLICY, "쿠폰 - 발급", 2, [P("쿠폰", "sheet_name"), P("발급", "sheet_name")], "쿠폰 › 발급",
          title="쿠폰 발급 조건", raw="BC"),
    # 서술형 (덮어쓰기: 분류 B·C 열 문자 선택자, D 정책 내용) — title 역할 없음
    _item(37, "policy", POLICY, "주문 - 배송", 2, [P("주문", "sheet_name"), P("배송", "sheet_name"),
                                                 P("배송비", "cell", "B"), P("기본", "cell", "C")],
          "주문 › 배송 › 배송비 › 기본", raw="BCD"),
    _item(38, "policy", POLICY, "주문 - 배송", 3, [P("주문", "sheet_name"), P("배송", "sheet_name"),
                                                 P("배송비", "merge_restored", "B"), P("도서 산간", "cell", "C")],
          "주문 › 배송 › 배송비 › 도서 산간", raw="CDE"),
    _item(39, "policy", POLICY, "주문 - 배송", 4, [P("주문", "sheet_name"), P("배송", "sheet_name"), P("배송 기간", "cell", "B")],
          "주문 › 배송 › 배송 기간", raw="BD"),
    # 목록형 (덮어쓰기: title 수단 이름, 분류 없음 → 경로는 시트 이름 하나). policy_fo 연결 대상 아님
    _item(40, "policy", POLICY, "결제 수단 목록", 2, [P("결제 수단 목록", "sheet_name")], "결제 수단 목록",
          title="신용카드", raw="BCDE"),
    _item(41, "policy", POLICY, "결제 수단 목록", 3, [P("결제 수단 목록", "sheet_name")], "결제 수단 목록",
          title="무통장 입금", raw="BCDE"),
    _item(42, "policy", POLICY, "결제 수단 목록", 4, [P("결제 수단 목록", "sheet_name")], "결제 수단 목록",
          title="휴대폰 결제", raw="BCDE"),

    # ---- 테스트케이스 (test) — B 케이스 ID, C 요구사항 ID, D 메뉴 E~G 1~3단계, H 테스트명, I 기대결과, J 수행자
    _item(43, "test", TEST, TC, 2, [P("회원", "cell", "D"), P("로그인", "cell", "E"), P("일반 로그인", "cell", "F"),
                                    P("아이디 입력", "cell", "G")],
          "회원 › 로그인 › 일반 로그인 › 아이디 입력", title="아이디 입력 확인", source_id="TC-001",
          ref_ids=["REQ-001"], raw="BCDEFGHIJKL"),
    _item(44, "test", TEST, TC, 3, [P("회원", "cell", "D"), P("로그인", "cell", "E"), P("일반 로그인", "cell", "F"),
                                    P("비밀번호 입력", "cell", "G")],
          "회원 › 로그인 › 일반 로그인 › 비밀번호 입력", title="비밀번호 가림 확인", source_id="TC-002",
          ref_ids=["REQ-001", "REQ-002"], raw="BCDEFGHIJK"),
    _item(45, "test", TEST, TC, 4, [P("주문", "cell", "D"), P("결제", "cell", "E"), P("결제 수단", "cell", "F"),
                                    P("카드 결제", "cell", "G")],
          "주문 › 결제 › 결제 수단 › 카드 결제", title="카드 결제 확인", source_id="TC-003",
          ref_ids=["REQ-999"], raw="BCDEFGHIJKLM"),
    _item(46, "test", TEST, TC, 5, [P("주문", "cell", "D"), P("배송", "cell", "E"), P("배송지 변경", "cell", "F")],
          "주문 › 배송 › 배송지 변경", title="배송지 변경 확인", source_id="TC-004", raw="BDEFHIJ"),
    _item(47, "test", TEST, TC, 6, [P("쿠폰", "cell", "D"), P("쿠폰함", "cell", "E"), P("쿠폰 목록", "cell", "F")],
          "쿠폰 › 쿠폰함 › 쿠폰 목록", status="unparsed", title="쿠폰 목록 확인", source_id="TC-005", raw="BCDEFHIJK"),
    # BO테스트케이스 — 머리글 FO와 같음, 요구사항 ID 빈칸, K~M 담당자별 결과(청크 본문 제외 열)
    _item(48, "test", TEST, TC_BO, 2, [P("회원관리", "cell", "D"), P("회원 목록", "cell", "E"), P("검색", "cell", "F")],
          "회원관리 › 회원 목록 › 검색", title="회원 검색 확인", source_id="TC-101", raw="BDEFHIJKL"),
    _item(49, "test", TEST, TC_BO, 3, [P("주문관리", "cell", "D"), P("주문 목록", "cell", "E"), P("상태 변경", "cell", "F")],
          "주문관리 › 주문 목록 › 상태 변경", title="상태 변경 확인", source_id="TC-102", raw="BDEFHIJKL"),
    _item(50, "test", TEST, TC_BO, 4, [P("주문관리", "cell", "D"), P("주문 목록", "cell", "E"), P("송장입력", "cell", "F")],
          "주문관리 › 주문 목록 › 송장입력", title="송장 입력 확인", source_id="TC-103", raw="BDEFHIJK"),

    # ---- 변형 (variation) — 기본: 헤더 1행, 분류1~3(B~D), 기능명 E, 설명 F
    # 빈칸채움 (fill_down 켬)
    _item(51, "variation", VAR, "빈칸채움", 2, [P("회원", "cell", "B"), P("로그인", "cell", "C")], "회원 › 로그인",
          title="로그인 화면", raw="BCEF"),
    _item(52, "variation", VAR, "빈칸채움", 3, [P("회원", "filled_down", "B"), P("로그인", "filled_down", "C"),
                                              P("아이디 찾기", "cell", "D")],
          "회원 › 로그인 › 아이디 찾기", status="ambiguous", title="아이디 찾기 화면", raw="DEF"),
    _item(53, "variation", VAR, "빈칸채움", 4, [P("회원", "filled_down", "B"), P("회원가입", "cell", "C")],
          "회원 › 회원가입", status="ambiguous", title="가입 화면", raw="CEF"),
    _item(54, "variation", VAR, "빈칸채움", 5, [P("회원", "filled_down", "B"), P("회원탈퇴", "cell", "C")],
          "회원 › 회원탈퇴", status="ambiguous", title="탈퇴 화면", raw="CEF"),
    _item(55, "variation", VAR, "빈칸채움", 6, [P("회원", "filled_down", "B"), P("회원탈퇴", "filled_down", "C")],
          "회원 › 회원탈퇴", status="ambiguous", title="탈퇴 완료 안내", raw="EF"),
    # 빈칸채움_끔 (fill_down 끔)
    _item(56, "variation", VAR, "빈칸채움_끔", 2, [P("회원", "cell", "B"), P("로그인", "cell", "C")], "회원 › 로그인",
          title="로그인 화면", raw="BCEF"),
    _item(57, "variation", VAR, "빈칸채움_끔", 3, [P(None, "empty", "B"), P(None, "empty", "C"), P("아이디 찾기", "cell", "D")],
          "(빈칸) › (빈칸) › 아이디 찾기", status="ambiguous", title="아이디 찾기 화면", raw="DEF"),
    _item(58, "variation", VAR, "빈칸채움_끔", 4, [P(None, "empty", "B"), P("회원가입", "cell", "C")],
          "(빈칸) › 회원가입", status="ambiguous", title="가입 화면", raw="CEF"),
    _item(59, "variation", VAR, "빈칸채움_끔", 5, [P(None, "empty", "B"), P("회원탈퇴", "cell", "C")],
          "(빈칸) › 회원탈퇴", status="ambiguous", title="탈퇴 화면", raw="CEF"),
    _item(60, "variation", VAR, "빈칸채움_끔", 6, [P(None, "empty", "B"), P(None, "empty", "C"), P(None, "empty", "D")],
          "(빈칸) › (빈칸) › (빈칸)", status="ambiguous", title="탈퇴 완료 안내", raw="EF"),
    # 한칸경로 (split_cell) — B 경로, C 기능명, D 설명
    _item(61, "variation", VAR, "한칸경로", 2, [P("회원", "split_cell", "B"), P("로그인", "split_cell", "B"),
                                              P("아이디 찾기", "split_cell", "B")],
          "회원 › 로그인 › 아이디 찾기", title="아이디 찾기 화면", raw="BCD"),
    # 번호 (numbering) — B 번호, C 이름(title), D 설명
    _item(62, "variation", VAR, "번호", 2, [P("회원", "numbering", "C")], "회원", title="회원", raw="BCD"),
    _item(63, "variation", VAR, "번호", 3, [P("회원", "numbering", "C"), P("로그인", "numbering", "C")],
          "회원 › 로그인", title="로그인", raw="BCD"),
    _item(64, "variation", VAR, "번호", 4, [P("회원", "numbering", "C"), P("로그인", "numbering", "C"),
                                          P("아이디 찾기", "numbering", "C")],
          "회원 › 로그인 › 아이디 찾기", title="아이디 찾기", raw="BCD"),
    _item(65, "variation", VAR, "번호", 5, [P("주문", "numbering", "C")], "주문", title="주문", raw="BCD"),
    _item(66, "variation", VAR, "번호", 6, [P("주문", "numbering", "C"), P(None, "empty"), P("주문 취소 사유", "numbering", "C")],
          "주문 › (빈칸) › 주문 취소 사유", status="unparsed", title="주문 취소 사유", raw="BCD"),
    # 이어지는행 (continuation) — B 기능 ID, C·D 분류, E 기능명, F 설명
    _item(67, "variation", VAR, "이어지는행", (2, 4), [P("주문", "cell", "C"), P("결제", "cell", "D")], "주문 › 결제",
          title="결제 화면\n결제 확인 버튼", source_id="V-001", raw="BCDEF"),
    # 오른쪽메모 — 본 표만 항목
    _item(68, "variation", VAR, "오른쪽메모", 2, [P("주문", "cell", "B"), P("장바구니", "cell", "C"), P("담기", "cell", "D")],
          "주문 › 장바구니 › 담기", title="담기 버튼", raw="BCDEF"),
    _item(69, "variation", VAR, "오른쪽메모", 3, [P("주문", "cell", "B"), P("장바구니", "cell", "C"), P("삭제", "cell", "D")],
          "주문 › 장바구니 › 삭제", title="삭제 버튼", raw="BCDEF"),
    # 숨김행수식 — 숨김 행(3 그냥, 4 그룹 접기)도 항목. G5 수식은 계산값 없음 → raw에 없음
    _item(70, "variation", VAR, "숨김행수식", 2, [P("회원", "cell", "B"), P("로그인", "cell", "C")], "회원 › 로그인",
          title="로그인 화면", raw="BCEF"),
    _item(71, "variation", VAR, "숨김행수식", 3, [P("회원", "cell", "B"), P("로그인", "cell", "C")], "회원 › 로그인",
          title="자동 로그인", raw="BCEF"),
    _item(72, "variation", VAR, "숨김행수식", 4, [P("회원", "cell", "B"), P("로그인", "cell", "C")], "회원 › 로그인",
          title="로그인 유지 안내", raw="BCEF"),
    _item(73, "variation", VAR, "숨김행수식", 5, [P("회원", "cell", "B"), P("회원가입", "cell", "C")], "회원 › 회원가입",
          title="가입 화면", raw="BCEF"),
    # 숨김건너뜀 (hidden_rows: skip) — 2·3행은 항목 없음
    _item(74, "variation", VAR, "숨김건너뜀", 4, [P("회원", "cell", "B"), P("로그인", "cell", "C")], "회원 › 로그인",
          title="로그인 화면", raw="BCEF"),
    _item(75, "variation", VAR, "숨김건너뜀", 5, [P("회원", "cell", "B"), P("회원가입", "cell", "C")], "회원 › 회원가입",
          title="가입 화면", raw="BCEF"),
    # 내용병합 — F2:F4 병합. 3·4행은 merged_fields로 설명을 받아 not_written 아님
    _item(76, "variation", VAR, "내용병합", 2, [P("주문", "cell", "B"), P("결제", "cell", "C"), P("카드 결제", "cell", "D")],
          "주문 › 결제 › 카드 결제", title="카드 결제 버튼", raw="BCDEF"),
    _item(77, "variation", VAR, "내용병합", 3, [P("주문", "cell", "B"), P("결제", "cell", "C"), P("무통장 입금", "cell", "D")],
          "주문 › 결제 › 무통장 입금", title="입금 계좌 안내", raw="BCDE", merged={"F": 2}),
    _item(78, "variation", VAR, "내용병합", 4, [P("주문", "cell", "B"), P("결제", "cell", "C"), P("간편 결제", "cell", "D")],
          "주문 › 결제 › 간편 결제", title="간편 결제 버튼", raw="BCDE", merged={"F": 2}),
    _item(79, "variation", VAR, "내용병합", 5, [P("주문", "cell", "B"), P("배송", "cell", "C")], "주문 › 배송",
          title="배송 조회 화면", raw="BCEF"),
    # 분류패턴 — header_pattern 하나로 2단·3단
    _item(80, "variation", VAR, "분류패턴_2단", 2, [P("주문", "cell", "B"), P("장바구니", "cell", "C")], "주문 › 장바구니",
          title="장바구니 화면", raw="BCDE"),
    _item(81, "variation", VAR, "분류패턴_2단", 3, [P("주문", "cell", "B"), P("결제", "cell", "C")], "주문 › 결제",
          title="결제 화면", raw="BCDE"),
    _item(82, "variation", VAR, "분류패턴_3단", 2, [P("주문", "cell", "B"), P("장바구니", "cell", "C"), P("담기", "cell", "D")],
          "주문 › 장바구니 › 담기", title="담기 버튼", raw="BCDEF"),
    _item(83, "variation", VAR, "분류패턴_3단", 3, [P("주문", "cell", "B"), P("결제", "cell", "C"), P("카드 결제", "cell", "D")],
          "주문 › 결제 › 카드 결제", title="카드 결제 버튼", raw="BCDEF"),
    # 각주 — B 번호(역할 없음), C~E 분류, F 기능명, G 설명. 5행 각주는 항목 + unparsed
    _item(84, "variation", VAR, "각주", 2, [P("주문", "cell", "C"), P("결제", "cell", "D")], "주문 › 결제",
          title="결제 화면", raw="BCDFG"),
    _item(85, "variation", VAR, "각주", 3, [P("주문", "cell", "C"), P("배송", "cell", "D")], "주문 › 배송",
          title="배송 조회 화면", raw="BCDFG"),
    _item(86, "variation", VAR, "각주", 5, [P(None, "empty", "C"), P(None, "empty", "D"), P(None, "empty", "E")],
          "(빈칸) › (빈칸) › (빈칸)", status="unparsed", raw="B"),
    # 부푼범위 (D1) — G 개수(숫자)
    _item(87, "variation", VAR, "부푼범위", 2, [P("주문", "cell", "B"), P("장바구니", "cell", "C")], "주문 › 장바구니",
          title="장바구니 화면", raw="BCEFG"),
    _item(88, "variation", VAR, "부푼범위", 3, [P("주문", "cell", "B"), P("결제", "cell", "C")], "주문 › 결제",
          title="결제 화면", raw="BCEFG"),
    _item(89, "variation", VAR, "부푼범위", 4, [P("주문", "cell", "B"), P("배송", "cell", "C")], "주문 › 배송",
          title="배송 조회 화면", raw="BCEFG"),
    # 표안빈열 (D3) — B·C 분류, D 기능명, E 메모(거의 빔), F 설명
    _item(90, "variation", VAR, "표안빈열", 2, [P("주문", "cell", "B"), P("장바구니", "cell", "C")], "주문 › 장바구니",
          title="장바구니 화면", raw="BCDF"),
    _item(91, "variation", VAR, "표안빈열", 3, [P("주문", "cell", "B"), P("결제", "cell", "C")], "주문 › 결제",
          title="결제 화면", raw="BCDEF"),
    _item(92, "variation", VAR, "표안빈열", 4, [P("주문", "cell", "B"), P("배송", "cell", "C")], "주문 › 배송",
          title="배송 조회 화면", raw="BCDF"),
    # 왼쪽덩어리 (D6) — 헤더 D~G, B열 덩어리는 항목 아님
    _item(93, "variation", VAR, "왼쪽덩어리", 2, [P("주문", "cell", "D"), P("결제", "cell", "E")], "주문 › 결제",
          title="결제 화면", raw="DEFG"),
    _item(94, "variation", VAR, "왼쪽덩어리", 3, [P("주문", "cell", "D"), P("배송", "cell", "E")], "주문 › 배송",
          title="배송 조회 화면", raw="DEFG"),
    # 표여러개 — 표마다 제목 단계(table_title) + B 분류1, A 번호·C 기능명·D 설명. 표3(11행)은 분류 열이 없어 건너뜀
    _item(95, "variation", VAR, "표여러개", 3, [P("주문 정책", "table_title"), P("주문", "cell", "B")], "주문 정책 › 주문",
          title="주문 취소", raw="ABCD"),
    _item(96, "variation", VAR, "표여러개", 4, [P("주문 정책", "table_title"), P("주문", "filled_down", "B")],
          "주문 정책 › 주문", status="ambiguous", title="주문 변경", raw="ACD"),
    _item(97, "variation", VAR, "표여러개", 8, [P("배송 정책", "table_title"), P("배송", "cell", "B")], "배송 정책 › 배송",
          title="배송 조회", raw="ABCD"),
    _item(98, "variation", VAR, "표여러개", 17, [P("가입 정책", "table_title"), P("회원", "cell", "B")], "가입 정책 › 회원",
          title="회원가입", raw="ABCD"),
    _item(99, "variation", VAR, "표여러개", 21, [P("탈퇴 정책", "table_title"), P("회원", "cell", "B")], "탈퇴 정책 › 회원",
          title="회원탈퇴", raw="ABCD"),
]

FINAL_LINKS = [
    _link(1, "fo_overview_detail", "path_exact", "structural", a=5, b=25),
    _link(2, "fo_overview_detail", "path_exact", "structural", a=10, b=26),
    _link(3, "fo_test", "path_exact", "structural", a=5, b=43),
    _link(4, "fo_test", "path_exact", "structural", a=6, b=44),
    _link(5, "fo_test", "path_exact", "structural", a=10, b=45),
    _link(6, "fo_test", "path_normalized", "structural", a=12, b=46),   # 배송지변경 ↔ 배송지 변경
    _link(7, "bo_test", "path_exact", "structural", a=27, b=48),
    _link(8, "bo_test", "path_exact", "structural", a=30, b=49),
    _link(9, "bo_test", "path_normalized", "structural", a=31, b=50),   # 송장 입력 ↔ 송장입력
    _link(10, "policy_fo", "path_normalized", "structural", item=33, group=("fo", "주문 › 결제")),
    _link(11, "policy_fo", "path_normalized", "structural", item=34, group=("fo", "주문 › 결제")),
    _link(12, "policy_fo", "path_normalized", "structural", item=35, group=("fo", "회원 › 로그인")),
    _link(13, "policy_fo", "path_normalized", "structural", item=37, group=("fo", "주문 › 배송")),  # 서술형 시트
    _link(14, "policy_fo", "path_normalized", "structural", item=38, group=("fo", "주문 › 배송")),
    _link(15, "policy_fo", "path_normalized", "structural", item=39, group=("fo", "주문 › 배송")),
    _link(16, "test_req", "id_ref", "explicit", a=1, b=43),
    _link(17, "test_req", "id_ref", "explicit", a=1, b=44),
    _link(18, "test_req", "id_ref", "explicit", a=2, b=44),
    _link(19, "req_fo_glossary", "glossary", "structural", item=1, group=("fo", "회원 › 로그인")),  # 고객=회원
]

FINAL_WARNINGS = [
    _warn(1, "duplicate_id", REQ, "요구사항", [("요구사항", 4, 4, "D"), ("요구사항", 5, 5, "D")], items=[3, 4]),
    _warn(2, "version_mismatch", FO, "표지", [("표지", 5, 5, "C")]),
    _warn(3, "merge_unrestored", FO, "회원", [("회원", 10, 10, "C")], items=[9]),
    _warn(4, "content_mismatch", FO, "주문", [("주문", 6, 6, "F"), ("요약", 7, 7, "G")], items=[10, 26]),
    _warn(5, "link_unconfirmed", POLICY, "쿠폰 - 발급", [("쿠폰 - 발급", 2, 2, "BC")], items=[36]),
    _warn(6, "ref_unresolved", TEST, TC, [(TC, 4, 4, "C")], items=[45]),
    _warn(7, "unparsed", TEST, TC, [(TC, 6, 6, "C")], items=[47]),
    _warn(8, "merge_unrestored", VAR, "빈칸채움_끔", [("빈칸채움_끔", 3, 3, "BC")], items=[57]),
    _warn(9, "merge_unrestored", VAR, "빈칸채움_끔", [("빈칸채움_끔", 4, 4, "B")], items=[58]),
    _warn(10, "merge_unrestored", VAR, "빈칸채움_끔", [("빈칸채움_끔", 5, 5, "B")], items=[59]),
    _warn(11, "merge_unrestored", VAR, "빈칸채움_끔", [("빈칸채움_끔", 6, 6, "BCD")], items=[60]),
    _warn(12, "unparsed", VAR, "번호", [("번호", 6, 6, "B")], items=[66]),            # 조상 2.3 없음
    _warn(13, "unsupported_layout", VAR, "오른쪽메모", [("오른쪽메모", 2, 3, "H")]),     # 덩어리만
    _warn(14, "header_not_found", VAR, "역할겹침", [("역할겹침", 1, 1, "EF")]),        # 겹친 열
    _warn(15, "sheet_skipped", VAR, "숨김"),                                          # 숨김 시트
    _warn(16, "unsupported_layout", VAR, "표두개", [("표두개", 7, 8, "BCDEF")]),         # 시트 건너뜀
    _warn(17, "unsupported", VAR, "들여쓰기"),                                         # indent 미구현
    _warn(18, "hidden_content", VAR, "숨김행수식", [("숨김행수식", 3, 3, None), ("숨김행수식", 4, 4, None)],
          items=[71, 72]),                                                            # 3 그냥 숨김, 4 그룹 접기
    _warn(19, "formula_no_value", VAR, "숨김행수식", [("숨김행수식", 5, 5, "G")], items=[73]),
    _warn(20, "hidden_content", VAR, "숨김건너뜀", [("숨김건너뜀", 2, 3, None)]),         # skip으로 건너뜀
    _warn(21, "header_not_found", VAR, "분류열부족", [("분류열부족", 1, 1, None)]),       # 못 찾은 선택자: 분류3
    _warn(22, "unparsed", VAR, "각주", [("각주", 5, 5, "B")], items=[86]),
    _warn(23, "unsupported_layout", VAR, "대각선표", [("대각선표", 7, 8, "HI")]),        # 시트 건너뜀
    _warn(24, "unsupported_layout", VAR, "왼쪽덩어리", [("왼쪽덩어리", 2, 3, "B")]),       # 덩어리만
    _warn(25, "sheet_skipped", VAR, "차트"),                                          # 사유 chart_sheet
    _warn(26, "header_not_found", VAR, "빈시트", [("빈시트", 1, 1, None)]),
    _warn(27, "header_not_found", VAR, "표여러개", [("표여러개", 12, 12, None)]),        # 분류 열 없는 표3만 건너뜀
    _warn(28, "unsupported", XLS, None),                                              # .xls
    _warn(29, "unsupported", FAKE, None),                                             # U6
]


FINAL = {
    "items": FINAL_ITEMS,
    "links": FINAL_LINKS,
    "warnings": FINAL_WARNINGS,
    "summary": {
        "items": 99, "links": 19, "warnings": 29,
        "warning_kinds": {"duplicate_id": 1, "version_mismatch": 1, "merge_unrestored": 5, "content_mismatch": 1,
                          "link_unconfirmed": 1, "ref_unresolved": 1, "unparsed": 3, "unsupported_layout": 4,
                          "header_not_found": 4, "sheet_skipped": 2, "unsupported": 3, "hidden_content": 2,
                          "formula_no_value": 1},
    },
}


# ======================================================================
# BEFORE_1008 — 1부 항목만 끝난 상태. 번호 없이 위치로 비교
# ======================================================================

def _b(file, sheet, rows, path_text, *, status="ok", title=None, source_id=None, ref_ids=(), merged=None):
    rows = (rows, rows) if isinstance(rows, int) else rows
    return {"file": file, "sheet": sheet, "rows": rows, "path_text": path_text, "status": status,
            "title": title, "source_id": source_id, "ref_ids": list(ref_ids), "merged": merged or {}}


def _bw(kind, file, sheet, locations=(), message_contains=None):
    """message_contains: message에 들어 있어야 할 글자"""
    w = {"kind": kind, "file": file, "sheet": sheet,
         "locations": [(s, a, b, list(c) if c else None) for s, a, b, c in locations]}
    if message_contains:
        w["message_contains"] = message_contains
    return w


BEFORE_ITEMS = [
    # req — 2026-10-13 13b 구현: duplicate_id 경고는 BEFORE_WARNINGS에
    _b(REQ, "요구사항", 2, "고객 › 로그인", title="로그인 기능", source_id="REQ-001"),
    _b(REQ, "요구사항", 3, "고객 › 문의", title="1:1 문의 기능", source_id="REQ-002"),
    _b(REQ, "요구사항", 4, "주문 › 결제", title="결제 기능", source_id="REQ-003"),
    _b(REQ, "요구사항", 5, "주문 › 배송", title="배송지 변경 기능", source_id="REQ-003"),
    # fo
    _b(FO, "회원", 6, "회원 › 로그인 › 일반 로그인 › 아이디 입력", title="아이디 입력란"),
    _b(FO, "회원", 7, "회원 › 로그인 › 일반 로그인 › 비밀번호 입력", title="비밀번호 입력란"),
    _b(FO, "회원", 8, "회원 › 로그인 › 간편 로그인 › 소셜 계정 선택", status="not_written", title="소셜 로그인 버튼"),
    _b(FO, "회원", 9, "회원 › 회원가입 › 약관 동의", title="약관 동의 화면"),
    _b(FO, "회원", 10, "회원 › 회원탈퇴 › (빈칸) › 탈퇴 사유", status="ambiguous", title="탈퇴 사유 선택"),
    _b(FO, "주문", 6, "주문 › 결제 › 결제 수단 › 카드 결제", title="카드 결제 버튼"),
    _b(FO, "주문", 7, "주문 › 결제 › 결제 수단 › 무통장 입금", title="입금 계좌 안내"),
    _b(FO, "주문", 8, "주문 › 배송 › 배송지변경", title="배송지 변경 화면"),
    _b(FO, "고객센터", 6, "고객센터 › 문의 › 문의 작성 › 문의 종류 › 주문 문의", title="주문 문의 선택"),
    _b(FO, "고객센터", 7, "고객센터 › 문의 › 문의 작성 › 문의 종류 › 배송 문의", title="배송 문의 선택"),
    _b(FO, "고객센터", 8, "고객센터 › 문의 › 문의 작성 › 문의 종류 › 기타 문의", title="기타 문의 선택"),
    _b(FO, "고객센터", 9, "고객센터 › 문의 › 문의 작성 › 본문 입력", title="본문 입력란"),
    _b(FO, "고객센터", 10, "고객센터 › 문의 › 문의 작성 › 사진 첨부", title="사진 첨부 버튼"),
    _b(FO, "고객센터", 11, "고객센터 › 문의 › 문의 내역 › 목록", title="문의 목록 화면"),
    _b(FO, "고객센터", 12, "고객센터 › 문의 › 문의 내역 › 상세 › 답변 보기", title="답변 보기 화면"),
    _b(FO, "고객센터", 13, "고객센터 › 문의 › 문의 내역 › 상세 › 추가 문의", title="추가 문의 버튼"),
    _b(FO, "고객센터", 14, "고객센터 › 문의 › 문의 내역 › 삭제", title="문의 삭제 버튼"),
    _b(FO, "고객센터", 15, "고객센터 › 문의 › 답변 알림 › 앱 알림", title="앱 알림 설정"),
    _b(FO, "고객센터", 16, "고객센터 › 문의 › 답변 알림 › 문자 알림", title="문자 알림 설정"),
    _b(FO, "고객센터", 17, "고객센터 › 문의 › 답변 알림 › 메일 알림", title="메일 알림 설정"),
    _b(FO, "요약", 6, "회원 › 로그인 › 일반 로그인 › 아이디 입력", title="아이디 입력란"),
    _b(FO, "요약", 7, "주문 › 결제 › 결제 수단 › 카드 결제", title="카드 결제 버튼"),
    # bo
    _b(BO, "회원관리", 6, "회원관리 › 회원 목록 › 검색", title="회원 검색"),
    _b(BO, "회원관리", 7, "회원관리 › 회원 목록 › 엑셀 내려받기", title="내려받기 버튼"),
    _b(BO, "회원관리", 8, "회원관리 › 회원 상세", title="회원 상세 화면"),
    _b(BO, "주문관리", 6, "주문관리 › 주문 목록 › 상태 변경", title="상태 변경 버튼"),
    _b(BO, "주문관리", 7, "주문관리 › 주문 목록 › 송장 입력", title="송장 입력란"),
    _b(BO, "주문관리", 8, "주문관리 › 환불 처리", title="환불 처리 화면"),
    # policy
    _b(POLICY, "주문 - 결제", 2, "주문 › 결제", title="결제 한도"),
    _b(POLICY, "주문 - 결제", 3, "주문 › 결제", title="결제 취소"),
    _b(POLICY, "회원 - 로그인", 2, "회원 › 로그인", title="로그인 실패 제한"),
    _b(POLICY, "쿠폰 - 발급", 2, "쿠폰 › 발급", title="쿠폰 발급 조건"),
    _b(POLICY, "주문 - 배송", 2, "주문 › 배송 › 배송비 › 기본"),
    _b(POLICY, "주문 - 배송", 3, "주문 › 배송 › 배송비 › 도서 산간"),
    _b(POLICY, "주문 - 배송", 4, "주문 › 배송 › 배송 기간"),
    _b(POLICY, "결제 수단 목록", 2, "결제 수단 목록", title="신용카드"),
    _b(POLICY, "결제 수단 목록", 3, "결제 수단 목록", title="무통장 입금"),
    _b(POLICY, "결제 수단 목록", 4, "결제 수단 목록", title="휴대폰 결제"),
    # test — 2026-10-13 13b 구현: ref_ids는 FINAL과 같음, 참조 칸에 ID가 없는 TC-005는 unparsed
    _b(TEST, TC, 2, "회원 › 로그인 › 일반 로그인 › 아이디 입력", title="아이디 입력 확인", source_id="TC-001",
       ref_ids=["REQ-001"]),
    _b(TEST, TC, 3, "회원 › 로그인 › 일반 로그인 › 비밀번호 입력", title="비밀번호 가림 확인", source_id="TC-002",
       ref_ids=["REQ-001", "REQ-002"]),
    _b(TEST, TC, 4, "주문 › 결제 › 결제 수단 › 카드 결제", title="카드 결제 확인", source_id="TC-003",
       ref_ids=["REQ-999"]),
    _b(TEST, TC, 5, "주문 › 배송 › 배송지 변경", title="배송지 변경 확인", source_id="TC-004"),
    _b(TEST, TC, 6, "쿠폰 › 쿠폰함 › 쿠폰 목록", status="unparsed", title="쿠폰 목록 확인", source_id="TC-005"),
    _b(TEST, TC_BO, 2, "회원관리 › 회원 목록 › 검색", title="회원 검색 확인", source_id="TC-101"),
    _b(TEST, TC_BO, 3, "주문관리 › 주문 목록 › 상태 변경", title="상태 변경 확인", source_id="TC-102"),
    _b(TEST, TC_BO, 4, "주문관리 › 주문 목록 › 송장입력", title="송장 입력 확인", source_id="TC-103"),
    # variation — 범위 안 시트만
    _b(VAR, "빈칸채움", 2, "회원 › 로그인", title="로그인 화면"),
    _b(VAR, "빈칸채움", 3, "회원 › 로그인 › 아이디 찾기", status="ambiguous", title="아이디 찾기 화면"),
    _b(VAR, "빈칸채움", 4, "회원 › 회원가입", status="ambiguous", title="가입 화면"),
    _b(VAR, "빈칸채움", 5, "회원 › 회원탈퇴", status="ambiguous", title="탈퇴 화면"),
    _b(VAR, "빈칸채움", 6, "회원 › 회원탈퇴", status="ambiguous", title="탈퇴 완료 안내"),
    _b(VAR, "빈칸채움_끔", 2, "회원 › 로그인", title="로그인 화면"),
    _b(VAR, "빈칸채움_끔", 3, "(빈칸) › (빈칸) › 아이디 찾기", status="ambiguous", title="아이디 찾기 화면"),
    _b(VAR, "빈칸채움_끔", 4, "(빈칸) › 회원가입", status="ambiguous", title="가입 화면"),
    _b(VAR, "빈칸채움_끔", 5, "(빈칸) › 회원탈퇴", status="ambiguous", title="탈퇴 화면"),
    _b(VAR, "빈칸채움_끔", 6, "(빈칸) › (빈칸) › (빈칸)", status="ambiguous", title="탈퇴 완료 안내"),
    _b(VAR, "숨김건너뜀", 4, "회원 › 로그인", title="로그인 화면"),
    _b(VAR, "숨김건너뜀", 5, "회원 › 회원가입", title="가입 화면"),
    _b(VAR, "내용병합", 2, "주문 › 결제 › 카드 결제", title="카드 결제 버튼"),
    _b(VAR, "내용병합", 3, "주문 › 결제 › 무통장 입금", title="입금 계좌 안내", merged={"F": 2}),
    _b(VAR, "내용병합", 4, "주문 › 결제 › 간편 결제", title="간편 결제 버튼", merged={"F": 2}),
    _b(VAR, "내용병합", 5, "주문 › 배송", title="배송 조회 화면"),
    _b(VAR, "분류패턴_2단", 2, "주문 › 장바구니", title="장바구니 화면"),
    _b(VAR, "분류패턴_2단", 3, "주문 › 결제", title="결제 화면"),
    _b(VAR, "분류패턴_3단", 2, "주문 › 장바구니 › 담기", title="담기 버튼"),
    _b(VAR, "분류패턴_3단", 3, "주문 › 결제 › 카드 결제", title="카드 결제 버튼"),
    _b(VAR, "부푼범위", 2, "주문 › 장바구니", title="장바구니 화면"),
    _b(VAR, "부푼범위", 3, "주문 › 결제", title="결제 화면"),
    _b(VAR, "부푼범위", 4, "주문 › 배송", title="배송 조회 화면"),
    _b(VAR, "표여러개", 3, "주문 정책 › 주문", title="주문 취소"),
    _b(VAR, "표여러개", 4, "주문 정책 › 주문", status="ambiguous", title="주문 변경"),
    _b(VAR, "표여러개", 8, "배송 정책 › 배송", title="배송 조회"),
    _b(VAR, "표여러개", 17, "가입 정책 › 회원", title="회원가입"),
    _b(VAR, "표여러개", 21, "탈퇴 정책 › 회원", title="회원탈퇴"),
]

BEFORE_LINKS = [  # path 규칙 + sheet_to_path. 항목은 (파일, 시트, 행), 묶음은 (문서 종류, 경로 글자)
    {"rule_id": "fo_overview_detail", "method": "path_exact", "a": (FO, "회원", 6), "b": (FO, "요약", 6)},
    {"rule_id": "fo_overview_detail", "method": "path_exact", "a": (FO, "주문", 6), "b": (FO, "요약", 7)},
    {"rule_id": "fo_test", "method": "path_exact", "a": (FO, "회원", 6), "b": (TEST, TC, 2)},
    {"rule_id": "fo_test", "method": "path_exact", "a": (FO, "회원", 7), "b": (TEST, TC, 3)},
    {"rule_id": "fo_test", "method": "path_exact", "a": (FO, "주문", 6), "b": (TEST, TC, 4)},
    {"rule_id": "fo_test", "method": "path_normalized", "a": (FO, "주문", 8), "b": (TEST, TC, 5)},
    {"rule_id": "bo_test", "method": "path_exact", "a": (BO, "회원관리", 6), "b": (TEST, TC_BO, 2)},
    {"rule_id": "bo_test", "method": "path_exact", "a": (BO, "주문관리", 6), "b": (TEST, TC_BO, 3)},
    {"rule_id": "bo_test", "method": "path_normalized", "a": (BO, "주문관리", 7), "b": (TEST, TC_BO, 4)},
    # 2026-10-10: 15(sheet_to_path)를 18 앞으로 옮겨 policy_fo 묶음 연결도 1부에 들어옴(FINAL과 같음)
    {"rule_id": "policy_fo", "method": "path_normalized", "item": (POLICY, "주문 - 결제", 2), "group": ("fo", "주문 › 결제")},
    {"rule_id": "policy_fo", "method": "path_normalized", "item": (POLICY, "주문 - 결제", 3), "group": ("fo", "주문 › 결제")},
    {"rule_id": "policy_fo", "method": "path_normalized", "item": (POLICY, "회원 - 로그인", 2), "group": ("fo", "회원 › 로그인")},
    {"rule_id": "policy_fo", "method": "path_normalized", "item": (POLICY, "주문 - 배송", 2), "group": ("fo", "주문 › 배송")},
    {"rule_id": "policy_fo", "method": "path_normalized", "item": (POLICY, "주문 - 배송", 3), "group": ("fo", "주문 › 배송")},
    {"rule_id": "policy_fo", "method": "path_normalized", "item": (POLICY, "주문 - 배송", 4), "group": ("fo", "주문 › 배송")},
    # 2026-10-10: 16a(glossary)를 18 다음·21 전으로 옮겨 1부에 들어옴(FINAL과 같음)
    # 2026-10-13: 13b·16b(id_ref) 구현(FINAL과 같음)
    {"rule_id": "test_req", "method": "id_ref", "a": (REQ, "요구사항", 2), "b": (TEST, TC, 2)},
    {"rule_id": "test_req", "method": "id_ref", "a": (REQ, "요구사항", 2), "b": (TEST, TC, 3)},
    {"rule_id": "test_req", "method": "id_ref", "a": (REQ, "요구사항", 3), "b": (TEST, TC, 3)},
    {"rule_id": "req_fo_glossary", "method": "glossary", "item": (REQ, "요구사항", 2), "group": ("fo", "회원 › 로그인")},
]

BEFORE_WARNINGS = [
    _bw("duplicate_id", REQ, "요구사항", [("요구사항", 4, 4, "D"), ("요구사항", 5, 5, "D")]),
    _bw("version_mismatch", FO, "표지", [("표지", 5, 5, "C")]),
    _bw("merge_unrestored", FO, "회원", [("회원", 10, 10, "C")]),
    _bw("content_mismatch", FO, "주문", [("주문", 6, 6, "F"), ("요약", 7, 7, "G")]),
    _bw("unsupported_layout", FO, "고객센터", [("고객센터", 1, 2, None)]),   # 2026-10-14: 머리글 위 칸(알려진 한계)
    _bw("link_unconfirmed", POLICY, "쿠폰 - 발급", [("쿠폰 - 발급", 2, 2, "BC")]),
    _bw("ref_unresolved", TEST, TC, [(TC, 4, 4, "C")]),           # REQ-999
    _bw("unparsed", TEST, TC, [(TC, 6, 6, "C")]),                 # 참조 칸에 ID 없음
    _bw("merge_unrestored", VAR, "빈칸채움_끔", [("빈칸채움_끔", 3, 3, "BC")]),
    _bw("merge_unrestored", VAR, "빈칸채움_끔", [("빈칸채움_끔", 4, 4, "B")]),
    _bw("merge_unrestored", VAR, "빈칸채움_끔", [("빈칸채움_끔", 5, 5, "B")]),
    _bw("merge_unrestored", VAR, "빈칸채움_끔", [("빈칸채움_끔", 6, 6, "BCD")]),
    _bw("unsupported", VAR, "한칸경로"),     # split_cell은 항목 12
    _bw("unsupported", VAR, "번호"),         # numbering은 항목 12
    _bw("unsupported", VAR, "이어지는행"),   # continuation은 항목 10b
    _bw("header_not_found", VAR, "역할겹침", [("역할겹침", 1, 1, "EF")]),
    _bw("sheet_skipped", VAR, "숨김"),
    _bw("unsupported", VAR, "들여쓰기"),
    _bw("hidden_content", VAR, "숨김건너뜀", [("숨김건너뜀", 2, 3, None)]),
    _bw("header_not_found", VAR, "분류열부족", [("분류열부족", 1, 1, None)]),
    _bw("header_not_found", VAR, "표여러개", [("표여러개", 12, 12, None)]),   # 표3만 건너뜀
    _bw("unsupported", XLS, None),
    _bw("unsupported", FAKE, None),
]

BEFORE_1008 = {
    "items": BEFORE_ITEMS,
    "links": BEFORE_LINKS,
    "warnings": BEFORE_WARNINGS,
    # 9b(표 배치 경고)·숨김행수식 시트: 10-08 전 비교 제외
    "excluded_sheets": [(VAR, s) for s in ("오른쪽메모", "표두개", "숨김행수식", "각주", "표안빈열",
                                           "대각선표", "왼쪽덩어리", "차트", "빈시트")],
    # 10b·12 방식 시트: 10-08 전에는 시트 건너뜀 + unsupported (항목 없음)
    "unsupported_sheets": [(VAR, s) for s in ("한칸경로", "번호", "이어지는행", "들여쓰기")],
    # 13b(ID 처리) 경고: 2026-10-13 구현으로 비교에 넣음(제외 없음)
    "excluded_warning_kinds": [],
    "summary": {
        "items": 78, "links": 19, "warnings": 23,
        "warning_kinds": {"unsupported": 6, "version_mismatch": 1, "merge_unrestored": 5, "content_mismatch": 1,
                          "header_not_found": 3, "sheet_skipped": 1, "hidden_content": 1, "link_unconfirmed": 1,
                          "duplicate_id": 1, "ref_unresolved": 1, "unparsed": 1, "unsupported_layout": 1},
    },
}


# ======================================================================
# docs/DESIGN.md 8.1 표의 상황(행 순서 그대로) → 확인할 (파일, 시트)
# ======================================================================

SCENARIOS = [
    ("fo 기본 구조·version_mismatch", FO, "회원"),
    ("fo 고객센터(흔한 양식 구조)", FO, "고객센터"),
    ("회원 10행 중간 빈 단계", FO, "회원"),
    ("설명 빈 항목 not_written", FO, "회원"),
    ("회원 9행 끝 빈 단계", FO, "회원"),
    ("요약 시트 연결·content_mismatch", FO, "요약"),
    ("※ 참고 끝 표시", FO, "주문"),
    ("bo 메뉴 시트(1단계=메뉴 이름)", BO, "회원관리"),
    ("test 같은 경로 4건", TEST, TC),
    ("test BO 시트·bo_test", TEST, TC_BO),
    ("담당자별 결과 열(exclude_from_text)", TEST, TC_BO),
    ("요구사항 ID 칸 4종", TEST, TC),
    ("참조 칸 패턴 불일치", TEST, TC),
    ("policy 시트 이름 연결", POLICY, "쿠폰 - 발급"),
    ("policy 서술형 시트", POLICY, "주문 - 배송"),
    ("policy 목록형 시트(연결 제외)", POLICY, "결제 수단 목록"),
    ("req 자기 ID·glossary", REQ, "요구사항"),
    ("req duplicate_id", REQ, "요구사항"),
    ("빈칸채움 켬/끔", VAR, "빈칸채움_끔"),
    ("한칸경로", VAR, "한칸경로"),
    ("번호", VAR, "번호"),
    ("이어지는행", VAR, "이어지는행"),
    ("오른쪽메모", VAR, "오른쪽메모"),
    ("역할겹침", VAR, "역할겹침"),
    ("숨김 시트", VAR, "숨김"),
    ("표두개", VAR, "표두개"),
    ("들여쓰기", VAR, "들여쓰기"),
    ("숨김행수식(그룹 접기 포함)", VAR, "숨김행수식"),
    ("숨김건너뜀", VAR, "숨김건너뜀"),
    ("내용병합", VAR, "내용병합"),
    ("분류패턴", VAR, "분류패턴_2단"),
    ("분류열부족", VAR, "분류열부족"),
    ("각주", VAR, "각주"),
    ("부푼범위 D1", VAR, "부푼범위"),
    ("표안빈열 D3", VAR, "표안빈열"),
    ("대각선표 D5", VAR, "대각선표"),
    ("왼쪽덩어리 D6", VAR, "왼쪽덩어리"),
    ("차트 시트 D8", VAR, "차트"),
    ("빈시트 U5", VAR, "빈시트"),
    ("표여러개 9b", VAR, "표여러개"),
    (".xls 미지원", XLS, None),
    ("가짜 확장자 U6", FAKE, None),
]
