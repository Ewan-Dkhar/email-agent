"""
MIME Sanitization and Normalization Module.
Converts raw RFC 5322 MIME messages into clean, token-efficient Markdown representations.
Applies multi-layered defense against Indirect Prompt Injection (IPI):
1. Zero-width character & steganography stripping
2. Control token escaping (<start_of_turn>, [INST], <|im_start|>)
3. Structural boundary isolation (<untrusted_email_data>)
"""

import email
from email import policy
from email.message import EmailMessage
import re
from typing import Optional, Tuple
from bs4 import BeautifulSoup
import markdownify
from app.schemas import SanitizedEmail

# Regular expression to match zero-width and invisible unicode characters
# used for prompt injection steganography
ZERO_WIDTH_PATTERN = re.compile(
    r"[\u200B-\u200D\u200E\u200F\u202A-\u202E\u2060-\u2064\uFEFF]"
)

# Control characters excluding standard newline (\n), carriage return (\r), and tab (\t)
CONTROL_CHAR_PATTERN = re.compile(
    r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]"
)

# LLM Chat template and tokenizer control tokens that attackers use to break out of turns
LLM_CONTROL_TOKENS = [
    "<start_of_turn>",
    "<end_of_turn>",
    "[INST]",
    "[/INST]",
    "<<SYS>>",
    "<</SYS>>",
    "<|im_start|>",
    "<|im_end|>",
    "<|system|>",
    "<|user|>",
    "<|assistant|>",
]

BOUNDARY_TAG_OPEN = "<untrusted_email_data>"
BOUNDARY_TAG_CLOSE = "</untrusted_email_data>"


def sanitize_text_security(text: str) -> str:
    """
    Applies security mitigations against Indirect Prompt Injection (IPI):
    - Strips zero-width steganographic characters.
    - Strips non-printable control characters.
    - Neutralizes LLM conversational control tokens.
    - Escapes structural boundary tags to prevent breakout attacks.
    """
    if not text:
        return ""

    # 1. Remove invisible / zero-width characters
    cleaned = ZERO_WIDTH_PATTERN.sub("", text)

    # 2. Remove anomalous control characters
    cleaned = CONTROL_CHAR_PATTERN.sub("", cleaned)

    # 3. Neutralize known model special tokens to prevent turn-hijacking
    for token in LLM_CONTROL_TOKENS:
        if token in cleaned:
            # Defuse by escaping angle brackets or brackets
            defused = token.replace("<", "&lt;").replace(">", "&gt;").replace("[", "&#91;").replace("]", "&#93;")
            cleaned = cleaned.replace(token, defused)

    # 4. Defuse boundary breakout attempts
    cleaned = cleaned.replace(BOUNDARY_TAG_CLOSE, "&lt;/untrusted_email_data&gt;")
    cleaned = cleaned.replace(BOUNDARY_TAG_OPEN, "&lt;untrusted_email_data&gt;")

    return cleaned


def wrap_untrusted_content(content: str) -> str:
    """
    Encloses untrusted content in strict, escaped XML-like boundary tags.
    Ensures downstream prompt builders isolate untrusted data from instructions.
    """
    safe_content = sanitize_text_security(content)
    return f"{BOUNDARY_TAG_OPEN}\n{safe_content}\n{BOUNDARY_TAG_CLOSE}"


def clean_html(html_content: str) -> str:
    """
    Strips scripts, styles, metadata, tracking pixels, and converts to markdown.
    Preserves hyperlinks, headings, and bullet points while neutralizing security risks.
    """
    soup = BeautifulSoup(html_content, "html.parser")

    # Remove non-content tags completely
    for element in soup(["script", "style", "meta", "head", "noscript", "svg", "canvas", "iframe"]):
        element.decompose()

    # Remove invisible tracking pixels (1x1 or 0x0 images)
    for img in soup.find_all("img"):
        width = img.get("width")
        height = img.get("height")
        if (width in ("0", "1") or height in ("0", "1")) or (not img.get("src")):
            img.decompose()
        elif img.get("src", "").startswith("data:"):
            # Strip base64 embedded image bloat
            img.decompose()

    # Convert sanitized HTML DOM to Markdown
    markdown_text = markdownify.markdownify(
        str(soup),
        heading_style="ATX",
        bullets="-",
        strip=["img"]  # Images add noise; links are preserved
    )

    # Apply text security filtering (zero-width, control tokens, breakout escapes)
    secured_text = sanitize_text_security(markdown_text)

    # Normalize whitespace: collapse multiple blank lines to at most two
    secured_text = re.sub(r"\n{3,}", "\n\n", secured_text)
    return secured_text.strip()


def extract_body_from_mime(msg: EmailMessage) -> Tuple[str, bool]:
    """
    Recursively extracts the best content representation from an EmailMessage.
    Prefers HTML (converted to Markdown) because it preserves critical URLs.
    Returns: (cleaned_body, is_html)
    """
    html_part: Optional[str] = None
    plain_part: Optional[str] = None

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))

            # Skip attachments
            if "attachment" in disposition:
                continue

            try:
                payload = part.get_content()
                if not isinstance(payload, str):
                    continue
            except Exception:
                continue

            if content_type == "text/html" and not html_part:
                html_part = payload
            elif content_type == "text/plain" and not plain_part:
                plain_part = payload
    else:
        content_type = msg.get_content_type()
        try:
            payload = msg.get_content()
            if isinstance(payload, str):
                if content_type == "text/html":
                    html_part = payload
                else:
                    plain_part = payload
        except Exception:
            plain_part = ""

    if html_part:
        return clean_html(html_part), True
    elif plain_part:
        # Apply security sanitization to plain text as well
        secured = sanitize_text_security(plain_part)
        cleaned = re.sub(r"\n{3,}", "\n\n", secured).strip()
        return cleaned, False
    return "", False


def parse_raw_email(raw_bytes: bytes, imap_uid: str) -> SanitizedEmail:
    """
    Parses raw RFC 5322 bytes into a validated SanitizedEmail instance.
    """
    msg: EmailMessage = email.message_from_bytes(raw_bytes, policy=policy.default)

    raw_sender = str(msg.get("From", "Unknown Sender"))
    raw_subject = str(msg.get("Subject", "No Subject"))
    date_header = str(msg.get("Date", ""))

    # Sanitize header values as well (headers can also contain prompt injection payloads)
    sender = sanitize_text_security(raw_sender)
    subject = sanitize_text_security(raw_subject)

    cleaned_body, _ = extract_body_from_mime(msg)

    # Create a 250-character snippet for fast UI indexing
    snippet = re.sub(r"\s+", " ", cleaned_body)[:250].strip()

    return SanitizedEmail(
        imap_uid=imap_uid,
        sender=sender,
        subject=subject,
        received_at=date_header,
        cleaned_body=cleaned_body,
        raw_snippet=snippet,
    )
