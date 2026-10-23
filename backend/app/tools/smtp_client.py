"""
SMTP Outbound Email Dispatcher.
Executes authenticated SMTP email sending for human-approved email drafts.
Supports STARTTLS (Port 587) and SSL/TLS (Port 465) with async thread offloading.
"""

import asyncio
import email.utils
from email.message import EmailMessage
import logging
import smtplib
import ssl
from typing import Any, Dict, Optional
from app.config import SmtpConfig, get_settings

logger = logging.getLogger(__name__)


class SmtpClientError(Exception):
    """Base exception for SMTP transmission failures."""
    pass


class SmtpConfigurationError(SmtpClientError):
    """Raised when SMTP credentials or settings are missing or invalid."""
    pass


class SmtpAuthError(SmtpClientError):
    """Raised when SMTP authentication is rejected by the server."""
    pass


class SmtpConnectionError(SmtpClientError):
    """Raised when network connection to the SMTP server fails or times out."""
    pass


class SmtpClient:
    def __init__(self, config: Optional[SmtpConfig] = None):
        self.config = config or get_settings().smtp
        self.imap_config = get_settings().imap

    @property
    def username(self) -> str:
        return self.config.get_username(self.imap_config.username)

    @property
    def password(self) -> str:
        return self.config.get_password(self.imap_config.password)

    @property
    def from_address(self) -> str:
        return self.config.get_from_address(self.imap_config.username)

    def validate_configuration(self) -> None:
        """Ensures minimal requirements are present for sending email."""
        if not self.config.host:
            raise SmtpConfigurationError("SMTP host is not configured.")
        if not self.username:
            raise SmtpConfigurationError(
                "SMTP username is missing. Please configure 'smtp.username' or 'imap.username'."
            )
        if not self.password:
            raise SmtpConfigurationError(
                "SMTP password is missing. Please configure 'smtp.password' or 'imap.password'."
            )
        if not self.from_address:
            raise SmtpConfigurationError("Sender address ('from_address') is missing.")

    def send_email(self, recipient: str, subject: str, body_text: str) -> Dict[str, Any]:
        """
        Synchronously builds and dispatches an RFC 5322 compliant message over SMTP.
        """
        self.validate_configuration()

        if not recipient or "@" not in recipient:
            raise ValueError(f"Invalid recipient email address: '{recipient}'")

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.from_address
        msg["To"] = recipient
        msg["Date"] = email.utils.formatdate(localtime=True)
        msg["Message-ID"] = email.utils.make_msgid()
        msg.set_content(body_text)

        host = self.config.host
        port = self.config.port
        use_ssl = self.config.use_ssl or port == 465

        logger.info(f"Connecting to SMTP server at {host}:{port} (SSL: {use_ssl})...")

        try:
            if use_ssl:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(host=host, port=port, context=context, timeout=30.0) as server:
                    server.login(self.username, self.password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(host=host, port=port, timeout=30.0) as server:
                    if self.config.use_tls:
                        context = ssl.create_default_context()
                        server.starttls(context=context)
                    server.login(self.username, self.password)
                    server.send_message(msg)

            logger.info(f"Successfully sent email to {recipient} with Subject: '{subject}'")
            return {
                "success": True,
                "recipient": recipient,
                "subject": subject,
                "message_id": msg["Message-ID"],
            }

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP Authentication failed for user {self.username}: {str(e)}")
            raise SmtpAuthError(f"SMTP Authentication failed: {str(e)}") from e
        except smtplib.SMTPConnectError as e:
            logger.error(f"Failed to connect to SMTP server {host}:{port}: {str(e)}")
            raise SmtpConnectionError(f"SMTP connection error: {str(e)}") from e
        except (TimeoutError, smtplib.SMTPException, OSError) as e:
            logger.error(f"SMTP dispatch failure: {str(e)}")
            raise SmtpClientError(f"SMTP error: {str(e)}") from e

    async def send_email_async(self, recipient: str, subject: str, body_text: str) -> Dict[str, Any]:
        """
        Asynchronously sends an email by offloading network I/O to a worker thread.
        Prevents blocking FastAPI's async event loop.
        """
        return await asyncio.to_thread(self.send_email, recipient, subject, body_text)
