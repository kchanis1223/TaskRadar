from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree as ET


NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
ET.register_namespace("w", NS["w"])


INTRO = [
    "01  에이전트 소개",
    "",
    "TaskRadar는 카카오톡 대화 내보내기 .txt 파일 또는 직접 입력한 대화 내용을 분석하여, 신입구성원이 놓치기 쉬운 업무 요청을 To-Do와 일정으로 정리해 주는 AI Agent입니다. 대화 속 지시사항, 마감, 회의 일정, 제출물, 확인이 필요한 애매한 표현을 추출하고, 선배에게 보낼 자연스러운 확인 문구와 체크리스트를 함께 제공합니다.",
    "",
    "특히 선배 답변을 추가로 받은 경우, 사용자가 반영할 To-Do를 선택하면 전체 대화를 다시 분석하지 않고 선택된 항목에 대한 업데이트 패치만 생성해 기존 결과에 병합합니다. 이를 통해 기존 To-Do 목록은 유지하면서 변경된 기한, 양식, 제출 경로, 추가 확인 사항만 빠르게 반영할 수 있습니다.",
]

ASIS = [
    "AS-IS",
    "",
    "신입구성원은 과제, 회의, 발표 준비, 제출물 안내를 카카오톡과 같은 메신저 대화 속에서 받는 경우가 많습니다. 하지만 실제 업무 요청은 자연스러운 대화 안에 흩어져 있어, 기한과 제출 방식, 준비 범위, 후속 확인 사항을 사용자가 직접 다시 정리해야 합니다.",
    "",
    "특히 “퇴근 전까지”, “다음 주 초”, “추후 공유”, “한번 확인해 주세요”처럼 애매한 표현이 포함되면 무엇을 일정으로 등록해야 하는지, 어떤 부분을 선배에게 다시 물어봐야 하는지 판단하기 어렵습니다.",
]

TOBE = [
    "TO-BE",
    "",
    "TaskRadar를 사용하면 카카오톡 대화 파일을 업로드하거나 대화를 붙여넣는 것만으로 To-Do, 일정, 확인 필요 항목, 추천 질문 문구를 한 화면에서 확인할 수 있습니다. 사용자는 AI가 정리한 업무 카드에서 기한, 우선순위, 확인해 볼 사항을 바로 확인하고, 필요한 경우 선배 답변을 선택한 To-Do에 다시 반영할 수 있습니다.",
    "",
    "기대 효과: 메신저 대화 1건 정리 시간을 약 10~15분에서 1~3분 수준으로 단축, 업무 요청/일정/확인 필요 사항의 누락 가능성 감소, 선배에게 물어볼 문구 자동 생성으로 커뮤니케이션 부담 완화",
]


def make_paragraph(text: str = "") -> ET.Element:
    paragraph = ET.Element(W + "p")
    run = ET.SubElement(paragraph, W + "r")
    text_node = ET.SubElement(run, W + "t")
    text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text_node.text = text
    return paragraph


def set_cell_text(cell: ET.Element, lines: list[str] | str) -> None:
    tc_pr = cell.find("w:tcPr", NS)
    preserved_tc_pr = deepcopy(tc_pr) if tc_pr is not None else None
    for child in list(cell):
        cell.remove(child)
    if preserved_tc_pr is not None:
        cell.append(preserved_tc_pr)
    if isinstance(lines, str):
        lines = [lines]
    for line in lines:
        cell.append(make_paragraph(line))


def main() -> None:
    project_dir = Path(__file__).resolve().parents[1]
    src = next(path for path in project_dir.glob("*.docx") if "제출양식" in path.name and not path.name.startswith("~$"))
    dst = project_dir / "TaskRadar_AI_Agent_Submission_Draft.docx"

    with ZipFile(src, "r") as zin:
        root = ET.fromstring(zin.read("word/document.xml"))
        tables = root.findall(".//w:tbl", NS)

        info_rows = tables[0].findall(".//w:tr", NS)
        set_cell_text(info_rows[0].findall("w:tc", NS)[1], "TaskRadar - 신입 업무 레이더 Agent")
        set_cell_text(info_rows[1].findall("w:tc", NS)[1], "")
        set_cell_text(
            info_rows[2].findall("w:tc", NS)[1],
            "Python, Streamlit, opencode OAuth, LLM 기반 JSON 분석, JSON Patch, KakaoTalk txt parser",
        )

        intro_rows = tables[1].findall(".//w:tr", NS)
        set_cell_text(intro_rows[1].findall("w:tc", NS)[0], INTRO[2:])

        effect_cells = tables[2].findall(".//w:tr", NS)[1].findall("w:tc", NS)
        set_cell_text(effect_cells[0], ASIS)
        set_cell_text(effect_cells[1], TOBE)

        screenshot_cells = tables[3].findall(".//w:tr", NS)[1].findall("w:tc", NS)
        set_cell_text(screenshot_cells[0], ["메인 화면", ""])
        set_cell_text(screenshot_cells[1], ["동작 화면", ""])

        updated_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)

        with ZipFile(dst, "w", ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == "word/document.xml":
                    zout.writestr(item, updated_xml)
                else:
                    zout.writestr(item, zin.read(item.filename))

    print(dst)


if __name__ == "__main__":
    main()
