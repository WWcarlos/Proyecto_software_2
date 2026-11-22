from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, PlainSerializer


def _iso_utc(valor: datetime) -> str:
    if valor.tzinfo is None:
        return valor.isoformat() + "Z"
    return valor.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


FechaUTC = Annotated[datetime, PlainSerializer(_iso_utc, return_type=str)]


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


class SesionOut(BaseModel):
    usuario_id: int
    email: str
    roles: list[str]
    permisos: list[str]
    expira_en: FechaUTC


class UsuarioOut(BaseModel):
    id: int
    nombre: str
    email: str
    activo: bool
    roles: list[str]
    ultimo_acceso: FechaUTC | None = None


class UsuarioNuevo(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    email: EmailStr
    password: str = Field(min_length=10)
    roles: list[int] = []


class UsuarioActualizar(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=150)
    activo: bool | None = None


class RolesIn(BaseModel):
    roles: list[int]


class RolOut(BaseModel):
    id: int
    nombre: str
    descripcion: str
    permisos: list[str]


class PermisoOut(BaseModel):
    id: int
    codigo: str
    descripcion: str
