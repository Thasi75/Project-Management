from contextlib import contextmanager
from threading import RLock
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import DATA, ensure_dirs

ensure_dirs()
WRITE_LOCK = RLock()
engine = create_engine('sqlite:///' + (DATA / 'project.db').as_posix(), connect_args={'check_same_thread': False, 'timeout': 30})


@event.listens_for(engine, 'connect')
def setup_sqlite(connection, _):
    connection.execute('PRAGMA foreign_keys=ON')
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('PRAGMA busy_timeout=30000')


class Base(DeclarativeBase):
    pass


Session = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def transaction():
    with WRITE_LOCK, Session.begin() as session:
        yield session
