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


def test_row_at_uses_band_and_list_area():
    from chat_jev.sources.ax import Snapshot
    rows = [Row("me", "", "a", band=(100, 140)), Row("them", "", "b", band=(140, 200))]
    snap = Snapshot("A", rows, area=(300, 80, 500, 600))
    assert snap.row_at(400, 120) == 0
    assert snap.row_at(700, 150) == 1
    assert snap.row_at(100, 150) is None          # 在会话列表那一侧，不在消息区
    assert snap.row_at(400, 500) is None          # 消息区空白处


def test_merge_window_scroll_up_down_and_new():
    from chat_jev.sources.ax import merge_window
    rows = [R("them", str(i)) for i in range(30)]
    known, off = merge_window([], rows[15:30])
    assert off == 0
    known, off = merge_window(known, rows[8:22])          # 往上翻：前面接上更早的
    assert [r.text for r in known] == [str(i) for i in range(8, 30)] and off == 0
    known, off = merge_window(known, rows[10:24])         # 在中间
    assert len(known) == 22 and off == 2
    more = rows + [R("them", "30")]
    known, off = merge_window(known, more[20:31])          # 底部来了新消息
    assert known[-1].text == "30" and len(known) == 23 and off == 12


def test_merge_window_no_overlap_restarts():
    from chat_jev.sources.ax import merge_window
    known, _ = merge_window([R("me", "a"), R("me", "b")], [R("them", "x"), R("them", "y")])
    assert [r.text for r in known] == ["x", "y"]
