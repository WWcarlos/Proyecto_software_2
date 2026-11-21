"""Microservicio de Compras: órdenes de compra y recepciones. Flask + MySQL."""
import logging
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from functools import wraps
from pathlib import Path
from uuid import uuid4

import requests
from flask import Flask, Response, g, jsonify, request
from sqlalchemy import DateTime, ForeignKey, Numeric, String, create_engine, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
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
class OrdenCompra(Base):
    __tablename__ = "orden_compra"

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[str] = mapped_column(String(30), unique=True)
    proveedor_id: Mapped[int] = mapped_column(index=True)  # referencia lógica a Proveedores
    estado: Mapped[str] = mapped_column(String(20), default="BORRADOR", index=True)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    creado_por_usuario_id: Mapped[int]
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    fecha_emision: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    detalles: Mapped[list["OrdenCompraDetalle"]] = relationship(
        back_populates="orden",
        cascade="all, delete-orphan",
        order_by="OrdenCompraDetalle.id",
        lazy="selectin",
    )
    recepciones: Mapped[list["Recepcion"]] = relationship(
        back_populates="orden", order_by="Recepcion.id", lazy="selectin"
    )


class OrdenCompraDetalle(Base):
    __tablename__ = "orden_compra_detalle"

    id: Mapped[int] = mapped_column(primary_key=True)
    orden_compra_id: Mapped[int] = mapped_column(ForeignKey("orden_compra.id"), index=True)
    producto_id: Mapped[int]  # referencia lógica a Productos
    cantidad_solicitada: Mapped[int]
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    orden: Mapped[OrdenCompra] = relationship(back_populates="detalles")
    lineas_recibidas: Mapped[list["RecepcionDetalle"]] = relationship(lazy="selectin")

    @property
    def cantidad_recibida(self) -> int:
        return sum(linea.cantidad_recibida for linea in self.lineas_recibidas)


class Recepcion(Base):
    __tablename__ = "recepcion"

    id: Mapped[int] = mapped_column(primary_key=True)
    orden_compra_id: Mapped[int] = mapped_column(ForeignKey("orden_compra.id"), index=True)
    bodega_id: Mapped[int]  # referencia lógica a Inventarios
    recibido_por_usuario_id: Mapped[int]
    fecha_recepcion: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    observaciones: Mapped[str | None] = mapped_column(String(500), nullable=True)

    orden: Mapped[OrdenCompra] = relationship(back_populates="recepciones")
    detalles: Mapped[list["RecepcionDetalle"]] = relationship(
        cascade="all, delete-orphan", order_by="RecepcionDetalle.id", lazy="selectin"
    )

    @property
    def movimientos_inventario_ids(self) -> list[int]:
        return [d.movimiento_inventario_id for d in self.detalles]


class RecepcionDetalle(Base):
    __tablename__ = "recepcion_detalle"

    id: Mapped[int] = mapped_column(primary_key=True)
    recepcion_id: Mapped[int] = mapped_column(ForeignKey("recepcion.id"), index=True)
    orden_compra_detalle_id: Mapped[int] = mapped_column(ForeignKey("orden_compra_detalle.id"), index=True)
    cantidad_recibida: Mapped[int]
    # Id de la ENTRADA confirmada por Inventarios (el contrato lo devuelve como movimientos_inventario_ids).
    movimiento_inventario_id: Mapped[int]


# ======================================================================
# Identidad del usuario (cabeceras X-User-* que pone el Gateway)
# ======================================================================
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
            "X-User-Email": self.email,
            "X-User-Roles": ",".join(self.roles),
            "X-User-Permissions": ",".join(sorted(self.permisos)),
        }
        if self.authorization:
            cabeceras["Authorization"] = self.authorization
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


def requiere(permiso: str | None = None):
    """Exige identidad (y el permiso indicado, si se pide). La vista recibe `identidad`."""

    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            identidad = obtener_identidad()
            if permiso is not None and permiso not in identidad.permisos:
                raise ErrorApi(403, "SIN_PERMISO", f"Se requiere el permiso {permiso}")
            return vista(*args, identidad=identidad, **kwargs)

        return envoltura

    return decorador


# ======================================================================
# Llamadas REST a Proveedores, Productos e Inventarios
# ======================================================================
PROVEEDORES_URL = os.getenv("PROVEEDORES_URL", "http://ms-proveedores:5000")
PRODUCTOS_URL = os.getenv("PRODUCTOS_URL", "http://ms-productos:5000")
INVENTARIOS_URL = os.getenv("INVENTARIOS_URL", "http://ms-inventarios:5000")
TIMEOUT = float(os.getenv("HTTP_TIMEOUT_SEGUNDOS", "10"))


class InventariosError(Exception):
    """Inventarios no pudo registrar el movimiento (no disponible o respuesta distinta de 201)."""


def _existe(url: str, identidad: Identidad, servicio: str, codigo_404: str, mensaje_404: str) -> None:
    try:
        respuesta = requests.get(url, headers=identidad.cabeceras_salida(), timeout=TIMEOUT)
    except requests.RequestException:
        raise ErrorApi(502, "SERVICIO_NO_DISPONIBLE", f"{servicio} no disponible")
    if respuesta.status_code == 404:
        raise ErrorApi(404, codigo_404, mensaje_404)
    if respuesta.status_code != 200:
        raise ErrorApi(502, "RESPUESTA_INESPERADA", f"{servicio} respondió {respuesta.status_code}")


def verificar_proveedor(proveedor_id: int, identidad: Identidad) -> None:
    _existe(
        f"{PROVEEDORES_URL}/{proveedor_id}", identidad, "Proveedores",
        "PROVEEDOR_NO_ENCONTRADO", f"El proveedor {proveedor_id} no existe",
    )


def verificar_producto(producto_id: int, identidad: Identidad) -> None:
    _existe(
        f"{PRODUCTOS_URL}/{producto_id}", identidad, "Productos",
        "PRODUCTO_NO_ENCONTRADO", f"El producto {producto_id} no existe",
    )


def solicitar_entrada(
    identidad: Identidad, producto_id: int, bodega_id: int, cantidad: int, orden_id: int, numero_orden: str
) -> int:
    """Pide a Inventarios una ENTRADA con referencia ORDEN_COMPRA. Devuelve el id del movimiento."""
    cuerpo = {
        "tipo": "ENTRADA",
        "producto_id": producto_id,
        "cantidad": cantidad,
        "bodega_destino_id": bodega_id,
        "motivo": f"Recepción de la orden {numero_orden}",
        "referencia_tipo": "ORDEN_COMPRA",
        "referencia_id": orden_id,
    }
    try:
        respuesta = requests.post(
            f"{INVENTARIOS_URL}/movimientos", json=cuerpo, headers=identidad.cabeceras_salida(), timeout=TIMEOUT
        )
    except requests.RequestException as error:
        raise InventariosError(f"Inventarios no disponible ({type(error).__name__})")
    if respuesta.status_code != 201:
        raise InventariosError(f"Inventarios respondió {respuesta.status_code}")
    try:
        return int(respuesta.json()["id"])
    except (ValueError, KeyError, TypeError):
        raise InventariosError("Inventarios devolvió una respuesta sin id de movimiento")


# ======================================================================
# Aplicación y rutas
# ======================================================================
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.json.sort_keys = False
app.json.ensure_ascii = False
app.teardown_appcontext(cerrar_db)
registrar_manejadores(app)
registrar_docs(app, "API Compras")

ESTADOS = ("BORRADOR", "EMITIDA", "PARCIAL", "RECIBIDA", "CANCELADA")
GESTIONAR_ORDENES = "compras.ordenes.gestionar"
REGISTRAR_RECEPCIONES = "compras.recepciones.registrar"


# ---------- utilidades ----------
def dinero(valor) -> Decimal:
    return Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def obtener_orden(orden_id: int, bloquear: bool = False) -> OrdenCompra:
    orden = get_db().get(OrdenCompra, orden_id, with_for_update=bloquear)
    if orden is None:
        raise ErrorApi(404, "ORDEN_NO_ENCONTRADA", "No existe")
    return orden


def detalle_a_dict(d: OrdenCompraDetalle) -> dict:
    return {
        "id": d.id,
        "producto_id": d.producto_id,
        "cantidad_solicitada": d.cantidad_solicitada,
        "cantidad_recibida": d.cantidad_recibida,
        "costo_unitario": float(d.costo_unitario),
        "subtotal": float(d.subtotal),
    }


def recepcion_a_dict(r: Recepcion) -> dict:
    return {
        "id": r.id,
        "orden_compra_id": r.orden_compra_id,
        "bodega_id": r.bodega_id,
        "fecha_recepcion": iso(r.fecha_recepcion),
        "movimientos_inventario_ids": r.movimientos_inventario_ids,
    }


def orden_a_dict(o: OrdenCompra, con_recepciones: bool = False) -> dict:
    datos = {
        "id": o.id,
        "numero": o.numero,
        "proveedor_id": o.proveedor_id,
        "estado": o.estado,
        "total": float(o.total),
        "fecha_creacion": iso(o.fecha_creacion),
        "detalles": [detalle_a_dict(d) for d in o.detalles],
    }
    if con_recepciones:
        datos["recepciones"] = [recepcion_a_dict(r) for r in o.recepciones]
    return datos


# ---------- órdenes ----------
@app.get("/ordenes")
@requiere()
def listar_ordenes(identidad):
    consulta = select(OrdenCompra).order_by(OrdenCompra.id.desc())
    estado = request.args.get("estado")
    if estado is not None:
        if estado not in ESTADOS:
            fallo("estado", f"Debe ser uno de: {', '.join(ESTADOS)}")
        consulta = consulta.where(OrdenCompra.estado == estado)
    proveedor_id = request.args.get("proveedor_id")
    if proveedor_id is not None:
        if not proveedor_id.isdigit():
            fallo("proveedor_id", "Debe ser un entero")
        consulta = consulta.where(OrdenCompra.proveedor_id == int(proveedor_id))
    return jsonify([orden_a_dict(o) for o in get_db().scalars(consulta)])


@app.post("/ordenes")
@requiere(GESTIONAR_ORDENES)
def crear_orden(identidad):
    datos = cuerpo_json()
    proveedor_id = entero(datos, "proveedor_id", minimo=1)
    lineas = []
    for i, crudo in enumerate(lista(datos, "detalles", minimo=1)):
        prefijo = f"detalles.{i}."
        if not isinstance(crudo, dict):
            fallo(f"detalles.{i}", "Debe ser un objeto")
        lineas.append(
            {
                "producto_id": entero(crudo, "producto_id", minimo=1, prefijo=prefijo),
                "cantidad_solicitada": entero(crudo, "cantidad_solicitada", minimo=1, prefijo=prefijo),
                "costo_unitario": numero_positivo(crudo, "costo_unitario", prefijo=prefijo),
            }
        )

    verificar_proveedor(proveedor_id, identidad)
    for producto_id in sorted({linea["producto_id"] for linea in lineas}):
        verificar_producto(producto_id, identidad)

    db = get_db()
    orden = OrdenCompra(
        numero=f"PEND-{uuid4().hex[:20]}",  # se reemplaza al conocer el id
        proveedor_id=proveedor_id,
        estado="BORRADOR",
        creado_por_usuario_id=identidad.usuario_id,
    )
    total = Decimal("0.00")
    for linea in lineas:
        costo = dinero(linea["costo_unitario"])
        subtotal = costo * linea["cantidad_solicitada"]
        total += subtotal
        orden.detalles.append(
            OrdenCompraDetalle(
                producto_id=linea["producto_id"],
                cantidad_solicitada=linea["cantidad_solicitada"],
                costo_unitario=costo,
                subtotal=subtotal,
            )
        )
    orden.total = total
    db.add(orden)
    db.flush()
    orden.numero = f"OC-{orden.fecha_creacion.year}-{orden.id:04d}"
    db.commit()
    return jsonify(orden_a_dict(orden)), 201


@app.get("/ordenes/<int:orden_id>")
@requiere()
def obtener(orden_id: int, identidad):
    return jsonify(orden_a_dict(obtener_orden(orden_id), con_recepciones=True))


@app.post("/ordenes/<int:orden_id>/emitir")
@requiere(GESTIONAR_ORDENES)
def emitir(orden_id: int, identidad):
    orden = obtener_orden(orden_id, bloquear=True)
    if orden.estado != "BORRADOR":
        raise ErrorApi(409, "ESTADO_NO_PERMITE_EMITIR", f"Una orden {orden.estado} no se puede emitir")
    orden.estado = "EMITIDA"
    orden.fecha_emision = ahora()
    get_db().commit()
    return jsonify(orden_a_dict(orden))


@app.post("/ordenes/<int:orden_id>/cancelar")
@requiere(GESTIONAR_ORDENES)
def cancelar(orden_id: int, identidad):
    orden = obtener_orden(orden_id, bloquear=True)
    if orden.estado not in ("BORRADOR", "EMITIDA") or orden.recepciones:
        raise ErrorApi(
            409,
            "ORDEN_NO_CANCELABLE",
            "La orden ya tiene recepciones, está recibida o ya fue cancelada",
        )
    orden.estado = "CANCELADA"
    get_db().commit()
    return jsonify(orden_a_dict(orden))


# ---------- recepciones ----------
@app.post("/ordenes/<int:orden_id>/recepciones")
@requiere(REGISTRAR_RECEPCIONES)
def registrar_recepcion(orden_id: int, identidad):
    datos = cuerpo_json()
    bodega_id = entero(datos, "bodega_id", minimo=1)
    observaciones = texto(datos, "observaciones", 0, 500, requerido=False)
    lineas = []
    for i, crudo in enumerate(lista(datos, "lineas", minimo=1)):
        prefijo = f"lineas.{i}."
        if not isinstance(crudo, dict):
            fallo(f"lineas.{i}", "Debe ser un objeto")
        lineas.append(
            (
                entero(crudo, "orden_compra_detalle_id", minimo=1, prefijo=prefijo),
                entero(crudo, "cantidad_recibida", minimo=1, prefijo=prefijo),
            )
        )

    db = get_db()
    # La fila de la orden se bloquea para que dos recepciones simultáneas no excedan lo pendiente.
    orden = obtener_orden(orden_id, bloquear=True)
    if orden.estado not in ("EMITIDA", "PARCIAL"):
        raise ErrorApi(
            409,
            "ORDEN_NO_RECIBIBLE",
            f"La orden está {orden.estado}; solo se recibe mercancía de órdenes EMITIDA o PARCIAL",
        )

    detalles = {d.id: d for d in orden.detalles}
    solicitado: dict[int, int] = defaultdict(int)
    for detalle_id, cantidad in lineas:
        if detalle_id not in detalles:
            raise ErrorApi(
                422, "DETALLE_NO_PERTENECE", f"El detalle {detalle_id} no pertenece a la orden {orden.numero}"
            )
        solicitado[detalle_id] += cantidad
    excedidos = []
    for detalle_id, cantidad in solicitado.items():
        pendiente = detalles[detalle_id].cantidad_solicitada - detalles[detalle_id].cantidad_recibida
        if cantidad > pendiente:
            excedidos.append(
                {"orden_compra_detalle_id": detalle_id, "pendiente": pendiente, "recibida_en_esta_solicitud": cantidad}
            )
    if excedidos:
        raise ErrorApi(409, "CANTIDAD_EXCEDE_PENDIENTE", "La cantidad recibida excede lo pendiente", excedidos)

    # Se solicita la ENTRADA a Inventarios línea por línea. Solo se registran las líneas que
    # Inventarios confirmó; si falla, las restantes quedan pendientes para reintentar.
    recepcion = Recepcion(
        orden_compra_id=orden.id,
        bodega_id=bodega_id,
        recibido_por_usuario_id=identidad.usuario_id,
        observaciones=observaciones,
    )
    pendientes: list[dict] = []
    causa: str | None = None
    for detalle_id, cantidad in lineas:
        if causa is None:
            try:
                movimiento_id = solicitar_entrada(
                    identidad, detalles[detalle_id].producto_id, bodega_id, cantidad, orden.id, orden.numero
                )
            except InventariosError as error:
                causa = str(error)
            else:
                recepcion.detalles.append(
                    RecepcionDetalle(
                        orden_compra_detalle_id=detalle_id,
                        cantidad_recibida=cantidad,
                        movimiento_inventario_id=movimiento_id,
                    )
                )
                continue
        pendientes.append({"orden_compra_detalle_id": detalle_id, "cantidad_recibida": cantidad})

    registradas = [
        {
            "orden_compra_detalle_id": r.orden_compra_detalle_id,
            "movimiento_inventario_id": r.movimiento_inventario_id,
        }
        for r in recepcion.detalles
    ]
    if recepcion.detalles:
        recibido_ahora: dict[int, int] = defaultdict(int)
        for r in recepcion.detalles:
            recibido_ahora[r.orden_compra_detalle_id] += r.cantidad_recibida
        completa = all(
            d.cantidad_recibida + recibido_ahora[d.id] >= d.cantidad_solicitada for d in orden.detalles
        )
        orden.estado = "RECIBIDA" if completa else "PARCIAL"
        db.add(recepcion)
        db.commit()
    else:
        db.rollback()

    if causa is not None:
        raise ErrorApi(
            502,
            "INVENTARIOS_NO_DISPONIBLE",
            "Inventarios no registró todas las entradas; las líneas pendientes deben reintentarse",
            [
                {
                    "causa": causa,
                    "recepcion_id": recepcion.id if registradas else None,
                    "lineas_registradas": registradas,
                    "lineas_pendientes": pendientes,
                }
            ],
        )
    return jsonify(recepcion_a_dict(recepcion)), 201


# ======================================================================
# Inicialización (python app.py): crea las tablas
# ======================================================================
if __name__ == "__main__":
    esperar_bd()
    Base.metadata.create_all(engine)
