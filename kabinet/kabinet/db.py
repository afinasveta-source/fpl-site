from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row


class Database:
    def __init__(self, settings):
        self.dsn = settings.database_dsn.get_secret_value()

    @contextmanager
    def transaction(self):
        # Connection context commits on success and rolls back on any exception.
        with psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5) as conn:
            yield conn
