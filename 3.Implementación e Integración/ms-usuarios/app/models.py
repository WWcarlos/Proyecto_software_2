from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def ahora() -> datetime:
    # MySQL no guarda zona horaria: se almacena siempre UTC "ingenuo" y al responder se agrega la Z.
    return datetime.now(timezone.utc).replace(tzinfo=None)


usuario_rol = Table(
    "usuario_rol",
    Base.metadata,
    Column("usuario_id", ForeignKey("usuario.id", ondelete="CASCADE"), primary_key=True),
    Column("rol_id", ForeignKey("rol.id", ondelete="CASCADE"), primary_key=True),
)

rol_permiso = Table(
    "rol_permiso",
    Base.metadata,
    Column("rol_id", ForeignKey("rol.id", ondelete="CASCADE"), primary_key=True),
    Column("permiso_id", ForeignKey("permiso.id", ondelete="CASCADE"), primary_key=True),
)


class Permiso(Base):
    __tablename__ = "permiso"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(100), unique=True)
    descripcion: Mapped[str] = mapped_column(String(255), default="")


class Rol(Base):
    __tablename__ = "rol"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(50), unique=True)
    descripcion: Mapped[str] = mapped_column(String(255), default="")
    permisos: Mapped[list[Permiso]] = relationship(secondary=rol_permiso, lazy="selectin")


class Usuario(Base):
    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    ultimo_acceso: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    roles: Mapped[list[Rol]] = relationship(secondary=usuario_rol, lazy="selectin")


class TokenRevocado(Base):
    """Tokens cerrados con logout. Se rechazan hasta que expiren."""

    __tablename__ = "token_revocado"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    usuario_id: Mapped[int] = mapped_column(Integer, index=True)
    expira_en: Mapped[datetime] = mapped_column(DateTime)
    revocado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)


class RecuperacionPassword(Base):
    """Códigos temporales para restablecer la contraseña (se usan una sola vez)."""

    __tablename__ = "recuperacion_password"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id", ondelete="CASCADE"), index=True)
    codigo_hash: Mapped[str] = mapped_column(String(64))
    expira_en: Mapped[datetime] = mapped_column(DateTime)
    usado: Mapped[bool] = mapped_column(Boolean, default=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)
