from types import SimpleNamespace
from claude_utils import extract_text


def _msg(blocks):
    return SimpleNamespace(content=blocks)


def test_extract_text_skips_thinking_block():
    blocks = [SimpleNamespace(type="thinking", thinking="hmm"),
              SimpleNamespace(type="text", text="hello")]
    assert extract_text(_msg(blocks)) == "hello"


def test_extract_text_plain():
    assert extract_text(_msg([SimpleNamespace(type="text", text="x")])) == "x"


def test_extract_text_no_text_block():
    assert extract_text(_msg([SimpleNamespace(type="thinking", thinking="only")])) == ""
