from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

class Base(DeclarativeBase):
    pass

def get_engine():
    return create_engine("sqlite:///./autovc.db", echo=False)

def get_session_factory():
    engine = get_engine()
    return sessionmaker(bind=engine)

def init_db():
    engine = get_engine()
    Base.metadata.create_all(engine)
