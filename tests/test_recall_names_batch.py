"""[F] 리콜 상품명 배치 부착 — 라벨은 'N건 이상'·분모 실측, 표본은 재현, DB·네트워크 없이 검사."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from sourcing_guard.batch import BatchRow, RowVerdict  # noqa: E402
from sourcing_guard.item_grades import ItemGradeBook  # noqa: E402
from sourcing_guard.kats_client import RecallRecord  # noqa: E402


def _rec(uid, name):
    return RecallRecord(product_name=name, model_name=None, maker=None, reason=None,
                        announced_on="20260901", detail_url="https://www.safetykorea.kr/r", scope="domestic", uid=uid)


def test_label_uses_the_measured_denominator_not_4244():
    from recall_names_batch import label

    assert label(4245) == "리콜 상품명 · 배치 경로 · 분모 4,245 · 검수 없음"
    src = (Path(__file__).resolve().parents[1] / "scripts/recall_names_batch.py").read_text(encoding="utf-8")
    assert "len(recs)" in src and "건 이상" in src
    assert "분모 4,244" not in src.replace("4,244 를 하드코딩하지 않는다", "")


def test_attach_keeps_row_pairing_across_chunks(monkeypatch):
    """배치는 500줄씩 자른다 - 잘라도 (리콜, 행) 짝이 밀리지 않아야 한다."""
    import recall_names_batch as m

    monkeypatch.setattr(m, "MAX_ROWS", 3)
    recs = [_rec(f"u{i}", f"블록 완구 {i}호") for i in range(7)]
    pairs = m.attach(recs, ItemGradeBook())
    assert [r.uid for r, _ in pairs] == [f"u{i}" for i in range(7)]
    assert [b.product_name for _, b in pairs] == [r.product_name for r in recs]


def test_summarize_and_sample_are_deterministic():
    from recall_names_batch import sample, summarize

    def row(i, hit):
        return BatchRow(line=i, product_name=f"p{i}", matched_items=["완구"] if hit else [],
                        grade="안전확인" if hit else None, verdict=RowVerdict.CERT_REQUIRED if hit else RowVerdict.UNDECIDED)
    pairs = [(_rec(f"u{i}", f"p{i}"), row(i, i % 3 == 0)) for i in range(60)]
    s = summarize(pairs)
    assert s["n"] == 60 and s["matched"] == 20 and abs(s["pct"] - 33.3) < 0.1
    assert s["items"][0] == ("완구", 20) and s["grades"] == {"안전확인": 20}
    assert s["silent_verdicts"] == {"undecided": 40}
    a = [r.uid for r, _ in sample(pairs)]
    b = [r.uid for r, _ in sample(pairs)]
    assert a == b and len(a) == 45                      # 붙은 20 전부 + 안 붙은 25
    hits = {r.uid for r, b2 in pairs if b2.grade}
    assert sum(u in hits for u in a) == 20


def test_the_doc_says_at_least_and_not_accuracy():
    src = (Path(__file__).resolve().parents[1] / "scripts/recall_names_batch.py").read_text(encoding="utf-8")
    assert "건 이상" in src and "세지 않는다" in src
    assert "정답률" not in src
    assert "판정은 사람이 한다" in src
