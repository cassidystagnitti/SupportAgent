from __future__ import annotations

import os

SKILL_DIR = ".claude/skills"
EXPECTED = [
    "bert-morning-review",
    "bert-summarize-mailbox",
    "bert-hydrate-ticket",
    "bert-draft-all",
    "bert-resolve",
    "bert-post",
]


def test_all_skills_exist_with_frontmatter():
    for name in EXPECTED:
        path = os.path.join(SKILL_DIR, name, "SKILL.md")
        assert os.path.exists(path), f"missing {path}"
        head = open(path).read(400)
        assert head.startswith("---")
        assert "name:" in head
        assert "description:" in head


def test_morning_review_references_steps():
    body = open(os.path.join(SKILL_DIR, "bert-morning-review", "SKILL.md")).read().lower()
    for step in ["summarize", "draft", "resolve", "post"]:
        assert step in body


def test_skills_reference_real_entry_points():
    checks = {
        "bert-summarize-mailbox": "bert.summarize",
        "bert-hydrate-ticket": "bert.pipeline",
        "bert-draft-all": "bert.fanout",
        "bert-post": "bert.fanout.apply_result",
    }
    for name, module in checks.items():
        body = open(os.path.join(SKILL_DIR, name, "SKILL.md")).read()
        assert module in body, f"{name} should reference {module}"


def test_system_prompt_exists():
    assert os.path.exists("bert/prompts/bert_system_prompt.txt")
    assert len(open("bert/prompts/bert_system_prompt.txt").read()) > 200
