from __future__ import annotations

import os

from process_answered_gaps import _parse_draft, _sanitize_filename, _target_doc_path


def test_sanitize_filename_basic():
    assert _sanitize_filename("Cancellation Policy") == "cancellation-policy"


def test_sanitize_filename_strips_punctuation():
    assert _sanitize_filename("Downloads / Offline!!  Meditations") == "downloads-offline-meditations"


def test_target_doc_path_resolves_existing_doc():
    path = _target_doc_path("Cancellation Policy")
    assert path is not None
    assert path.endswith(os.path.join("policies", "cancellation-policy.md"))
    assert os.path.exists(path)


def test_target_doc_path_returns_none_for_unknown_doc():
    assert _target_doc_path("Some Doc That Does Not Exist") is None


def test_target_doc_path_empty_returns_none():
    assert _target_doc_path("") is None


def test_parse_draft_plain_addition():
    text = "### New Section\n\nSome guidance."
    new_doc, body = _parse_draft(text)
    assert new_doc is None
    assert body == text


def test_parse_draft_new_doc_marker():
    text = "NEW_DOC_SUGGESTED: podcast-pitches\n\n# Podcast Pitches\n\n# Summary\nBody text."
    new_doc, body = _parse_draft(text)
    assert new_doc == "podcast-pitches.md"
    assert body.startswith("# Podcast Pitches")
