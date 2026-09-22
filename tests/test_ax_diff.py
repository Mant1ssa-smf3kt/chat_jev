"""AXSource 的 diff 逻辑不依赖真实窗口，直接构造快照测。"""

from chat_jev.sources.ax import AppSource, Row, Snapshot, _rfind_subseq


def _src():
    s = AppSource.__new__(AppSource)
    s._prev = None
    return s


def R(sender, text):
    return Row(sender, "", text)


def test_first_snapshot_is_baseline_only():
    s = _src()
    assert s._diff(Snapshot("A", [R("them", "hi")])) == []


def test_new_rows_after_anchor():
    s = _src()
    s._prev = Snapshot("A", [R("me", "1"), R("them", "2")])
    out = s._diff(Snapshot("A", [R("me", "1"), R("them", "2"), R("them", "3"), R("me", "4")]))
    assert [r.text for r in out] == ["3", "4"]


def test_scrolled_list_still_finds_anchor():
    s = _src()
    s._prev = Snapshot("A", [R("me", "0"), R("me", "1"), R("them", "2")])
    out = s._diff(Snapshot("A", [R("me", "1"), R("them", "2"), R("them", "3")]))
    assert [r.text for r in out] == ["3"]


def test_duplicate_texts_use_two_row_anchor():
    s = _src()
    s._prev = Snapshot("A", [R("them", "哈哈"), R("me", "嗯"), R("them", "哈哈")])
    out = s._diff(Snapshot("A", [R("them", "哈哈"), R("me", "嗯"), R("them", "哈哈"), R("them", "哈哈")]))
    assert [r.text for r in out] == ["哈哈"]


def test_contact_switch_resets():
    s = _src()
    s._prev = Snapshot("A", [R("them", "x")])
    assert s._diff(Snapshot("B", [R("them", "x"), R("them", "y")])) == []


def test_anchor_missing_emits_nothing():
    s = _src()
    s._prev = Snapshot("A", [R("them", "old")])
    assert s._diff(Snapshot("A", [R("them", "new1"), R("them", "new2")])) == []


def test_rfind_subseq():
    assert _rfind_subseq([1, 2, 3, 2, 3], [2, 3]) == 3
    assert _rfind_subseq([1, 2], [3]) is None
