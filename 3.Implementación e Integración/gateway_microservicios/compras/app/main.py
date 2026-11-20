from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import get_args
from uuid import uuid4

from flask import Flask, jsonify, request
from sqlalchemy import select

from . import clientes, models, schemas
from .auth import requiere, obtener_identidad
from .db import Base, Session, engine, esperar_bd
from .errores import ErrorApi, registrar_manejadores, salida, validar_cuerpo

app = Flask(__name__)
app.json.ensure_ascii = False
app.json.sort_keys = False
registrar_manejadores(app)


@app.teardown_appcontext
def _cerrar_sesion(_):
    Session.remove()


def iniciar() -> None:
    """Equivalente al 'lifespan' de FastAPI: espera la BD y crea las tablas."""
    esperar_bd()
    Base.metadata.create_all(engine)


iniciar()

GESTIONAR_ORDENES = "compras.ordenes.gestionar"
REGISTRAR_RECEPCIONES = "compras.recepciones.registrar"
ESTADOS = get_args(schemas.Estado)


def dinero(valor: float | Decimal) -> Decimal:
    return Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def obtener_orden(orden_id: int, bloquear: bool = False) -> models.OrdenCompra:
    orden = Session.get(models.OrdenCompra, orden_id, with_for_update=bloquear)
    if orden is None:
        raise ErrorApi(404, "ORDEN_NO_ENCONTRADA", "No existe")
    return orden


def _error_consulta(campo: str, mensaje: str) -> ErrorApi:
    return ErrorApi(422, "VALIDACION_FALLIDA", "Datos inválidos", [{"campo": f"query.{campo}", "error": mensaje}])


@app.get("/health")
def health():
    return jsonify(estado="ok", servicio="compras")


# ---------- órdenes ----------
@app.get("/ordenes")
def listar_ordenes():
    obtener_identidad()
    estado = request.args.get("estado")
    if estado is not None and estado not in ESTADOS:
        raise _error_consulta("estado", f"Debe ser uno de {list(ESTADOS)}")
    proveedor_id = None
    if "proveedor_id" in request.args:
        try:
            proveedor_id = int(request.args["proveedor_id"])
        except ValueError:
            raise _error_consulta("proveedor_id", "Debe ser un entero")

    consulta = select(models.OrdenCompra).order_by(models.OrdenCompra.id.desc())
    if estado is not None:
        consulta = consulta.where(models.OrdenCompra.estado == estado)
    if proveedor_id is not None:
        consulta = consulta.where(models.OrdenCompra.proveedor_id == proveedor_id)
    return salida([schemas.OrdenCompraOut.model_validate(o) for o in Session.scalars(consulta)])


@app.post("/ordenes")
def crear_orden():
    """Crear orden de compra en estado BORRADOR."""
    identidad = requiere(GESTIONAR_ORDENES)
    datos = validar_cuerpo(schemas.OrdenCompraNueva)
    clientes.verificar_proveedor(datos.proveedor_id, identidad)
    for producto_id in sorted({d.producto_id for d in datos.detalles}):
        clientes.verificar_producto(producto_id, identidad)

    orden = models.OrdenCompra(
        numero=f"PEND-{uuid4().hex[:20]}",
        proveedor_id=datos.proveedor_id,
        estado="BORRADOR",
        creado_por_usuario_id=identidad.usuario_id,
    )
    total = Decimal("0.00")
    for d in datos.detalles:
        costo = dinero(d.costo_unitario)
        subtotal = costo * d.cantidad_solicitada
        total += subtotal
        orden.detalles.append(
            models.OrdenCompraDetalle(
                producto_id=d.producto_id,
                cantidad_solicitada=d.cantidad_solicitada,
                costo_unitario=costo,
                subtotal=subtotal,
            )
        )
    orden.total = total
    Session.add(orden)
    Session.flush()
    orden.numero = f"OC-{orden.fecha_creacion.year}-{orden.id:04d}"
    Session.commit()
    return salida(schemas.OrdenCompraOut.model_validate(orden), 201)


@app.get("/ordenes/<int:orden_id>")
def obtener(orden_id: int):
    """Obtener orden con sus detalles y recepciones."""
    obtener_identidad()
    return salida(schemas.OrdenCompraConRecepciones.model_validate(obtener_orden(orden_id)))


@app.post("/ordenes/<int:orden_id>/emitir")
def emitir(orden_id: int):
    """Emitir orden (BORRADOR → EMITIDA)."""
    requiere(GESTIONAR_ORDENES)
    orden = obtener_orden(orden_id, bloquear=True)
    if orden.estado != "BORRADOR":
        raise ErrorApi(409, "ESTADO_NO_PERMITE_EMITIR", f"Una orden {orden.estado} no se puede emitir")
    orden.estado = "EMITIDA"
    orden.fecha_emision = models.ahora()
    Session.commit()
    return salida(schemas.OrdenCompraOut.model_validate(orden))


@app.post("/ordenes/<int:orden_id>/cancelar")
def cancelar(orden_id: int):
    """Cancelar orden (solo si no tiene recepciones)."""
    requiere(GESTIONAR_ORDENES)
    orden = obtener_orden(orden_id, bloquear=True)
    if orden.estado not in ("BORRADOR", "EMITIDA") or orden.recepciones:
        raise ErrorApi(
            409,
            "ORDEN_NO_CANCELABLE",
            "La orden ya tiene recepciones, está recibida o ya fue cancelada",
        )
    orden.estado = "CANCELADA"
    Session.commit()
    return salida(schemas.OrdenCompraOut.model_validate(orden))


# ---------- recepciones ----------
@app.post("/ordenes/<int:orden_id>/recepciones")
def registrar_recepcion(orden_id: int):
    """Registrar recepción de mercancía (solicita la ENTRADA a Inventarios)."""
    identidad = requiere(REGISTRAR_RECEPCIONES)
    datos = validar_cuerpo(schemas.RecepcionNueva)

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
    for linea in datos.lineas:
        if linea.orden_compra_detalle_id not in detalles:
            raise ErrorApi(
                422,
                "DETALLE_NO_PERTENECE",
                f"El detalle {linea.orden_compra_detalle_id} no pertenece a la orden {orden.numero}",
            )
        solicitado[linea.orden_compra_detalle_id] += linea.cantidad_recibida
    excedidos = [
        {
            "orden_compra_detalle_id": detalle_id,
            "pendiente": detalles[detalle_id].cantidad_solicitada - detalles[detalle_id].cantidad_recibida,
            "recibida_en_esta_solicitud": cantidad,
        }
        for detalle_id, cantidad in solicitado.items()
        if cantidad > detalles[detalle_id].cantidad_solicitada - detalles[detalle_id].cantidad_recibida
    ]
    if excedidos:
        raise ErrorApi(409, "CANTIDAD_EXCEDE_PENDIENTE", "La cantidad recibida excede lo pendiente", excedidos)

    # Se solicita la ENTRADA a Inventarios línea por línea. Solo se registran las líneas que
    # Inventarios confirmó; si falla, las restantes quedan pendientes para reintentar.
    recepcion = models.Recepcion(
        orden_compra_id=orden.id,
        bodega_id=datos.bodega_id,
        recibido_por_usuario_id=identidad.usuario_id,
        observaciones=datos.observaciones,
    )
    pendientes: list[dict] = []
    causa: str | None = None
    for linea in datos.lineas:
        if causa is None:
            detalle = detalles[linea.orden_compra_detalle_id]
            try:
                movimiento_id = clientes.solicitar_entrada(
                    identidad, detalle.producto_id, datos.bodega_id,
                    linea.cantidad_recibida, orden.id, orden.numero,
                )
            except clientes.InventariosError as error:
                causa = str(error)
            else:
                recepcion.detalles.append(
                    models.RecepcionDetalle(
                        orden_compra_detalle_id=detalle.id,
                        cantidad_recibida=linea.cantidad_recibida,
                        movimiento_inventario_id=movimiento_id,
                    )
                )
                continue
        pendientes.append(
            {
                "orden_compra_detalle_id": linea.orden_compra_detalle_id,
                "cantidad_recibida": linea.cantidad_recibida,
            }
        )

    if recepcion.detalles:
        recibido_ahora: dict[int, int] = defaultdict(int)
        for registrada in recepcion.detalles:
            recibido_ahora[registrada.orden_compra_detalle_id] += registrada.cantidad_recibida
        completa = all(
            d.cantidad_recibida + recibido_ahora[d.id] >= d.cantidad_solicitada for d in orden.detalles
        )
        orden.estado = "RECIBIDA" if completa else "PARCIAL"
        Session.add(recepcion)
        Session.commit()
    else:
        Session.rollback()

    if causa is not None:
        raise ErrorApi(
            502,
            "INVENTARIOS_NO_DISPONIBLE",
            "Inventarios no registró todas las entradas; las líneas pendientes deben reintentarse",
            [
                {
                    "causa": causa,
                    "recepcion_id": recepcion.id if recepcion.detalles else None,
                    "lineas_registradas": [
                        {
                            "orden_compra_detalle_id": r.orden_compra_detalle_id,
                            "movimiento_inventario_id": r.movimiento_inventario_id,
                        }
                        for r in recepcion.detalles
                    ],
                    "lineas_pendientes": pendientes,
                }
            ],
        )
    return salida(schemas.RecepcionOut.model_validate(recepcion), 201)
