from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session
from .config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}, pool_pre_ping=True)

class Base(DeclarativeBase):
    pass

def get_db():
    with Session(engine) as db:
        yield db
