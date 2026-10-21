"""
MIME Sanitization and Normalization Module.
Converts raw RFC 5322 MIME messages into clean, token-efficient Markdown representations.
"""

import email
from email import policy
from email.message import EmailMessage
import re
from typing import Optional, Tuple
from bs4 import BeautifulSoup
import markdownify
from app.schemas import SanitizedEmail


def clean_html(html_content: str) -> str:
    """
    Strips scripts, styles, metadata, tracking pixels, and converts to markdown.
    Preserves hyperlinks, headings, and bullet points.
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
        strip=["img"] # Images add noise; links are preserved
    )

    # Normalize whitespace: collapse multiple blank lines to at most two
    markdown_text = re.sub(r"\n{3,}", "\n\n", markdown_text)
    return markdown_text.strip()


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
        # Normalize plain text whitespace
        cleaned = re.sub(r"\n{3,}", "\n\n", plain_part).strip()
        return cleaned, False
    return "", False


def parse_raw_email(raw_bytes: bytes, imap_uid: str) -> SanitizedEmail:
    """
    Parses raw RFC 5322 bytes into a validated SanitizedEmail instance.
    """
    msg: EmailMessage = email.message_from_bytes(raw_bytes, policy=policy.default)

    sender = str(msg.get("From", "Unknown Sender"))
    subject = str(msg.get("Subject", "No Subject"))
    date_header = str(msg.get("Date", ""))

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
