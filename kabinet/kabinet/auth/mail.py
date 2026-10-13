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


TEXTS = {
    'reset_password': ('Face Painting League: новый пароль',
                       'Здравствуйте!\n\nВы запросили новый пароль для кабинета Face Painting League. Чтобы задать его, откройте ссылку:\n{link}\n\n'
                       'Ссылка действует ограниченное время. Если вы не запрашивали новый пароль, просто удалите это письмо — ваш пароль не изменится.\n\n'
                       'Face Painting League · facepaintingleague.com'),
    'set_password': ('Face Painting League: вход в кабинет',
                     'Здравствуйте!\n\nДля вас создан вход в кабинет Face Painting League. Чтобы задать пароль, откройте ссылку:\n{link}\n\n'
                     'Если вы не ждали это письмо, просто удалите его.\n\nFace Painting League · facepaintingleague.com'),
}


class SMTPMailer:
    def __init__(self, settings):
        self.settings = settings

    def send(self, mail: Mail):
        s = self.settings
        subject, body = TEXTS.get(mail.kind, TEXTS['reset_password'])
        message = EmailMessage()
        message['From'] = s.mail_from
        message['To'] = mail.recipient
        message['Subject'] = subject
        message.set_content(body.format(link=mail.link))
        ctx = ssl.create_default_context()
        if s.smtp_port == 465:          # Mail.ru / VK WorkSpace, Яндекс: SSL сразу
            client = smtplib.SMTP_SSL(s.smtp_host, 465, timeout=15, context=ctx)
        else:
            client = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15)
            client.starttls(context=ctx)
        with client:
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
