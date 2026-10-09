"""The D1 server-mode check reproduces the result before and after the render guard (D-22)."""
from pilot.d1 import d1_check


def test_d1_server_check_before_and_after_render_guard():
    before = d1_check.server_check("", guard=False)
    assert before["verdict"].startswith("LETS_THROUGH")
    assert set(before["forms_left"]) == set(d1_check.EXTERNAL)
    after = d1_check.server_check("", guard=True)
    assert after["verdict"] == "STRIPS_ALL" and after["forms_left"] == []
