"""Microservicio de Usuarios: autenticación (JWT), usuarios, roles y permisos. Flask + MySQL."""
import base64
import hashlib
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

import bcrypt
import jwt
from flask import Flask, Response, g, jsonify, request
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Table, create_engine, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from werkzeug.exceptions import HTTPException

# ======================================================================
# Errores (formato común: codigo, mensaje, detalles)
# ======================================================================
class ErrorApi(Exception):
    def __init__(self, status: int, codigo: str, mensaje: str, detalles: list | None = None):
        super().__init__(mensaje)
        self.status = status
        self.codigo = codigo
        self.mensaje = mensaje
        self.detalles = detalles or []


def respuesta_error(status: int, codigo: str, mensaje: str, detalles: list | None = None):
    respuesta = jsonify({"codigo": codigo, "mensaje": mensaje, "detalles": detalles or []})
    respuesta.status_code = status
    return respuesta


def registrar_manejadores(app: Flask) -> None:
    @app.errorhandler(ErrorApi)
    def _error_api(error: ErrorApi):
        return respuesta_error(error.status, error.codigo, error.mensaje, error.detalles)

    @app.errorhandler(HTTPException)
    def _http(error: HTTPException):
        return respuesta_error(error.code or 500, "ERROR_HTTP", error.description or error.name)

    @app.errorhandler(Exception)
    def _inesperado(_: Exception):
        app.logger.exception("Error no controlado")
        return respuesta_error(500, "ERROR_INTERNO", "Error interno del servidor")


# ======================================================================
# Base de datos (MySQL)
# ======================================================================
URL_BD = URL.create(
    "mysql+pymysql",
    username=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    host=os.environ["DB_HOST"],
    port=int(os.getenv("DB_PORT", "3306")),
    database=os.environ["DB_NAME"],
    query={"charset": "utf8mb4"},
)
engine = create_engine(URL_BD, pool_pre_ping=True, pool_recycle=1800)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """Una sesión por petición; se cierra (con rollback si no hubo commit) al terminar."""
    if "db" not in g:
        g.db = SessionLocal()
    return g.db


def cerrar_db(_error=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def esperar_bd(intentos: int = 30, pausa: float = 2.0) -> None:
    for _ in range(intentos):
        try:
            with engine.connect() as conexion:
                conexion.execute(text("SELECT 1"))
            return
        except Exception:
            time.sleep(pausa)
    raise RuntimeError("No fue posible conectar con la base de datos")


# ======================================================================
# Utilidades: fechas y validación de datos
# ======================================================================
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def ahora() -> datetime:
    return datetime.now(timezone.utc)


def iso(valor: datetime | None) -> str | None:
    """MySQL devuelve las fechas sin zona horaria; todas se guardan en UTC."""
    if valor is None:
        return None
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.isoformat()


def fallo(campo: str, mensaje: str):
    raise ErrorApi(422, "VALIDACION_FALLIDA", "Datos inválidos", [{"campo": campo, "error": mensaje}])


def cuerpo_json() -> dict:
    datos = request.get_json(force=True, silent=True)
    if not isinstance(datos, dict):
        fallo("cuerpo", "Se esperaba un objeto JSON")
    return datos


def _falta(datos: dict, campo: str, requerido: bool, prefijo: str) -> bool:
    if datos.get(campo) is None:
        if requerido:
            fallo(prefijo + campo, "Campo requerido")
        return True
    return False


def entero(datos, campo, minimo=None, requerido=True, prefijo=""):
    if _falta(datos, campo, requerido, prefijo):
        return None
    valor = datos[campo]
    if isinstance(valor, bool) or not isinstance(valor, int):
        fallo(prefijo + campo, "Debe ser un entero")
    if minimo is not None and valor < minimo:
        fallo(prefijo + campo, f"Debe ser mayor o igual a {minimo}")
    return valor


def numero_positivo(datos, campo, requerido=True, prefijo=""):
    if _falta(datos, campo, requerido, prefijo):
        return None
    valor = datos[campo]
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        fallo(prefijo + campo, "Debe ser un número")
    if valor <= 0:
        fallo(prefijo + campo, "Debe ser mayor que 0")
    return valor


def texto(datos, campo, minimo=1, maximo=None, requerido=True, prefijo=""):
    if _falta(datos, campo, requerido, prefijo):
        return None
    valor = datos[campo]
    if not isinstance(valor, str):
        fallo(prefijo + campo, "Debe ser texto")
    if len(valor) < minimo:
        fallo(prefijo + campo, f"Debe tener al menos {minimo} caracteres")
    if maximo is not None and len(valor) > maximo:
        fallo(prefijo + campo, f"Debe tener máximo {maximo} caracteres")
    return valor


def booleano(datos, campo, requerido=True, prefijo=""):
    if _falta(datos, campo, requerido, prefijo):
        return None
    if not isinstance(datos[campo], bool):
        fallo(prefijo + campo, "Debe ser verdadero o falso")
    return datos[campo]


def lista(datos, campo, minimo=0, requerido=True, prefijo=""):
    if _falta(datos, campo, requerido, prefijo):
        return []
    valor = datos[campo]
    if not isinstance(valor, list):
        fallo(prefijo + campo, "Debe ser una lista")
    if len(valor) < minimo:
        fallo(prefijo + campo, f"Debe tener al menos {minimo} elemento(s)")
    return valor


def lista_enteros(datos, campo, requerido=True):
    valores = lista(datos, campo, requerido=requerido)
    for i, v in enumerate(valores):
        if isinstance(v, bool) or not isinstance(v, int):
            fallo(f"{campo}.{i}", "Debe ser un entero")
    return valores


def email_valido(datos, campo="email"):
    valor = texto(datos, campo, 3, 255)
    if not EMAIL_RE.match(valor):
        fallo(campo, "Email inválido")
    return valor.strip().lower()


# ======================================================================
# Documentación Swagger (/docs) a partir de openapi.yaml
# ======================================================================
RUTA_YAML = Path(__file__).resolve().parent / "openapi.yaml"

HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>{titulo}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"></head>
<body><div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>window.ui = SwaggerUIBundle({{ url: "openapi.yaml", dom_id: "#swagger-ui" }});</script>
</body></html>"""


def registrar_docs(app: Flask, titulo: str) -> None:
    @app.get("/docs")
    def docs():
        return Response(HTML.format(titulo=titulo), mimetype="text/html")

    @app.get("/openapi.yaml")
    def openapi():
        return Response(RUTA_YAML.read_text(encoding="utf-8"), mimetype="application/yaml")


# ======================================================================
# Modelos
# ======================================================================
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
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    ultimo_acceso: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    roles: Mapped[list[Rol]] = relationship(secondary=usuario_rol, lazy="selectin")


# ======================================================================
# Seguridad: contraseñas y tokens JWT
# ======================================================================
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITMO = "HS256"
JWT_EXPIRA_SEGUNDOS = int(os.getenv("JWT_EXPIRES_SECONDS", "3600"))


def _prehash(password: str) -> bytes:
    # bcrypt solo admite 72 bytes; se normaliza la longitud con SHA-256 antes de aplicarlo.
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("utf-8")


def verificar_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("utf-8"))
    except ValueError:
        return False


def crear_token(usuario_id: int, email: str) -> str:
    emitido = ahora()
    claims = {
        "sub": str(usuario_id),
        "email": email,
        "iat": emitido,
        "exp": emitido + timedelta(seconds=JWT_EXPIRA_SEGUNDOS),
    }
    return jwt.encode(claims, JWT_SECRET, algorithm=JWT_ALGORITMO)


def decodificar_token(token: str) -> dict:
    """Lanza jwt.PyJWTError si el token es inválido o expiró."""
    return jwt.decode(
        token,
        JWT_SECRET,
        algorithms=[JWT_ALGORITMO],
        options={"require": ["exp", "sub"]},
    )


# ======================================================================
# Datos iniciales (permisos, roles y administrador)
# ======================================================================
PERMISOS = {
    "usuarios.gestionar": "Administrar usuarios, roles y permisos",
    "compras.ordenes.gestionar": "Crear, emitir y cancelar órdenes de compra",
    "compras.recepciones.registrar": "Registrar recepciones de mercancía",
    "inventarios.movimientos.crear": "Registrar movimientos de inventario",
}

ROLES = {
    "ADMIN": ("Administrador del sistema", list(PERMISOS)),
    "BODEGUERO": (
        "Operador de bodega",
        ["compras.recepciones.registrar", "inventarios.movimientos.crear"],
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
        elif nombre == "ADMIN":
            for codigo in codigos:
                if permisos[codigo] not in rol.permisos:
                    rol.permisos.append(permisos[codigo])
        roles[nombre] = rol
    db.flush()

    email = os.getenv("ADMIN_EMAIL", "admin@inventarios.local").lower()
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


# ======================================================================
# Aplicación y rutas
# ======================================================================
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.json.sort_keys = False
app.json.ensure_ascii = False
app.teardown_appcontext(cerrar_db)
registrar_manejadores(app)
registrar_docs(app, "API Usuarios")


# ---------- utilidades ----------
def permisos_de(usuario: Usuario) -> list[str]:
    return sorted({p.codigo for rol in usuario.roles for p in rol.permisos})


def usuario_a_dict(usuario: Usuario) -> dict:
    return {
        "id": usuario.id,
        "nombre": usuario.nombre,
        "email": usuario.email,
        "activo": usuario.activo,
        "roles": sorted(r.nombre for r in usuario.roles),
        "ultimo_acceso": iso(usuario.ultimo_acceso),
    }


def usuario_actual() -> tuple[Usuario, dict]:
    esquema, _, token = request.headers.get("Authorization", "").partition(" ")
    if esquema.lower() != "bearer" or not token.strip():
        raise ErrorApi(401, "NO_AUTENTICADO", "Token ausente")
    try:
        claims = decodificar_token(token.strip())
        usuario = get_db().get(Usuario, int(claims["sub"]))
    except (jwt.PyJWTError, ValueError):
        raise ErrorApi(401, "TOKEN_INVALIDO", "Token inválido o expirado")
    if usuario is None or not usuario.activo:
        raise ErrorApi(401, "TOKEN_INVALIDO", "Token inválido o expirado")
    return usuario, claims


def requiere_gestion(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        usuario, _ = usuario_actual()
        if "usuarios.gestionar" not in permisos_de(usuario):
            raise ErrorApi(403, "SIN_PERMISO", "Se requiere el permiso usuarios.gestionar")
        return vista(*args, **kwargs)

    return envoltura


def cargar_roles(ids: list[int]) -> list[Rol]:
    ids_unicos = set(ids)
    if not ids_unicos:
        return []
    roles = list(get_db().scalars(select(Rol).where(Rol.id.in_(ids_unicos))))
    faltantes = sorted(ids_unicos - {r.id for r in roles})
    if faltantes:
        raise ErrorApi(404, "ROL_NO_ENCONTRADO", "Algún rol no existe", [{"roles_inexistentes": faltantes}])
    return roles


def obtener_usuario(usuario_id: int) -> Usuario:
    usuario = get_db().get(Usuario, usuario_id)
    if usuario is None:
        raise ErrorApi(404, "USUARIO_NO_ENCONTRADO", "No existe")
    return usuario


# ---------- autenticación ----------
@app.post("/auth/login")
def login():
    datos = cuerpo_json()
    email = email_valido(datos)
    password = texto(datos, "password")
    db = get_db()
    usuario = db.scalar(select(Usuario).where(Usuario.email == email))
    if (
        usuario is None
        or not usuario.activo
        or not verificar_password(password, usuario.password_hash)
    ):
        raise ErrorApi(401, "CREDENCIALES_INVALIDAS", "Credenciales inválidas")
    usuario.ultimo_acceso = ahora()
    db.commit()
    return jsonify(
        {
            "access_token": crear_token(usuario.id, usuario.email),
            "token_type": "Bearer",
            "expires_in": JWT_EXPIRA_SEGUNDOS,
        }
    )


@app.get("/auth/validar")
def validar():
    usuario, claims = usuario_actual()
    return jsonify(
        {
            "usuario_id": usuario.id,
            "email": usuario.email,
            "roles": sorted(r.nombre for r in usuario.roles),
            "permisos": permisos_de(usuario),
            "expira_en": datetime.fromtimestamp(claims["exp"], tz=timezone.utc).isoformat(),
        }
    )


# ---------- roles y permisos ----------
@app.get("/roles")
@requiere_gestion
def listar_roles():
    roles = get_db().scalars(select(Rol).order_by(Rol.id))
    return jsonify(
        [
            {
                "id": r.id,
                "nombre": r.nombre,
                "descripcion": r.descripcion,
                "permisos": sorted(p.codigo for p in r.permisos),
            }
            for r in roles
        ]
    )


@app.get("/permisos")
@requiere_gestion
def listar_permisos():
    permisos = get_db().scalars(select(Permiso).order_by(Permiso.id))
    return jsonify([{"id": p.id, "codigo": p.codigo, "descripcion": p.descripcion} for p in permisos])


# ---------- usuarios ----------
@app.get("/")
@requiere_gestion
def listar_usuarios():
    usuarios = get_db().scalars(select(Usuario).order_by(Usuario.id))
    return jsonify([usuario_a_dict(u) for u in usuarios])


@app.post("/")
@requiere_gestion
def crear_usuario():
    datos = cuerpo_json()
    nombre = texto(datos, "nombre", 1, 150)
    email = email_valido(datos)
    password = texto(datos, "password", 10)
    ids_roles = lista_enteros(datos, "roles", requerido=False)

    db = get_db()
    if db.scalar(select(Usuario).where(Usuario.email == email)) is not None:
        raise ErrorApi(409, "EMAIL_DUPLICADO", "Email ya registrado")
    usuario = Usuario(
        nombre=nombre,
        email=email,
        password_hash=hash_password(password),
        roles=cargar_roles(ids_roles),
    )
    db.add(usuario)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ErrorApi(409, "EMAIL_DUPLICADO", "Email ya registrado")
    return jsonify(usuario_a_dict(usuario)), 201


@app.get("/<int:usuario_id>")
@requiere_gestion
def obtener(usuario_id: int):
    return jsonify(usuario_a_dict(obtener_usuario(usuario_id)))


@app.put("/<int:usuario_id>")
@requiere_gestion
def actualizar(usuario_id: int):
    datos = cuerpo_json()
    nombre = texto(datos, "nombre", 1, 150, requerido=False)
    activo = booleano(datos, "activo", requerido=False)
    usuario = obtener_usuario(usuario_id)
    if nombre is not None:
        usuario.nombre = nombre
    if activo is not None:
        usuario.activo = activo
    get_db().commit()
    return jsonify(usuario_a_dict(usuario))


@app.put("/<int:usuario_id>/roles")
@requiere_gestion
def reemplazar_roles(usuario_id: int):
    ids_roles = lista_enteros(cuerpo_json(), "roles")
    usuario = obtener_usuario(usuario_id)
    usuario.roles = cargar_roles(ids_roles)
    get_db().commit()
    return jsonify(usuario_a_dict(usuario))


# ======================================================================
# Inicialización (python app.py): crea tablas y datos iniciales
# ======================================================================
if __name__ == "__main__":
    esperar_bd()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        sembrar(db)
