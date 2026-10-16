"""Настройки кабинета. TEST — только база с именем *_test; PROD — база на этом же сервере."""
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from psycopg.conninfo import conninfo_to_dict

LOCAL_HOSTS = {'127.0.0.1', 'localhost', '::1'}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='FPL_', env_file='.env', extra='ignore')
    environment: Literal['TEST', 'PROD']
    api_docs: bool = True          # /docs и /openapi.json в TEST; публичный тестовый кабинет их выключает
    database_dsn: SecretStr
    # disabled — письма не отправляются (сброс пароля — через организатора); memory — только для тестов.
    mail_mode: Literal['disabled', 'memory', 'smtp'] = 'memory'
    frontend_url: str = 'http://localhost:8100'
    root_path: str = ''
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    mail_from: str | None = None
    session_hours: int = 24 * 14   # вход держится две недели: меньше повторных входов у толпы после рассылки (робот на сервере, 13.10)
    token_minutes: int = 30
    # Ссылки, которые организатор отправляет сам (писем нет): приглашение — 7 дней, новый пароль — сутки.
    # Регистрация в кабинете самой участницей (решение 12.10). Email не подтверждается письмом — писем пока нет.
    signup_enabled: bool = True
    signup_limit: int = Field(default=5, ge=1, le=100)
    claim_limit: int = Field(default=10, ge=1, le=10000)   # заявок участниц из бота в час с одного адреса
    invite_days: int = Field(default=7, ge=1, le=30)
    reset_link_hours: int = Field(default=24, ge=1, le=168)
    login_limit: int = 20          # попыток входа на один email за окно
    login_ip_limit: int = 200      # попыток входа с одного адреса за окно (общий адрес мобильного оператора)
    reset_limit: int = 5
    rate_window_seconds: int = 900
    # sha256 ключа сервера (ключ приёмника данных); нужен один раз — создать первого администратора.
    setup_key_sha256: str | None = None
    # Фото работ: папка на сервере (не отдаётся сайтом), лимит загрузок, запас свободного места.
    media_dir: str = '/var/lib/fpl/kabinet-media'
    # Платный аудиоразбор от судьи (решение 13.10): заказ формой на сайте, оплата по ссылке организатора.
    review_enabled: bool = True
    review_reviewer: str = 'Милена'
    review_price_one: int = Field(default=300, ge=1)
    review_price_all: int = Field(default=700, ge=1)
    review_days: int = Field(default=3, ge=1, le=30)
    review_window_days: int = Field(default=30, ge=1, le=365)   # сколько дней после конца Игры открыт заказ
    upload_max_mb: int = Field(default=20, ge=1, le=50)
    upload_limit: int = 60
    media_min_free_mb: int = 1024
    # Уведомления в мессенджеры (16.10): бот лиги в Telegram и сообщество ВКонтакте. Нет токена — канал выключен.
    # Токены вводятся на закрытой странице сервера /admin/messengers.html и попадают сюда из /etc/fpl-kabinet.env.
    tg_token: SecretStr | None = None
    tg_username: str | None = None           # имя бота без @ — для ссылки t.me/<имя>?start=<код>
    tg_hook_path: SecretStr | None = None    # секретная часть адреса, на который Telegram присылает сообщения
    tg_hook_secret: SecretStr | None = None  # заголовок X-Telegram-Bot-Api-Secret-Token
    vk_token: SecretStr | None = None
    vk_group_id: int | None = None
    vk_secret: SecretStr | None = None       # секрет Callback API сообщества
    vk_confirmation: str | None = None       # строка подтверждения адреса Callback API
    messenger_worker: bool = True            # доставка в фоне (в тестах доставка вызывается вручную)
    # Пуш-уведомления (Web Push, 17.10): ключ VAPID создаёт сервер (fpl-kabinet-setup); нет файла — пуши выключены.
    push_key_file: str | None = None
    push_subject: str = 'https://facepaintingleague.com'
    # Лента данных для инструмента контента (16.10): запросов в минуту на ключ; как часто писать «последнее использование».
    feed_rate_limit: int = Field(default=120, ge=1, le=10000)
    feed_flush_seconds: int = Field(default=60, ge=0, le=3600)

    @model_validator(mode='after')
    def guard_environment(self):
        parts = conninfo_to_dict(self.database_dsn.get_secret_value())
        name = parts.get('dbname', '')
        if not name:
            raise ValueError('An explicit database name is required')
        if self.environment == 'TEST' and not name.endswith('_test'):
            raise ValueError('TEST database name must end with _test')
        if min(self.session_hours, self.token_minutes, self.login_limit,
               self.reset_limit, self.rate_window_seconds) <= 0:
            raise ValueError('TTL and rate limits must be positive')
        if self.mail_mode == 'smtp' and (not self.smtp_host or not self.mail_from):
            raise ValueError('SMTP mode requires smtp_host and mail_from')
        if self.root_path and (not self.root_path.startswith('/') or self.root_path.endswith('/')):
            raise ValueError('root_path must look like /kabinet')
        if self.setup_key_sha256 is not None and (len(self.setup_key_sha256) != 64
                                                  or any(c not in '0123456789abcdef' for c in self.setup_key_sha256)):
            raise ValueError('setup_key_sha256 must be a lowercase sha256 hex digest')
        if self.environment == 'PROD':
            if name.endswith('_test'):
                raise ValueError('PROD must not use a TEST database')
            host = parts.get('host') or ''
            # База — на этом же сервере (только 127.0.0.1); удалённая — только с проверкой сертификата.
            if host and host not in LOCAL_HOSTS and not host.startswith('/') and parts.get('sslmode') != 'verify-full':
                raise ValueError('A remote PROD database requires sslmode=verify-full')
            if self.mail_mode == 'memory':
                raise ValueError('PROD cannot keep mail in memory')
            url = urlsplit(self.frontend_url)
            if url.scheme != 'https' or not url.netloc or url.query or url.fragment:
                raise ValueError('PROD requires an HTTPS frontend URL without query/fragment')
        if bool(self.smtp_username) != bool(self.smtp_password):
            raise ValueError('SMTP username and password must be configured together')
        return self
