from pathlib import Path

from agents_hub.models import LiveInfo, SessionMeta, display_title, format_tokens


def meta(**kw) -> SessionMeta:
    m = SessionMeta(session_id="abcdef1234", path=Path("/x.jsonl"))
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def live(**kw) -> LiveInfo:
    base = dict(pid=1, session_id="abcdef1234", cwd="/", status="idle", name=None,
                name_source=None, kind="interactive", updated_at=0.0, tty=None)
    base.update(kw)
    return LiveInfo(**base)


def test_title_prefers_custom():
    assert display_title(meta(custom_title="A", ai_title="B"), None, None) == "A"


def test_title_skips_derived_name():
    lv = live(name="proj-b3", name_source="derived")
    assert display_title(meta(ai_title="CVE hotfix"), lv, None) == "CVE hotfix"


def test_title_uses_user_name():
    lv = live(name="my-topic", name_source="user")
    assert display_title(meta(ai_title="X"), lv, None) == "my-topic"


def test_title_hub_title_first():
    assert display_title(meta(custom_title="A"), None, "H") == "H"


def test_title_falls_back_to_prompt():
    assert len(display_title(meta(first_prompt="x" * 80), None, None)) == 60


def test_title_falls_back_to_id():
    assert display_title(meta(), None, None) == "abcdef12"


def test_format_tokens():
    assert format_tokens(None) == "—"
    assert format_tokens(512) == "512"
    assert format_tokens(187_600) == "188k"
