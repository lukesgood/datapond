"""Transactional email delivery via Amazon SES.

Used by the password-reset ("forgot password") flow. Deliberately degrades
gracefully: if SES_FROM_EMAIL is unset or the send fails for any reason, we log
a warning and return False rather than raising — an install without SES wired up
(local dev, air-gapped, OSS on-prem) must still boot and run, and the auth flow
above this layer is written to not leak whether an email was actually sent.

Config:
- SES_FROM_EMAIL  — the verified SES sender identity ("From" address). Required
  for any mail to be sent; unset = feature disabled (no-op, returns False).
- AWS_REGION      — SES region (default us-east-1). boto3 default credential
  chain (instance profile / IRSA / env) — no static keys here.
"""
import logging
import os

logger = logging.getLogger(__name__)


def _from_email() -> str:
    return (os.getenv("SES_FROM_EMAIL") or "").strip()


def send_email(to: str, subject: str, body_text: str, body_html: str = None) -> bool:
    """Send one email via Amazon SES. Returns True on success, False otherwise.

    Never raises: a misconfigured or unavailable SES must not break the caller.
    Returns False (and logs a warning) when SES_FROM_EMAIL is unset or the send
    fails — the caller treats a False the same as a success for anti-enumeration.
    """
    sender = _from_email()
    if not sender:
        logger.warning(
            "[email] SES_FROM_EMAIL is not set — skipping email to %s (subject=%r). "
            "Set SES_FROM_EMAIL to a verified SES identity to enable delivery.",
            to, subject,
        )
        return False
    if not to:
        logger.warning("[email] no recipient address — skipping send")
        return False

    try:
        import boto3  # lazy — only when actually sending

        client = boto3.client("ses", region_name=os.getenv("AWS_REGION", "us-east-1"))

        body: dict = {"Text": {"Data": body_text, "Charset": "UTF-8"}}
        if body_html:
            body["Html"] = {"Data": body_html, "Charset": "UTF-8"}

        client.send_email(
            Source=sender,
            Destination={"ToAddresses": [to]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": body,
            },
        )
        logger.info("[email] sent %r to %s via SES", subject, to)
        return True
    except Exception as e:  # never propagate — email is best-effort
        logger.warning("[email] SES send to %s failed (non-fatal): %s", to, e)
        return False


def password_reset_email(reset_url: str):
    """Build the (subject, text, html) for a password-reset email.

    reset_url is the full one-time link the recipient clicks; it embeds the raw
    token as a query parameter and expires in 30 minutes.
    """
    subject = "Reset your DataPond password"

    text = (
        "We received a request to reset your DataPond password.\n\n"
        f"Use the link below to choose a new password:\n{reset_url}\n\n"
        "This link expires in 30 minutes and can be used only once.\n\n"
        "If you did not request a password reset, you can safely ignore this "
        "email — your password will not change.\n"
    )

    html = (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;'
        'margin:0 auto;color:#0f172a;">'
        '<h2 style="font-size:18px;margin-bottom:8px;">Reset your DataPond password</h2>'
        '<p style="font-size:14px;line-height:1.6;color:#334155;">'
        "We received a request to reset your DataPond password. "
        "Click the button below to choose a new one."
        "</p>"
        f'<p style="margin:24px 0;"><a href="{reset_url}" '
        'style="display:inline-block;background:#2563eb;color:#ffffff;'
        'text-decoration:none;padding:10px 18px;border-radius:8px;font-size:14px;'
        'font-weight:600;">Reset password</a></p>'
        '<p style="font-size:12px;line-height:1.6;color:#64748b;">'
        "This link expires in 30 minutes and can be used only once. "
        "If the button does not work, copy and paste this URL into your browser:"
        "</p>"
        f'<p style="font-size:12px;word-break:break-all;color:#2563eb;">{reset_url}</p>'
        '<p style="font-size:12px;line-height:1.6;color:#64748b;">'
        "If you did not request a password reset, you can safely ignore this "
        "email — your password will not change."
        "</p>"
        "</div>"
    )

    return subject, text, html
