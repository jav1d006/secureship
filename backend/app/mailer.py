"""Send the PDF report by e-mail through any SMTP server (optional feature)."""
import re
import smtplib
import ssl
from email.message import EmailMessage

from . import config

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24}$")


def enabled() -> bool:
    return bool(config.SMTP_HOST)


def send_report(to: str, filename: str, score: int, pdf: bytes) -> None:
    if not EMAIL_RE.match(to) or len(to) > 254:
        raise ValueError("invalid e-mail address")
    msg = EmailMessage()
    msg["From"], msg["To"] = config.SMTP_FROM, to
    msg["Subject"] = f"SecureShip report: score {score}/100"
    msg.set_content(f"Your SecureShip security report for {filename[:120]} is attached.\n\nScore: {score}/100\n\n"
                    "You received this because someone entered your address on a SecureShip instance. "
                    "If that was not you, ignore this message.")
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename="secureship-report.pdf")
    ctx = ssl.create_default_context()
    if config.SMTP_PORT == 465:
        smtp = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=15, context=ctx)
    else:
        smtp = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15)
    with smtp:
        if config.SMTP_PORT != 465:
            smtp.starttls(context=ctx)
        if config.SMTP_USER:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
        smtp.send_message(msg)
