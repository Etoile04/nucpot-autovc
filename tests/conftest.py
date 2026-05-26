import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from autovc.database import Base


@pytest.fixture(scope="session")
def engine():
    return create_engine("sqlite:///:memory:")


@pytest.fixture(scope="session", autouse=True)
def tables(engine):
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db_session(engine):
    conn = engine.connect()
    txn = conn.begin()
    Session = sessionmaker(bind=conn)
    session = Session()
    yield session
    session.close()
    txn.rollback()
    conn.close()
