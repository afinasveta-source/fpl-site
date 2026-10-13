from fastapi import HTTPException
from .security import Busy, new_token, token_hash, password_hasher, verify_password
from .mail import make_mail


def require_admin(conn, actor):
    """Serialize a privileged write against account suspension and role removal."""
    row = conn.execute("SELECT id FROM users WHERE id=%s AND account_status='active' AND deleted_at IS NULL FOR UPDATE", (actor['id'],)).fetchone()
    if not row or not conn.execute("SELECT 1 FROM user_roles WHERE user_id=%s AND role='admin'", (actor['id'],)).fetchone():
        raise HTTPException(403, 'Administrator role required')


def user_view(conn, user):
    return {k: user[k] for k in ('id', 'email', 'display_name', 'full_name', 'city', 'country_code', 'account_status')} | {
        'roles': [r['role'] for r in conn.execute('SELECT role FROM user_roles WHERE user_id=%s ORDER BY role', (user['id'],))]
    }


class AuthService:
    def __init__(self, db, settings, mailer):
        self.db, self.settings, self.mailer = db, settings, mailer

    def throttle(self, action, ip, email=None, limit=None, by_ip=True, window=None):
        s = self.settings
        window = window or s.rate_window_seconds
        if limit is None:
            limit = s.login_limit if action == 'login' else s.reset_limit
        # Вход: на один email — login_limit попыток, на один адрес — login_ip_limit. Участницы с мобильного интернета часто
        # выходят в сеть с одного общего адреса оператора, и общий лимит 20 на адрес отказал бы им во входе после рассылки.
        ip_limit = max(limit, s.login_ip_limit) if action == 'login' else limit
        keys = [(token_hash(f'{action}:ip:{ip}'), ip_limit)] if by_ip else []
        if email:
            keys.append((token_hash(f'{action}:email:{email}'), limit))
        # Independent transaction: failed authentication must still consume its quota.
        exceeded = False
        with self.db.transaction() as conn:
            for key, key_limit in sorted(keys):
                row = conn.execute('''
INSERT INTO auth_rate_limits(key_hash, window_start, attempts) VALUES (%s, now(), 1)
ON CONFLICT (key_hash) DO UPDATE SET
    attempts = CASE WHEN auth_rate_limits.window_start <= now() - make_interval(secs => %s)
                    THEN 1 ELSE auth_rate_limits.attempts + 1 END,
    window_start = CASE WHEN auth_rate_limits.window_start <= now() - make_interval(secs => %s)
                       THEN now() ELSE auth_rate_limits.window_start END
RETURNING attempts''', (key, window, window)).fetchone()
                exceeded = exceeded or row['attempts'] > key_limit
        if exceeded:
            raise HTTPException(429, 'Too many requests', headers={'Retry-After': str(window)})

    def unthrottle(self, action, ip, email=None):
        keys = [token_hash(f'{action}:ip:{ip}')] + ([token_hash(f'{action}:email:{email}')] if email else [])
        with self.db.transaction() as conn:
            for key in sorted(keys):
                conn.execute('DELETE FROM auth_rate_limits WHERE key_hash=%s AND attempts<=1', (key,))   # счётчик не бывает 0
                conn.execute('UPDATE auth_rate_limits SET attempts=attempts-1 WHERE key_hash=%s AND attempts>1', (key,))

    def current_user(self, raw):
        with self.db.transaction() as conn:
            user = conn.execute('''SELECT u.* FROM auth_sessions a JOIN users u ON u.id=a.user_id
WHERE a.token_hash=%s AND a.revoked_at IS NULL AND a.expires_at>now()
AND u.account_status='active' AND u.deleted_at IS NULL AND u.email_verified_at IS NOT NULL''', (token_hash(raw),)).fetchone()
            if not user:
                raise HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Bearer'})
            return user_view(conn, user)

    def login(self, email, password, ip):
        self.throttle('login', ip, email)
        # Пароль проверяется вне транзакции: проверка может подождать очереди (см. BoundedHasher), соединение с базой
        # в это время не занято. Потом — под блокировкой: аккаунт ещё активен и пароль тот же, что проверяли.
        with self.db.transaction() as conn:
            user = conn.execute('SELECT * FROM users WHERE lower(email)=%s', (email,)).fetchone()
        try:
            valid = verify_password(password, user['password_hash'] if user else None)
        except Busy:
            # «занято» — пароль не проверялся: попытка не в счёт (иначе повторы после рассылки упирались бы в лимит)
            self.unthrottle('login', ip, email)
            raise
        with self.db.transaction() as conn:
            if user:
                fresh = conn.execute('SELECT * FROM users WHERE id=%s FOR UPDATE', (user['id'],)).fetchone()
                if fresh['password_hash'] != user['password_hash']:
                    valid = False
                user = fresh
            if not user or not valid or user['account_status'] != 'active' or user['deleted_at'] or not user['email_verified_at']:
                raise HTTPException(401, 'Invalid credentials', headers={'WWW-Authenticate': 'Bearer'})
            raw = new_token()
            conn.execute('''INSERT INTO auth_sessions(user_id, token_hash, expires_at)
VALUES (%s, %s, now() + make_interval(hours => %s))''', (user['id'], token_hash(raw), self.settings.session_hours))
        return {'access_token': raw, 'token_type': 'bearer', 'expires_in': self.settings.session_hours * 3600}

    def logout(self, raw):
        with self.db.transaction() as conn:
            conn.execute('UPDATE auth_sessions SET revoked_at=now() WHERE token_hash=%s AND revoked_at IS NULL', (token_hash(raw),))

    def issue_token(self, user_id, kind, email=None, actor=None):
        raw = new_token()
        with self.db.transaction() as conn:
            if actor is not None:
                require_admin(conn, actor)
            user = conn.execute('SELECT * FROM users WHERE id=%s FOR UPDATE', (user_id,)).fetchone()
            allowed = 'imported' if kind == 'set_password' else 'active'
            if not user or user['account_status'] != allowed or user['deleted_at']:
                raise HTTPException(400, 'Account is not eligible')
            target = email if kind == 'set_password' else user['email']
            if kind == 'set_password':
                # Never change a pre-linked legacy email without proving ownership of it.
                if user['email'] and user['email'].lower() != target:
                    raise HTTPException(409, 'Account already has a different email')
                other = conn.execute('SELECT id FROM users WHERE lower(email)=%s AND id<>%s', (target, user_id)).fetchone()
                if other:
                    raise HTTPException(409, 'Email unavailable')
            conn.execute('UPDATE auth_tokens SET used_at=now() WHERE user_id=%s AND token_type=%s AND used_at IS NULL', (user_id, kind))
            conn.execute('''INSERT INTO auth_tokens(user_id, token_hash, token_type, target_email, expires_at)
VALUES (%s,%s,%s,%s,now()+make_interval(mins => %s))''', (user_id, token_hash(raw), kind, target, self.settings.token_minutes))
        try:
            self.mailer.send(make_mail(self.settings, target, kind, raw))
        except Exception:
            # Never leave a token usable after the delivery path reported failure.
            with self.db.transaction() as conn:
                conn.execute('UPDATE auth_tokens SET used_at=now() WHERE token_hash=%s', (token_hash(raw),))
            raise HTTPException(503, 'Email delivery unavailable') from None

    def request_reset(self, email):
        with self.db.transaction() as conn:
            user = conn.execute("SELECT id FROM users WHERE lower(email)=%s AND account_status='active' AND email_verified_at IS NOT NULL AND deleted_at IS NULL", (email,)).fetchone()
        if user:
            try:
                self.issue_token(user['id'], 'reset_password')
            except HTTPException as exc:
                if exc.status_code not in (400, 503):
                    raise
                # Same response for absent/inactive users and delivery failures.
                if exc.status_code == 503:
                    with self.db.transaction() as conn:
                        conn.execute("INSERT INTO system_errors(severity,component,error_code,message) VALUES ('error','auth','MAIL_DELIVERY_FAILED','Password reset email delivery failed')")

    def consume_token(self, raw, password, kind):
        encoded = password_hasher.hash(password)
        digest = token_hash(raw)
        with self.db.transaction() as conn:
            owner = conn.execute('SELECT user_id FROM auth_tokens WHERE token_hash=%s AND token_type=%s', (digest, kind)).fetchone()
            if not owner:
                raise HTTPException(400, 'Invalid or expired token')
            # All issue/consume paths lock user first, serializing reissue and consumption.
            user = conn.execute('SELECT * FROM users WHERE id=%s FOR UPDATE', (owner['user_id'],)).fetchone()
            token = conn.execute('''SELECT * FROM auth_tokens WHERE token_hash=%s AND token_type=%s
AND used_at IS NULL AND expires_at>clock_timestamp() FOR UPDATE''', (digest, kind)).fetchone()
            allowed = 'imported' if kind == 'set_password' else 'active'
            if not token or user['account_status'] != allowed or user['deleted_at']:
                raise HTTPException(400, 'Invalid or expired token')
            if kind == 'set_password':
                # Email is bound to the delivered token, never supplied at consumption.
                conn.execute("UPDATE users SET email=%s, password_hash=%s, email_verified_at=now(), account_status='active' WHERE id=%s", (token['target_email'], encoded, user['id']))
            else:
                if token['target_email'] != user['email']:
                    raise HTTPException(400, 'Invalid or expired token')
                conn.execute('UPDATE users SET password_hash=%s WHERE id=%s', (encoded, user['id']))
            conn.execute('UPDATE auth_tokens SET used_at=now() WHERE user_id=%s AND used_at IS NULL', (user['id'],))
            conn.execute('UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL', (user['id'],))
            conn.execute("INSERT INTO audit_log(actor_user_id,entity_type,entity_id,action) VALUES (%s,'user',%s,%s)", (user['id'], user['id'], kind))

    # ---------- Приглашение: человек сам указывает email и пароль (этап 3) ----------

    def _invite(self, conn, raw, lock):
        digest = token_hash(raw)
        owner = conn.execute("SELECT user_id FROM auth_tokens WHERE token_hash=%s AND token_type='invite'", (digest,)).fetchone()
        if not owner:
            raise HTTPException(400, 'Invalid or expired token')
        user = conn.execute('SELECT * FROM users WHERE id=%s' + (' FOR UPDATE' if lock else ''), (owner['user_id'],)).fetchone()
        token = conn.execute("""SELECT * FROM auth_tokens WHERE token_hash=%s AND token_type='invite'
AND used_at IS NULL AND expires_at>clock_timestamp()""" + (' FOR UPDATE' if lock else ''), (digest,)).fetchone()
        if not token or user['account_status'] != 'imported' or user['deleted_at']:
            raise HTTPException(400, 'Invalid or expired token')
        return user

    def check_invite(self, raw):
        with self.db.transaction() as conn:
            user = self._invite(conn, raw, lock=False)
            name = (user['display_name'] or user['full_name'] or '').split(' ')[0] or None
            return {'name': name, 'email': user['email']}

    def consume_invite(self, raw, email, password):
        encoded = password_hasher.hash(password)
        with self.db.transaction() as conn:
            user = self._invite(conn, raw, lock=True)
            if user['email'] and user['email'].lower() != email:
                raise HTTPException(409, 'email_preset')
            if conn.execute('SELECT 1 FROM users WHERE lower(email)=%s AND id<>%s', (email, user['id'])).fetchone():
                raise HTTPException(409, 'email_taken')
            # Ссылку передал организатор лично (писем пока нет), поэтому email считается подтверждённым ею.
            conn.execute("""UPDATE users SET email=%s, password_hash=%s, email_verified_at=now(), account_status='active'
WHERE id=%s""", (email, encoded, user['id']))
            conn.execute('UPDATE auth_tokens SET used_at=now() WHERE user_id=%s AND used_at IS NULL', (user['id'],))
            conn.execute('UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL', (user['id'],))
            conn.execute("INSERT INTO audit_log(actor_user_id,entity_type,entity_id,action) VALUES (%s,'user',%s,'invite_accepted')",
                         (user['id'], user['id']))
