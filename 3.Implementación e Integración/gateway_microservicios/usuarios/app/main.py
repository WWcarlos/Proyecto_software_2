from datetime import datetime, timezone

import jwt
from flask import Flask, jsonify, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from . import models, schemas, security
from .db import Base, Session, SessionLocal, engine, esperar_bd
from .errores import ErrorApi, registrar_manejadores, salida, validar_cuerpo
from .seed import sembrar

app = Flask(__name__)
app.json.ensure_ascii = False
app.json.sort_keys = False
registrar_manejadores(app)


@app.teardown_appcontext
def _cerrar_sesion(_):
    Session.remove()


def iniciar() -> None:
    """Equivalente al 'lifespan' de FastAPI: espera la BD, crea tablas y siembra datos."""
    esperar_bd()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        sembrar(db)


iniciar()


# ---------- utilidades ----------
def permisos_de(usuario: models.Usuario) -> list[str]:
    return sorted({p.codigo for rol in usuario.roles for p in rol.permisos})


def usuario_a_out(usuario: models.Usuario) -> schemas.UsuarioOut:
    return schemas.UsuarioOut(
        id=usuario.id,
        nombre=usuario.nombre,
        email=usuario.email,
        activo=usuario.activo,
        roles=sorted(r.nombre for r in usuario.roles),
        ultimo_acceso=usuario.ultimo_acceso,
    )


def usuario_actual():
    autorizacion = request.headers.get("Authorization", "")
    if autorizacion[:7].lower() != "bearer " or not autorizacion[7:].strip():
        raise ErrorApi(401, "NO_AUTENTICADO", "Token ausente")
    try:
        claims = security.decodificar_token(autorizacion[7:].strip())
        usuario_id = int(claims["sub"])
    except (jwt.PyJWTError, ValueError):
        raise ErrorApi(401, "TOKEN_INVALIDO", "Token inválido o expirado")
    usuario = Session.get(models.Usuario, usuario_id)
    if usuario is None or not usuario.activo:
        raise ErrorApi(401, "TOKEN_INVALIDO", "Token inválido o expirado")
    return usuario, claims


def requiere_gestion() -> models.Usuario:
    usuario, _ = usuario_actual()
    if "usuarios.gestionar" not in permisos_de(usuario):
        raise ErrorApi(403, "SIN_PERMISO", "Se requiere el permiso usuarios.gestionar")
    return usuario


def cargar_roles(ids: list[int]) -> list[models.Rol]:
    ids_unicos = set(ids)
    if not ids_unicos:
        return []
    roles = list(Session.scalars(select(models.Rol).where(models.Rol.id.in_(ids_unicos))))
    faltantes = sorted(ids_unicos - {r.id for r in roles})
    if faltantes:
        raise ErrorApi(404, "ROL_NO_ENCONTRADO", "Algún rol no existe", [{"roles_inexistentes": faltantes}])
    return roles


def obtener_usuario(usuario_id: int) -> models.Usuario:
    usuario = Session.get(models.Usuario, usuario_id)
    if usuario is None:
        raise ErrorApi(404, "USUARIO_NO_ENCONTRADO", "No existe")
    return usuario


@app.get("/health")
def health():
    return jsonify(estado="ok", servicio="usuarios")


# ---------- autenticación ----------
@app.post("/auth/login")
def login():
    """Iniciar sesión y obtener token JWT."""
    datos = validar_cuerpo(schemas.LoginIn)
    usuario = Session.scalar(select(models.Usuario).where(models.Usuario.email == datos.email.lower()))
    if (
        usuario is None
        or not usuario.activo
        or not security.verificar_password(datos.password, usuario.password_hash)
    ):
        raise ErrorApi(401, "CREDENCIALES_INVALIDAS", "Credenciales inválidas")
    usuario.ultimo_acceso = models.ahora()
    Session.commit()
    token = security.crear_token(usuario.id, usuario.email)
    return salida(schemas.TokenOut(access_token=token, expires_in=security.JWT_EXPIRA_SEGUNDOS))


@app.get("/auth/validar")
def validar():
    """Validar token (uso interno del Gateway)."""
    usuario, claims = usuario_actual()
    return salida(
        schemas.SesionOut(
            usuario_id=usuario.id,
            email=usuario.email,
            roles=sorted(r.nombre for r in usuario.roles),
            permisos=permisos_de(usuario),
            expira_en=datetime.fromtimestamp(claims["exp"], tz=timezone.utc),
        )
    )


# ---------- roles y permisos ----------
@app.get("/roles")
def listar_roles():
    requiere_gestion()
    roles = Session.scalars(select(models.Rol).order_by(models.Rol.id))
    return salida(
        [
            schemas.RolOut(
                id=r.id,
                nombre=r.nombre,
                descripcion=r.descripcion,
                permisos=sorted(p.codigo for p in r.permisos),
            )
            for r in roles
        ]
    )


@app.get("/permisos")
def listar_permisos():
    requiere_gestion()
    permisos = Session.scalars(select(models.Permiso).order_by(models.Permiso.id))
    return salida([schemas.PermisoOut(id=p.id, codigo=p.codigo, descripcion=p.descripcion) for p in permisos])


# ---------- usuarios ----------
@app.get("/")
def listar_usuarios():
    requiere_gestion()
    return salida([usuario_a_out(u) for u in Session.scalars(select(models.Usuario).order_by(models.Usuario.id))])


@app.post("/")
def crear_usuario():
    requiere_gestion()
    datos = validar_cuerpo(schemas.UsuarioNuevo)
    email = datos.email.lower()
    if Session.scalar(select(models.Usuario).where(models.Usuario.email == email)) is not None:
        raise ErrorApi(409, "EMAIL_DUPLICADO", "Email ya registrado")
    usuario = models.Usuario(
        nombre=datos.nombre,
        email=email,
        password_hash=security.hash_password(datos.password),
        roles=cargar_roles(datos.roles),
    )
    Session.add(usuario)
    try:
        Session.commit()
    except IntegrityError:
        Session.rollback()
        raise ErrorApi(409, "EMAIL_DUPLICADO", "Email ya registrado")
    return salida(usuario_a_out(usuario), 201)


@app.get("/<int:usuario_id>")
def obtener(usuario_id: int):
    requiere_gestion()
    return salida(usuario_a_out(obtener_usuario(usuario_id)))


@app.put("/<int:usuario_id>")
def actualizar(usuario_id: int):
    requiere_gestion()
    datos = validar_cuerpo(schemas.UsuarioActualizar)
    usuario = obtener_usuario(usuario_id)
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        if valor is not None:
            setattr(usuario, campo, valor)
    Session.commit()
    return salida(usuario_a_out(usuario))


@app.put("/<int:usuario_id>/roles")
def reemplazar_roles(usuario_id: int):
    requiere_gestion()
    datos = validar_cuerpo(schemas.RolesIn)
    usuario = obtener_usuario(usuario_id)
    usuario.roles = cargar_roles(datos.roles)
    Session.commit()
    return salida(usuario_a_out(usuario))
