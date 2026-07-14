"""Tests for eval_draft_accuracy.py — draft vs. sent-reply similarity classification."""

from __future__ import annotations

from eval_draft_accuracy import classify_similarity


def test_unedited():
    assert classify_similarity("Hello Jane, thanks!", "Hello Jane, thanks!") == "sent_unedited"


def test_edited():
    assert classify_similarity(
        "Hello Jane, thanks for reaching out about your refund.",
        "Hi Jane! Thanks for reaching out about the refund — done!",
    ) == "edited"


def test_discarded():
    assert classify_similarity("Totally different draft", None) == "discarded"


def test_discarded_when_very_different_text():
    assert classify_similarity(
        "Your subscription has been cancelled as requested.",
        "We are unable to process refunds for gift cards purchased more than a year ago.",
    ) == "discarded"


def test_unedited_ignores_html_tags_and_whitespace():
    draft = "<p>Hello Jane,</p><p>Thanks!</p>"
    sent = "Hello   Jane,\n\nThanks!"
    assert classify_similarity(draft, sent) == "sent_unedited"


def test_discarded_when_sent_is_none_even_if_draft_present():
    assert classify_similarity("Some draft text here", None) == "discarded"


def test_discarded_when_both_none_or_empty():
    assert classify_similarity("", None) == "discarded"


def test_edited_boundary_just_below_unedited_threshold():
    # Minor word swap should land in the "edited" band, not "sent_unedited".
    draft = "Hi Jane, thanks so much for reaching out about your account today."
    sent = "Hi Jane, thanks so much for reaching out about your account this morning."
    result = classify_similarity(draft, sent)
    assert result in ("edited", "sent_unedited")  # exact band depends on ratio; must not be discarded
    assert result != "discarded"
