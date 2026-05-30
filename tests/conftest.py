import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from autovc.database import Base
from autovc.models import Potential, VerificationJob, VerificationResult

# Only create v1/v2 ORM tables for testing (not ReferenceValue which needs PG)
_TEST_TABLES = [Potential, VerificationJob, VerificationResult]


@pytest.fixture(scope="session")
def engine():
    return create_engine("sqlite:///:memory:")


@pytest.fixture(scope="session", autouse=True)
def tables(engine):
    for table in _TEST_TABLES:
        table.__table__.create(engine, checkfirst=True)
    yield
    for table in reversed(_TEST_TABLES):
        table.__table__.drop(engine, checkfirst=True)


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
