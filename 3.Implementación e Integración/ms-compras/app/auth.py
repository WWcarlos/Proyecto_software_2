"""Identidad del usuario. El Gateway valida el JWT y reenvía la identidad en cabeceras X-User-*."""
import os
from dataclasses import dataclass, field

from flask import request

from .errores import ErrorApi

# Token compartido entre servicios; Inventarios lo exige en X-Service-Token.
SERVICE_TOKEN = os.getenv("SERVICE_TOKEN", "")


def _lista(valor: str | None) -> list[str]:
    return [v for v in (valor or "").split(",") if v]


@dataclass
class Identidad:
    usuario_id: int
    email: str = ""
    roles: list[str] = field(default_factory=list)
    permisos: set[str] = field(default_factory=set)
    authorization: str | None = None

    def cabeceras_salida(self) -> dict[str, str]:
        """Cabeceras que se reenvían a otros microservicios para conservar la identidad."""
        cabeceras = {
            "X-User-Id": str(self.usuario_id),
            "X-Usuario-Id": str(self.usuario_id),  # nombre que usa Inventarios
            "X-User-Email": self.email,
            "X-User-Roles": ",".join(self.roles),
            "X-User-Permissions": ",".join(sorted(self.permisos)),
        }
        if self.authorization:
            cabeceras["Authorization"] = self.authorization
        if SERVICE_TOKEN:
            cabeceras["X-Service-Token"] = SERVICE_TOKEN
        return cabeceras


def obtener_identidad() -> Identidad:
    usuario_id = request.headers.get("X-User-Id", "")
    if not usuario_id.isdigit():
        raise ErrorApi(401, "NO_AUTENTICADO", "Solicitud sin identidad: las peticiones deben entrar por el API Gateway")
    return Identidad(
        usuario_id=int(usuario_id),
        email=request.headers.get("X-User-Email", ""),
        roles=_lista(request.headers.get("X-User-Roles")),
        permisos=set(_lista(request.headers.get("X-User-Permissions"))),
        authorization=request.headers.get("Authorization"),
    )


def requiere(permiso: str) -> Identidad:
    identidad = obtener_identidad()
    if permiso not in identidad.permisos:
        raise ErrorApi(403, "SIN_PERMISO", f"Se requiere el permiso {permiso}")
    return identidad
