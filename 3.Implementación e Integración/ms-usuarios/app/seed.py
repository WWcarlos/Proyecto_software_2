"""Datos iniciales: permisos, roles y un usuario administrador para poder iniciar sesión."""
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Permiso, Rol, Usuario
from .security import hash_password

PERMISOS = {
    "usuarios.gestionar": "Administrar usuarios, roles y permisos",
    "compras.ordenes.gestionar": "Crear, emitir y cancelar órdenes de compra",
    "compras.recepciones.registrar": "Registrar recepciones de mercancía",
    "inventarios.movimientos.crear": "Registrar movimientos de inventario",
    "inventarios.bodegas.gestionar": "Crear y modificar bodegas y stock mínimo",
    "productos.gestionar": "Crear, modificar y dar de baja productos y categorías",
    "proveedores.gestionar": "Registrar, modificar y desactivar proveedores",
    "logistica.gestionar": "Registrar clientes, paquetes, envíos e insumos",
}

ROLES = {
    "ADMIN": ("Administrador del sistema", list(PERMISOS)),
    "BODEGUERO": (
        "Operador de bodega",
        ["compras.recepciones.registrar", "inventarios.movimientos.crear", "logistica.gestionar"],
    ),
}


def sembrar(db: Session) -> None:
    permisos: dict[str, Permiso] = {}
    for codigo, descripcion in PERMISOS.items():
        permiso = db.scalar(select(Permiso).where(Permiso.codigo == codigo))
        if permiso is None:
            permiso = Permiso(codigo=codigo, descripcion=descripcion)
            db.add(permiso)
        permisos[codigo] = permiso
    db.flush()

    roles: dict[str, Rol] = {}
    for nombre, (descripcion, codigos) in ROLES.items():
        rol = db.scalar(select(Rol).where(Rol.nombre == nombre))
        if rol is None:
            rol = Rol(nombre=nombre, descripcion=descripcion, permisos=[permisos[c] for c in codigos])
            db.add(rol)
        else:
            # Si el rol ya existía, se le agregan los permisos nuevos (no se quita ninguno).
            for codigo in codigos:
                if permisos[codigo] not in rol.permisos:
                    rol.permisos.append(permisos[codigo])
        roles[nombre] = rol
    db.flush()

    email = os.getenv("ADMIN_EMAIL", "admin@inventarios.com").lower()
    password = os.getenv("ADMIN_PASSWORD")
    if password and db.scalar(select(Usuario).where(Usuario.email == email)) is None:
        db.add(
            Usuario(
                nombre="Administrador",
                email=email,
                password_hash=hash_password(password),
                roles=[roles["ADMIN"]],
            )
        )
    db.commit()
