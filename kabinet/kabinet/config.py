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
    session_hours: int = 12
    token_minutes: int = 30
    login_limit: int = 20
    reset_limit: int = 5
    rate_window_seconds: int = 900
    # sha256 ключа сервера (ключ приёмника данных); нужен один раз — создать первого администратора.
    setup_key_sha256: str | None = None
    # Фото работ: папка на сервере (не отдаётся сайтом), лимит загрузок, запас свободного места.
    media_dir: str = '/var/lib/fpl/kabinet-media'
    upload_max_mb: int = Field(default=20, ge=1, le=50)
    upload_limit: int = 60
    media_min_free_mb: int = 1024

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
