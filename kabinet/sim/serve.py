"""Поднять кабинет на готовой базе симуляции (для проверки экранов): python -m sim.serve <база> <папка фото> <порт> <время ISO>."""
import sys
from datetime import datetime

import uvicorn
from psycopg.conninfo import make_conninfo

from sim.harness import Clock, MemoryMailer, create_app, settings_for
import os


def main():
    name, media, port, at = sys.argv[1], sys.argv[2], int(sys.argv[3]), datetime.fromisoformat(sys.argv[4])
    dsn = make_conninfo(os.environ['FPL_SIM_DSN'], dbname=name)
    app = create_app(settings_for(dsn, media), MemoryMailer(), clock=Clock(at))
    uvicorn.run(app, host='127.0.0.1', port=port, log_level='warning')


if __name__ == '__main__':
    main()
