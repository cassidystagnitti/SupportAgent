from __future__ import annotations

from anthropic import Anthropic

from support_agent.config import Settings

SYSTEM_PROMPT = """You are a support specialist for Happier Meditation. Write clear, warm, concise replies that match a calm mindfulness brand tone. Do not make up refund, account, or policy details you do not have—if needed, say you will verify and follow up. Output only the email body text the human agent can send as-is (no subject line, no signature block, no internal notes)."""


def generate_draft_reply(
    settings: Settings,
    *,
    subject: str,
    transcript: str,
) -> str:
    client = Anthropic(api_key=settings.anthropic_api_key)
    user = f"Subject: {subject}\n\nConversation transcript:\n{transcript}"
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=2_048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
    )
    parts: list[str] = []
    for block in msg.content:
        if block.type == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()
