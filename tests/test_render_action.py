"""Task 63 — render_action message augmentation."""

from backend.pipeline.router import ChatRequest, _apply_render_action_message


def test_render_action_script_gen_augment_message() -> None:
    body = ChatRequest(
        message="",
        render_action={
            "action": "script.gen",
            "hotspots": [{"title": "考研择校", "score": 90}],
        },
    )
    out = _apply_render_action_message(body)
    assert "口播" in out
    assert "考研择校" in out
