from __future__ import annotations

import bert.state as st


def test_new_state_shape():
    s = st.new_state("2026-07-06")
    assert s == {"date": "2026-07-06", "records": [], "brief": [], "statuses": {}}


def test_save_and_load_roundtrip(tmp_path):
    s = st.new_state("2026-07-06")
    st.append_brief(s, "Streak bug fixed 7/5")
    st.set_records(s, [{"conversation_id": 1}])
    st.save(s, base_dir=str(tmp_path))
    loaded = st.load("2026-07-06", base_dir=str(tmp_path))
    assert loaded["brief"] == ["Streak bug fixed 7/5"]
    assert loaded["records"] == [{"conversation_id": 1}]


def test_load_missing_returns_new(tmp_path):
    assert st.load("1999-01-01", base_dir=str(tmp_path))["records"] == []


def test_render_brief_empty_and_bulleted():
    s = st.new_state("d")
    assert st.render_brief(s) == ""
    st.append_brief(s, "A")
    st.append_brief(s, "B")
    assert st.render_brief(s) == "- A\n- B"


def test_append_brief_dedupes_exact():
    s = st.new_state("d")
    st.append_brief(s, "same")
    st.append_brief(s, "same")
    assert s["brief"] == ["same"]


def test_append_brief_ignores_blank():
    s = st.new_state("d")
    st.append_brief(s, "   ")
    assert s["brief"] == []


def test_set_status_merges(tmp_path):
    s = st.new_state("d")
    st.set_status(s, "42", drafted=True, confidence="low")
    st.set_status(s, "42", posted=True)
    assert s["statuses"]["42"] == {"drafted": True, "confidence": "low", "posted": True}
