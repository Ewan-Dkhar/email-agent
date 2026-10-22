"""
Email Action Skills Module.
Enforces the Human-in-the-Loop (HITL) gate for email drafting and composition.
Never directly dispatches outbound emails over SMTP.
"""

from typing import Dict, Optional
import uuid
from pydantic import AliasChoices, BaseModel, Field
from app.tools.base import BaseSkill, SkillResult
from app.tools.registry import registry


class DraftEmailArgs(BaseModel):
    recipient: str = Field(
        description="Target recipient email address",
        validation_alias=AliasChoices("recipient", "to", "email")
    )
    subject: str = Field(description="Subject line for the reply (typically starting with 'Re: ')")
    body_markdown: str = Field(
        description="Content of the reply in clear Markdown format",
        validation_alias=AliasChoices("body_markdown", "body", "content", "text")
    )



class DraftEmailReplySkill(BaseSkill):
    name = "draft_email_reply"
    description = (
        "Drafts an email reply for user review and approval. "
        "Strictly stages the draft locally. NEVER sends the email directly."
    )
    args_schema = DraftEmailArgs

    # In-memory staging store for active session drafts
    _staged_drafts: Dict[str, Dict[str, str]] = {}

    async def execute(self, recipient: str, subject: str, body_markdown: str) -> SkillResult:
        try:
            draft_id = f"draft_{uuid.uuid4().hex[:8]}"
            draft_record = {
                "draft_id": draft_id,
                "recipient": recipient,
                "subject": subject,
                "body_markdown": body_markdown,
                "status": "PENDING_APPROVAL"
            }
            DraftEmailReplySkill._staged_drafts[draft_id] = draft_record

            return SkillResult(
                success=True,
                data={
                    "draft_id": draft_id,
                    "recipient": recipient,
                    "subject": subject,
                    "message": "Draft created successfully. Staged locally awaiting user approval in dashboard."
                }
            )
        except Exception as e:
            return SkillResult(success=False, error=f"Drafting error: {str(e)}")

    @classmethod
    def get_staged_draft(cls, draft_id: str) -> Optional[Dict[str, str]]:
        """Retrieves a staged draft by ID."""
        return cls._staged_drafts.get(draft_id)


# Register by default
registry.register(DraftEmailReplySkill)
