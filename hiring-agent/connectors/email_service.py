"""
connectors/email_service.py
═══════════════════════════════════════════════════════
Interview invitation email service.

Sends each shortlisted candidate a personalised email with:
  - Their unique, private Jitsi interview link
  - Scheduled date and time
  - Role they applied for
  - What to expect / preparation tips
  - Contact email for questions

Transport: standard SMTP (works with Gmail, Outlook, or any SMTP relay).
Credentials are read from env vars — never hardcoded.

Gmail setup:
  1. Enable 2FA on your Google account
  2. Generate an App Password: myaccount.google.com/apppasswords
  3. Set SMTP_USER + SMTP_PASSWORD in .env

Template:
  HTML (with plain-text fallback).
  Inline CSS only — no external stylesheets (email client compatible).

Usage:
  service = EmailService.from_env()
  await service.send_interview_invite(
      applicant_name  = "Priya Sharma",
      applicant_email = "priya@example.com",
      role            = "Backend Engineer",
      meeting_url     = "https://meet.jit.si/HireIQ-A3F9B2C1",
      scheduled_at    = datetime(2026, 4, 20, 14, 30),
      interviewer_name = "Sarah Mitchell",
      company_name    = "HireIQ Technologies",
  )
"""

from __future__ import annotations

import asyncio
import os
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from utils.logger import logger


# ─────────────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────────────

@dataclass
class EmailConfig:
    """SMTP configuration loaded from environment variables."""
    host:       str
    port:       int
    user:       str
    password:   str
    from_name:  str
    from_email: str
    use_tls:    bool = True    # STARTTLS on port 587

    @classmethod
    def from_env(cls) -> "EmailConfig":
        return cls(
            host       = os.getenv("SMTP_HOST",       "smtp.gmail.com"),
            port       = int(os.getenv("SMTP_PORT",   "587")),
            user       = os.getenv("SMTP_USER",       ""),
            password   = os.getenv("SMTP_PASSWORD",   ""),
            from_name  = os.getenv("INTERVIEW_FROM_NAME",  "HireIQ Talent Team"),
            from_email = os.getenv("INTERVIEW_FROM_EMAIL", ""),
            use_tls    = os.getenv("SMTP_USE_TLS", "true").lower() == "true",
        )

    @property
    def configured(self) -> bool:
        return bool(self.user and self.password and self.from_email)


# ─────────────────────────────────────────────────────
#  Email templates
# ─────────────────────────────────────────────────────

def _format_datetime(dt: datetime) -> str:
    """Format datetime for email display: 'Monday, 20 April 2026 at 2:30 PM'"""
    hour   = dt.hour % 12 or 12
    minute = dt.strftime("%M")
    ampm   = "AM" if dt.hour < 12 else "PM"
    return dt.strftime(f"%A, %d %B %Y at {hour}:{minute} {ampm}")


def _render_html(
    applicant_name:   str,
    role:             str,
    meeting_url:      str,
    scheduled_at:     datetime,
    interviewer_name: str,
    company_name:     str,
) -> str:
    formatted_time = _format_datetime(scheduled_at)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Interview Invitation — {company_name}</title>
</head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">

  <!-- Outer wrapper -->
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:40px 0;">
  <tr><td align="center">

    <!-- Card -->
    <table width="600" cellpadding="0" cellspacing="0"
           style="background:#ffffff;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,0.08);overflow:hidden;max-width:600px;width:100%;">

      <!-- Header -->
      <tr>
        <td style="background:linear-gradient(135deg,#1a1a2e 0%,#16213e 60%,#0f3460 100%);padding:40px 40px 36px;text-align:center;">
          <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;letter-spacing:0.5px;">
            {company_name}
          </h1>
          <p style="margin:8px 0 0;color:#a0b4d8;font-size:13px;letter-spacing:1px;text-transform:uppercase;">
            Talent Acquisition
          </p>
        </td>
      </tr>

      <!-- Body -->
      <tr>
        <td style="padding:40px 40px 32px;">

          <p style="margin:0 0 8px;color:#888;font-size:13px;text-transform:uppercase;letter-spacing:0.8px;">Interview Invitation</p>
          <h2 style="margin:0 0 24px;color:#1a1a2e;font-size:26px;font-weight:700;line-height:1.3;">
            Hi {applicant_name},<br>you're invited to interview! 🎉
          </h2>

          <p style="margin:0 0 24px;color:#444;font-size:15px;line-height:1.7;">
            We reviewed your application for the <strong>{role}</strong> role and we're excited to move
            forward. {interviewer_name} from our talent team will conduct your interview.
          </p>

          <!-- Interview details card -->
          <table width="100%" cellpadding="0" cellspacing="0"
                 style="background:#f8f9ff;border:1px solid #e0e8ff;border-radius:10px;margin:0 0 28px;">
            <tr>
              <td style="padding:24px 28px;">
                <table width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td style="padding:0 0 14px;">
                      <span style="display:block;font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:4px;">Date &amp; Time</span>
                      <span style="font-size:15px;color:#1a1a2e;font-weight:600;">{formatted_time}</span>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:0 0 14px;">
                      <span style="display:block;font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:4px;">Role</span>
                      <span style="font-size:15px;color:#1a1a2e;font-weight:600;">{role}</span>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:0 0 14px;">
                      <span style="display:block;font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:4px;">Interviewer</span>
                      <span style="font-size:15px;color:#1a1a2e;font-weight:600;">{interviewer_name}</span>
                    </td>
                  </tr>
                  <tr>
                    <td>
                      <span style="display:block;font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:4px;">Format</span>
                      <span style="font-size:15px;color:#1a1a2e;font-weight:600;">Video Interview (3 rounds · ~45 minutes)</span>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>

          <!-- CTA Button -->
          <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 32px;">
            <tr>
              <td align="center">
                <a href="{meeting_url}"
                   style="display:inline-block;background:linear-gradient(135deg,#667eea,#764ba2);
                          color:#ffffff;text-decoration:none;font-size:16px;font-weight:600;
                          padding:16px 40px;border-radius:8px;letter-spacing:0.3px;">
                  Join Your Interview →
                </a>
              </td>
            </tr>
            <tr>
              <td align="center" style="padding-top:12px;">
                <span style="font-size:12px;color:#888;">Or copy this link: </span>
                <a href="{meeting_url}" style="font-size:12px;color:#667eea;word-break:break-all;">{meeting_url}</a>
              </td>
            </tr>
          </table>

          <!-- Tips -->
          <table width="100%" cellpadding="0" cellspacing="0"
                 style="background:#fffbf0;border:1px solid #ffe08a;border-radius:10px;margin:0 0 28px;">
            <tr>
              <td style="padding:20px 24px;">
                <p style="margin:0 0 12px;color:#92400e;font-weight:600;font-size:14px;">Before your interview</p>
                <ul style="margin:0;padding-left:18px;color:#6b4500;font-size:13px;line-height:2;">
                  <li>Test your camera and microphone</li>
                  <li>Use Chrome or Firefox for best experience</li>
                  <li>Find a quiet, well-lit space</li>
                  <li>Have your resume and portfolio ready</li>
                  <li>Join 2–3 minutes early</li>
                </ul>
              </td>
            </tr>
          </table>

          <p style="margin:0;color:#666;font-size:14px;line-height:1.7;">
            Questions? Reply to this email or contact us at
            <a href="mailto:{os.getenv('INTERVIEW_FROM_EMAIL', 'talent@hireiq.com')}"
               style="color:#667eea;">{os.getenv('INTERVIEW_FROM_EMAIL', 'talent@hireiq.com')}</a>.
            We look forward to meeting you!
          </p>

        </td>
      </tr>

      <!-- Footer -->
      <tr>
        <td style="background:#f8f9ff;border-top:1px solid #e8ecf8;padding:20px 40px;text-align:center;">
          <p style="margin:0;color:#aaa;font-size:12px;line-height:1.6;">
            This is a private interview link — please do not share it.<br>
            © {datetime.utcnow().year} {company_name}. All rights reserved.
          </p>
        </td>
      </tr>

    </table>
  </td></tr>
  </table>
</body>
</html>"""


def _render_text(
    applicant_name:   str,
    role:             str,
    meeting_url:      str,
    scheduled_at:     datetime,
    interviewer_name: str,
    company_name:     str,
) -> str:
    formatted_time = _format_datetime(scheduled_at)
    return f"""Hi {applicant_name},

Congratulations — you're invited to interview for the {role} role at {company_name}!

INTERVIEW DETAILS
─────────────────
Date & Time  : {formatted_time}
Role         : {role}
Interviewer  : {interviewer_name}
Format       : Video Interview (3 rounds · ~45 minutes)

JOIN YOUR INTERVIEW
───────────────────
{meeting_url}

Click the link above at your scheduled time to join. This link is private — please do not share it.

BEFORE YOU JOIN
───────────────
• Test your camera and microphone
• Use Chrome or Firefox for best experience
• Find a quiet, well-lit space
• Have your resume and portfolio ready
• Join 2–3 minutes early

Questions? Reply to this email — we're happy to help.

We look forward to meeting you!

— {interviewer_name}
  {company_name} Talent Team
  {os.getenv('INTERVIEW_FROM_EMAIL', 'talent@hireiq.com')}
"""


# ─────────────────────────────────────────────────────
#  Email Service
# ─────────────────────────────────────────────────────

class EmailService:
    """
    Async SMTP email sender for interview invitations.

    Uses Python's stdlib smtplib wrapped in asyncio.to_thread so
    the event loop is never blocked during SMTP handshake / send.

    Supports Gmail App Password, Outlook, or any SMTP relay.
    Falls back to logging (dev mode) when SMTP is not configured.
    """

    def __init__(self, config: EmailConfig) -> None:
        self.config = config

    @classmethod
    def from_env(cls) -> "EmailService":
        return cls(EmailConfig.from_env())

    async def send_interview_invite(
        self,
        applicant_name:   str,
        applicant_email:  str,
        role:             str,
        meeting_url:      str,
        scheduled_at:     datetime,
        interviewer_name: str = "Sarah Mitchell",
        company_name:     str = "HireIQ Technologies",
    ) -> bool:
        """
        Send an interview invitation email to a candidate.

        Returns True if the email was sent (or logged in dev mode).
        Returns False and logs an error on failure.

        Args:
            applicant_name:   Candidate's full name
            applicant_email:  Candidate's email (from their resume/application)
            role:             Human-readable role name, e.g. "Backend Engineer"
            meeting_url:      Unique Jitsi meeting URL for this candidate
            scheduled_at:     Scheduled interview datetime (UTC)
            interviewer_name: Persona name shown in the email
            company_name:     Company name in the email header + footer
        """
        subject = f"Your Interview with {company_name} — {role}"
        html    = _render_html(applicant_name, role, meeting_url, scheduled_at, interviewer_name, company_name)
        text    = _render_text(applicant_name, role, meeting_url, scheduled_at, interviewer_name, company_name)

        if not self.config.configured:
            logger.warning(
                f"EMAIL | SMTP not configured — logging invite instead of sending | "
                f"to={applicant_email} | url={meeting_url}"
            )
            logger.info(f"EMAIL [DEV] | Subject: {subject}")
            logger.info(f"EMAIL [DEV] | Meeting URL: {meeting_url}")
            logger.info(f"EMAIL [DEV] | Scheduled: {_format_datetime(scheduled_at)}")
            return True   # treat as success in dev

        try:
            await asyncio.to_thread(
                self._send_smtp,
                to_email = applicant_email,
                to_name  = applicant_name,
                subject  = subject,
                html     = html,
                text     = text,
            )
            logger.info(
                f"EMAIL | Invite sent | "
                f"to={applicant_email} | role={role} | url={meeting_url}"
            )
            return True
        except Exception as e:
            logger.error(
                f"EMAIL | Send failed | to={applicant_email} | {e}"
            )
            return False

    def _send_smtp(
        self,
        to_email: str,
        to_name:  str,
        subject:  str,
        html:     str,
        text:     str,
    ) -> None:
        """Blocking SMTP send — always call via asyncio.to_thread."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{self.config.from_name} <{self.config.from_email}>"
        msg["To"]      = f"{to_name} <{to_email}>"
        msg["Reply-To"] = self.config.from_email

        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html",  "utf-8"))

        ctx = ssl.create_default_context()
        with smtplib.SMTP(self.config.host, self.config.port) as server:
            if self.config.use_tls:
                server.starttls(context=ctx)
            server.login(self.config.user, self.config.password)
            server.sendmail(
                from_addr = self.config.from_email,
                to_addrs  = [to_email],
                msg       = msg.as_string(),
            )


# ─────────────────────────────────────────────────────
#  Module-level singleton
# ─────────────────────────────────────────────────────

def build_email_service() -> EmailService:
    """Convenience factory used by AvatarInterviewOrchestrator (Phase 5)."""
    return EmailService.from_env()
