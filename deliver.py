"""Delivery: write the digest to disk, and (locally) email it.

Two delivery contexts share this code:
  - GitHub Actions: Python writes digest.html / digest.md; the workflow's
    send-mail action emails them. send_email() is NOT called there.
  - Local runs: send_email() pushes over Gmail SMTP if a password is present.

The dated digests/YYYY-MM-DD.md is always written — it's the committed archive.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path


def write_digest(markdown, html, date_str, digests_dir, root, has_content):
    """Always archive the dated .md. Write transient mail artifacts if content."""
    digests_dir = Path(digests_dir)
    digests_dir.mkdir(parents=True, exist_ok=True)
    dated = digests_dir / f"{date_str}.md"
    dated.write_text(markdown)

    html_path = md_path = None
    if has_content:
        html_path = Path(root) / "digest.html"
        md_path = Path(root) / "digest.md"
        html_path.write_text(html)
        md_path.write_text(markdown)

    return {"dated": dated, "html": html_path, "md": md_path}


def send_email(subject, html_body, attachment_path, to_addr):
    """Send the digest via SMTP (Gmail SSL by default). Returns True if sent."""
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = (os.environ.get("SMTP_USER")
            or os.environ.get("GMAIL_USER", "luis.goicouria@gmail.com"))
    password = os.environ.get("SMTP_PASS") or os.environ.get("GMAIL_APP_PASSWORD")
    if not password:
        print("  ! no GMAIL_APP_PASSWORD / SMTP_PASS set — wrote files but did "
              "not email")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content("This digest is HTML. See the attached .md if unrendered.")
    msg.add_alternative(html_body, subtype="html")
    if attachment_path and Path(attachment_path).exists():
        msg.add_attachment(
            Path(attachment_path).read_bytes(),
            maintype="text", subtype="markdown",
            filename=Path(attachment_path).name,
        )

    ctx = ssl.create_default_context()
    if port == 587:
        with smtplib.SMTP(host, port) as s:
            s.starttls(context=ctx)
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP_SSL(host, port, context=ctx) as s:
            s.login(user, password)
            s.send_message(msg)
    print(f"  emailed digest to {to_addr}")
    return True
