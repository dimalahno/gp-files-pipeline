from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config.config import Settings


def build_session_factory(settings: Settings) -> sessionmaker[Session]:
    engine = create_engine(settings.DB_URL, future=True, pool_pre_ping=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@contextmanager
def db_session(session_factory: sessionmaker[Session]):
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()