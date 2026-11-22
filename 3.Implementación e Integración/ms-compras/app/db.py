import os
import time

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker

engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True, pool_recycle=1800)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
# Una sesión por hilo; main.py la cierra al terminar cada petición.
Session = scoped_session(SessionLocal)


class Base(DeclarativeBase):
    pass


def esperar_bd(intentos: int = 30, pausa: float = 2.0) -> None:
    for _ in range(intentos):
        try:
            with engine.connect() as conexion:
                conexion.execute(text("SELECT 1"))
            return
        except Exception:
            time.sleep(pausa)
    raise RuntimeError("No fue posible conectar con la base de datos")
