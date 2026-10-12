import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from urllib.parse import urlencode


@dataclass(frozen=True)
class Mail:
    recipient: str
    kind: str
    token: str
    link: str


class MemoryMailer:
    """TEST-only mail sink. Never exposes tokens through HTTP or log output."""
    def __init__(self):
        self.messages: list[Mail] = []

    def send(self, mail: Mail):
        self.messages.append(mail)


class SMTPMailer:
    def __init__(self, settings):
        self.settings = settings

    def send(self, mail: Mail):
        s = self.settings
        message = EmailMessage()
        message['From'] = s.mail_from
        message['To'] = mail.recipient
        message['Subject'] = 'Face Painting League: установка пароля'
        message.set_content(f'Для установки пароля откройте ссылку:\n{mail.link}\n\nЕсли вы не запрашивали письмо, игнорируйте его.')
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as client:
            client.starttls(context=ssl.create_default_context())
            if s.smtp_username:
                client.login(s.smtp_username, s.smtp_password.get_secret_value())
            client.send_message(message)


def make_mail(settings, recipient, kind, raw):
    # Fragment keeps the token out of ordinary frontend access logs/referrers.
    return Mail(recipient, kind, raw, settings.frontend_url.rstrip('/') + '/auth/set-password#' + urlencode({'token': raw, 'type': kind}))


class DisabledMailer:
    """Письма не настроены: сброс пароля недоступен, токен не остаётся рабочим (см. AuthService.issue_token)."""
    def send(self, mail: Mail):
        raise OSError('Mail delivery is not configured')
