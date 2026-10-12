import pytest
from pydantic import ValidationError
from kabinet.config import Settings
from kabinet.main import create_app
from kabinet.auth.mail import MemoryMailer


def test_test_requires_explicit_test_database():
    with pytest.raises(ValidationError):
        Settings(environment='TEST',database_dsn='postgresql://localhost/fpl_prod',_env_file=None)


@pytest.mark.parametrize('overrides', [
    {'mail_mode':'memory'}, {'frontend_url':'http://app.example.org'},
    {'database_dsn':'postgresql://localhost/fpl_test?sslmode=verify-full'},
    {'database_dsn':'postgresql://db.example.org/fpl_prod?sslmode=require'},
    {'root_path':'/kabinet/'},
])
def test_prod_guardrails(overrides):
    values=dict(environment='PROD',database_dsn='postgresql://db.example.org/fpl_prod?sslmode=verify-full',
                mail_mode='smtp',smtp_host='smtp.example.org',mail_from='noreply@example.org',frontend_url='https://app.example.org')
    values.update(overrides)
    with pytest.raises(ValidationError):
        Settings(**values,_env_file=None)


def test_prod_cannot_inject_test_mailer():
    settings=Settings(environment='PROD',database_dsn='postgresql://db.example.org/fpl_prod?sslmode=verify-full',
                      mail_mode='smtp',smtp_host='smtp.example.org',mail_from='noreply@example.org',frontend_url='https://app.example.org',_env_file=None)
    with pytest.raises(ValueError):
        create_app(settings,MemoryMailer())


def test_positive_ttl_and_limits():
    with pytest.raises(ValidationError):
        Settings(environment='TEST',database_dsn='postgresql://localhost/fpl_test',token_minutes=0,_env_file=None)


def test_smtp_requires_config_in_test_too():
    with pytest.raises(ValidationError):
        Settings(environment='TEST',database_dsn='postgresql://localhost/fpl_test',mail_mode='smtp',_env_file=None)


def test_prod_on_same_server_without_mail():
    """Сервер FPL: база на 127.0.0.1, письма пока не настроены — так можно."""
    s=Settings(environment='PROD',database_dsn='postgresql://fpl_kabinet:x@127.0.0.1:5432/fpl',mail_mode='disabled',
               frontend_url='https://facepaintingleague.com/kabinet',root_path='/kabinet',_env_file=None)
    assert s.mail_mode=='disabled'


def test_setup_key_must_be_sha256():
    with pytest.raises(ValidationError):
        Settings(environment='TEST',database_dsn='postgresql://localhost/fpl_test',setup_key_sha256='plain-key',_env_file=None)
