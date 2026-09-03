"""주격·보조사·목적격 조사 선택.

"인증번호 이(가) 조회되었습니다" 처럼 두 형태를 병기하면 문장이 어색하다.
심사위원과 셀러가 읽는 화면이라 한 글자를 맞춘다.
"""

import pytest

from sourcing_guard.models import object_particle, subject_particle, topic_particle


@pytest.mark.parametrize(
    "word,want",
    [
        ("모델명", "이"), ("인증번호", "가"), ("제조사와 제품명", "이"), ("성분", "이"),
        # 숫자로 끝나면 읽는 소리로 판단한다
        ("CB061R2170-3018", "이"),  # 8 → 팔
        ("B363R871-5002", "가"),    # 2 → 이
        ("X-1", "이"), ("X-3", "이"), ("X-4", "가"), ("X-5", "가"),
        ("X-6", "이"), ("X-7", "이"), ("X-9", "가"), ("X-0", "이"),
    ],
)
def test_subject_particle(word, want):
    assert subject_particle(word) == want


@pytest.mark.parametrize(
    "word,topic,obj",
    [("모델명", "은", "을"), ("인증번호", "는", "를"),
     ("CB061R2170-3018", "은", "을"), ("B363R871-5002", "는", "를")],
)
def test_topic_and_object_particles(word, topic, obj):
    assert topic_particle(word) == topic
    assert object_particle(word) == obj


def test_empty_input_does_not_crash():
    for fn, opts in ((subject_particle, ("이", "가")),
                     (topic_particle, ("은", "는")),
                     (object_particle, ("을", "를"))):
        assert fn("") in opts


def test_no_dual_particles_remain_in_user_facing_copy():
    """병기 표기가 되살아나지 않게 고정한다.

    ⚠ 주석과 docstring 은 걷어내고 본다. 이 규칙을 설명하는 글 자체가
      "인증번호 이(가)" 를 예로 들기 때문이다 - 걷어내지 않으면 가드가 자기
      설명에 걸린다.
    """
    import ast
    from pathlib import Path

    for src_path in sorted(Path("sourcing_guard").glob("*.py")):
        src = src_path.read_text(encoding="utf-8")
        doc_lines: set[int] = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                doc_lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
        body = "\n".join(
            line for i, line in enumerate(src.splitlines(), start=1)
            if i not in doc_lines and not line.lstrip().startswith("#")
        )
        for dual in ("이(가)", "은(는)", "을(를)"):
            assert dual not in body, f"{src_path.name} 에 {dual} 병기가 있습니다"
