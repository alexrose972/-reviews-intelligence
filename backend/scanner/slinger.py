"""Slinger 3000 handoff — exact SYSTEM prompt from slinger_3000_email_builder.tsx."""

import os
from typing import List, Optional
import anthropic

SLINGER_SYSTEM = """You are an expert B2B email copywriter for Yotpo, a reviews and loyalty platform. You write outbound cold email sequences for the lifecycle product marketing team.

TONE AND STYLE RULES (follow exactly):
- Emails must be readable in 15 seconds. Short. Punchy. Every sentence earns its place.
- Email 1 must open with a one-sentence human intro: who Alex is and why she's writing. Example: "I'm Alex, I work on product marketing at Yotpo, and I'm reaching out to a handful of brands we think could be a strong fit." Keep it natural, not corporate.
- After the intro, make one specific point. One. Not three. Not a list of five things.
- Each follow-up email adds one new angle, stat, or proof point. Never repeat what was already said.
- The final email is 3-5 sentences max. Low pressure. Easy to reply to.
- Never use em-dashes. Use commas or periods instead.
- Zero contrast framing. No binary setups. No rhetorical reversals. No "not this, but that" phrasing. No "it's not" or "stop/start" constructions. No "either/or" or "X is dead" tropes.
- Keep it specific and concrete. One clear point per paragraph with a real detail.
- Paragraphs are 1-3 sentences. Never longer.
- No bullet lists unless there are exactly 3 items and prose would be harder to read.
- Never use jargon: no "synergies", "leverage", "unlock", "game-changer", "revolutionize".
- Never use the phrase "I wanted to reach out".
- Sign off as Alex, Lifecycle Product Marketing Manager, Yotpo.
- All emails share the SAME subject line. Write it once at the top. Do not repeat it.
- Label each email as "Email 1", "Email 2" etc.
- Use {{First Name}} and {{Account Name}} as personalization tokens.

OUTPUT FORMAT:
Plain text only. No markdown, no asterisks, no bold, no headers except email labels.

Subject: [subject line]

Email 1
[body]

Email 2
[body]"""


def build_context(
    brand_name: str,
    domain: str,
    overall_score: int,
    grade: str,
    scores: dict,
    pitch_angles: List[str],
    detected_platform: Optional[str],
    sf_platform: Optional[str],
    platform_mismatch: bool,
    vertical: Optional[str],
    page_speed_score: Optional[float],
    llm_quote: str,
    llm_failed: bool,
) -> str:
    from ..scanner.utils import DIMENSION_LABELS, WHY_IT_MATTERS

    lines = [
        f"Brand: {brand_name} ({domain})",
        f"Overall reviews experience score: {overall_score}/100 (Grade {grade})",
        f"Detected reviews platform: {detected_platform or 'unknown'}",
    ]
    if sf_platform:
        lines.append(f"Salesforce listed platform: {sf_platform}")
    if platform_mismatch:
        lines.append("NOTE: Platform mismatch between SF and live site")
    if vertical:
        lines.append(f"Detected vertical: {vertical}")
    if page_speed_score is not None:
        lines.append(f"Mobile page speed score: {page_speed_score:.0f}/100")

    # Worst dimensions first
    sorted_dims = sorted(
        [(k, v) for k, v in scores.items()],
        key=lambda x: x[1].get("score", 0) / max(x[1].get("max_score", 1), 1),
    )
    lines.append("\nKey weaknesses found:")
    for key, dim in sorted_dims[:4]:
        label = DIMENSION_LABELS.get(key, key)
        lines.append(f"- {label} ({dim.get('score', 0)}/{dim.get('max_score', 0)}): {dim.get('finding', '')}")

    lines.append("\nTop pitch angles:")
    for i, angle in enumerate(pitch_angles, 1):
        lines.append(f"{i}. {angle}")

    if llm_failed and llm_quote:
        lines.append(
            f"\nLLM crawlability failure (use verbatim in email): "
            f"When asked to quote a review, Claude said: \"{llm_quote[:200]}\""
        )
    return "\n".join(lines)


def parse_slinger_output(text: str) -> dict:
    """Parse Slinger output into subject + list of {num, body} emails."""
    sub_match = __import__("re").search(r"Subject:\s*(.+)", text, __import__("re").I)
    subject = sub_match.group(1).strip() if sub_match else ""
    body = __import__("re").sub(r"Subject:.*\n?", "", text, flags=__import__("re").I)
    parts = __import__("re").split(r"\bEmail\s+(\d+)\b", body, flags=__import__("re").I)

    emails = []
    num = 1
    for chunk in parts:
        chunk = chunk.strip()
        if __import__("re").match(r"^\d+$", chunk):
            num = int(chunk)
            continue
        if chunk:
            emails.append({"num": num, "body": chunk})
            num += 1

    if not emails:
        emails = [{"num": 1, "body": text}]
    return {"subject": subject, "emails": emails}


def generate_drafts(
    brand_name: str,
    context: str,
    email_count: int = 3,
) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"subject": "", "emails": [], "raw": "(No ANTHROPIC_API_KEY)"}

    client = anthropic.Anthropic(api_key=api_key)
    user_msg = (
        f'Write a {email_count}-email outbound sequence for Yotpo targeting the brand "{brand_name}".\n'
        f"Angle / campaign type: Reviews\n"
        f"Additional context: {context}\n"
        f"Reference the brand name naturally.\n"
        f"Write all {email_count} emails now."
    )
    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1400,
            system=SLINGER_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = msg.content[0].text.strip()
        result = parse_slinger_output(raw)
        result["raw"] = raw
        return result
    except Exception as e:
        return {"subject": "", "emails": [], "raw": f"Slinger error: {e}"}
