from messenger_parser import parse_kakao_export


def test_parse_bracket_export_with_date_and_multiline():
    text = """--------------- 2026년 6월 24일 수요일 ---------------
[선배] [오전 10:30] 발표자료는 목요일 퇴근 전까지 제출해주세요.
추가 설명입니다.
[나] [오전 10:31] 네, 확인했습니다.
"""
    messages = parse_kakao_export(text)

    assert len(messages) == 2
    assert messages[0].sender == "선배"
    assert "추가 설명입니다." in messages[0].message
    assert messages[0].timestamp.hour == 10
    assert messages[1].sender == "나"


def test_parse_simple_bracket_lines_without_time():
    text = "[선배] 이번 주 금요일 오전 10시에 팀별 발표 리허설 있어요."
    messages = parse_kakao_export(text)

    assert len(messages) == 1
    assert messages[0].sender == "선배"
    assert "리허설" in messages[0].message
