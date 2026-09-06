"""报告素材组装测试(纯逻辑):引用池规则定死、可精确断言。"""
from researchpilot.core.events import Verdict
from researchpilot.core.models import EvidenceReview, Note, NoteReview, SearchSource, SubQuestion
from researchpilot.core.report import (
    CitedSource, build_report_sources, render_references,
)


def _note(sub_index, claim, evidence_indexes, n_sources=3) -> Note:
    return Note(
        sub_index=sub_index,
        claim=claim,
        sources=[SearchSource(url=f"https://s{sub_index}.{i}.io", title=f"S{sub_index}-{i}") for i in range(n_sources)],
        evidence_indexes=evidence_indexes,
    )


def _review(sub_index, verdicts: dict[int, Verdict]) -> NoteReview:
    return NoteReview(sub_index=sub_index, evidence=[
        EvidenceReview(index=i, verdict=v, reason="r") for i, v in verdicts.items()
    ])


def test_supported_only_enter_pool_with_global_numbering():
    subs = [SubQuestion(index=0, question="Q0", queries=["q"]), SubQuestion(index=1, question="Q1", queries=["q"])]
    notes = [
        _note(0, "c0", [0, 1]),  # 引用 0,1 号来源
        _note(1, "c1", [0]),
    ]
    reviews = [
        _review(0, {0: Verdict.SUPPORTED, 1: Verdict.UNSUPPORTED}),
        _review(1, {0: Verdict.SUPPORTED}),
    ]

    sections, pool = build_report_sources(subs, notes, reviews)

    # note0 只有 [0] 合格 -> 全局编号 1;note1 的 [0] -> 编号 2
    assert [c.citation_no for c in pool] == [1, 2]
    assert pool[0].url == "https://s0.0.io"
    assert sections[0].citation_nos == [1]
    assert sections[0].insufficient is False
    assert sections[1].citation_nos == [2]


def test_unverifiable_is_excluded_and_note_marked_insufficient():
    subs = [SubQuestion(index=0, question="Q0", queries=["q"])]
    notes = [_note(0, "c0", [0])]
    reviews = [_review(0, {0: Verdict.UNVERIFIABLE})]

    sections, pool = build_report_sources(subs, notes, reviews)
    assert pool == []  # 没有合格证据 -> 引用池空
    assert sections[0].insufficient is True
    assert sections[0].citation_nos == []


def test_note_without_evidence_is_insufficient():
    """Researcher 诚实输出空 evidence(证据不足)时,节被标记不足。"""
    subs = [SubQuestion(index=0, question="Q0", queries=["q"])]
    notes = [_note(0, "现有资料不足以回答", [])]
    reviews = [_review(0, {})]  # 无证据可核

    sections, _ = build_report_sources(subs, notes, reviews)
    assert sections[0].insufficient is True


def test_sections_follow_notes_order_and_keep_question():
    subs = [SubQuestion(index=0, question="Q0", queries=["q"]), SubQuestion(index=1, question="Q1", queries=["q"])]
    notes = [_note(1, "c1", [0]), _note(0, "c0", [0])]  # 故意乱序传入
    reviews = [_review(1, {0: Verdict.SUPPORTED}), _review(0, {0: Verdict.SUPPORTED})]

    sections, pool = build_report_sources(subs, notes, reviews)
    assert [s.sub_index for s in sections] == [1, 0]  # 跟随 notes 顺序
    assert sections[0].question == "Q1"
    assert [c.citation_no for c in pool] == [1, 2]


# -- render_references:确定性引用脚注 --------------------------------------

_POOL = [
    CitedSource(citation_no=1, url="https://a.io", title="来源A"),
    CitedSource(citation_no=2, url="https://b.io", title=""),
]


def test_render_references_appends_url_footer():
    md = render_references("# 报告\n\n正文 [1]。\n", _POOL)
    assert "## 引用来源" in md
    assert "[1] 来源A — https://a.io" in md  # 标题与 URL 都进脚注
    assert "[2] https://b.io" in md          # 无标题时只有 URL
    assert md.rstrip().endswith("[2] https://b.io")  # 在文末


def test_render_references_is_idempotent():
    once = render_references("# 报告\n\n正文 [1]。\n", _POOL)
    twice = render_references(once, _POOL)
    assert once == twice  # 已含引用来源标题 -> 不重复追加


def test_render_references_empty_pool_no_op():
    md = render_references("# 报告\n\n(证据不足的如实说明)\n", [])
    assert md == "# 报告\n\n(证据不足的如实说明)\n"
