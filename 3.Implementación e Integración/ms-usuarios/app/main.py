import logging
import os
from datetime import datetime, timedelta, timezone

import jwt
from flask import Flask, jsonify, request, send_from_directory
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from . import models, schemas, security
from .db import Base, Session, SessionLocal, engine, esperar_bd
from .errores import ErrorApi, registrar_manejadores, salida, validar_cuerpo
from .seed import sembrar

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("usuarios")

# Minutos de validez del código de recuperación de contraseña.
RECUPERACION_MINUTOS = int(os.getenv("RECUPERACION_MINUTOS", "15"))

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
    if claims.get("jti") and Session.get(models.TokenRevocado, claims["jti"]) is not None:
        raise ErrorApi(401, "TOKEN_REVOCADO", "La sesión fue cerrada")
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


# ---------- documentación OpenAPI / Swagger ----------
@app.get("/openapi.yaml")
def openapi_spec():
    # El contrato está en la carpeta del servicio, junto a app/ (igual que en los otros microservicios).
    return send_from_directory(os.path.dirname(app.root_path), "usuarios.yaml", mimetype="text/yaml")


@app.get("/docs")
def swagger_ui():
    # URL relativa: funciona tanto en /docs como detrás del gateway en /usuarios/docs
    return """<!DOCTYPE html>
<html>
<head>
  <title>API Usuarios - Swagger</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>SwaggerUIBundle({ url: 'openapi.yaml', dom_id: '#swagger-ui' });</script>
</body>
</html>""", 200, {"Content-Type": "text/html"}


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


@app.post("/auth/logout")
def logout():
    """Cerrar sesión: el token actual queda revocado (el Gateway lo rechaza desde ese momento)."""
    usuario, claims = usuario_actual()
    if claims.get("jti"):
        Session.merge(
            models.TokenRevocado(
                jti=claims["jti"],
                usuario_id=usuario.id,
                expira_en=datetime.fromtimestamp(claims["exp"], tz=timezone.utc).replace(tzinfo=None),
            )
        )
        Session.commit()
    return salida(schemas.MensajeOut(mensaje="Sesión cerrada"))


@app.put("/auth/password")
def cambiar_password():
    """Cambiar la contraseña del usuario autenticado (exige la contraseña actual)."""
    usuario, _ = usuario_actual()
    datos = validar_cuerpo(schemas.CambioPasswordIn)
    if not security.verificar_password(datos.password_actual, usuario.password_hash):
        raise ErrorApi(401, "CREDENCIALES_INVALIDAS", "La contraseña actual no es correcta")
    usuario.password_hash = security.hash_password(datos.password_nueva)
    Session.commit()
    return salida(schemas.MensajeOut(mensaje="Contraseña actualizada"))


MENSAJE_RECUPERACION = "Si el correo está registrado, se envió un código para restablecer la contraseña"


@app.post("/auth/recuperar")
def recuperar_password():
    """Solicitar un código de recuperación. La respuesta es la misma exista o no el correo.

    No hay servidor de correo: el envío se simula escribiendo el código en el log del servicio
    (docker compose logs usuarios).
    """
    datos = validar_cuerpo(schemas.RecuperarIn)
    usuario = Session.scalar(select(models.Usuario).where(models.Usuario.email == datos.email.lower()))
    if usuario is not None and usuario.activo:
        # Los códigos anteriores que no se usaron dejan de servir.
        for anterior in Session.scalars(
            select(models.RecuperacionPassword).where(
                models.RecuperacionPassword.usuario_id == usuario.id,
                models.RecuperacionPassword.usado.is_(False),
            )
        ):
            anterior.usado = True
        codigo = security.generar_codigo_recuperacion()
        Session.add(
            models.RecuperacionPassword(
                usuario_id=usuario.id,
                codigo_hash=security.hash_codigo(codigo),
                expira_en=models.ahora() + timedelta(minutes=RECUPERACION_MINUTOS),
            )
        )
        Session.commit()
        log.info("[CORREO SIMULADO] Para %s: código de recuperación %s (válido %s min)",
                 usuario.email, codigo, RECUPERACION_MINUTOS)
    return salida(schemas.MensajeOut(mensaje=MENSAJE_RECUPERACION))


@app.post("/auth/restablecer")
def restablecer_password():
    """Restablecer la contraseña con el código recibido. El código sirve una sola vez."""
    datos = validar_cuerpo(schemas.RestablecerIn)
    usuario = Session.scalar(select(models.Usuario).where(models.Usuario.email == datos.email.lower()))
    recuperacion = None
    if usuario is not None and usuario.activo:
        recuperacion = Session.scalar(
            select(models.RecuperacionPassword).where(
                models.RecuperacionPassword.usuario_id == usuario.id,
                models.RecuperacionPassword.codigo_hash == security.hash_codigo(datos.codigo),
                models.RecuperacionPassword.usado.is_(False),
                models.RecuperacionPassword.expira_en > models.ahora(),
            )
        )
    if recuperacion is None:
        raise ErrorApi(400, "CODIGO_INVALIDO", "El código no es válido o ya expiró")
    recuperacion.usado = True
    usuario.password_hash = security.hash_password(datos.password_nueva)
    Session.commit()
    return salida(schemas.MensajeOut(mensaje="Contraseña restablecida"))


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
