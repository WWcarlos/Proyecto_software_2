"""Llamadas REST a otros microservicios (Proveedores, Productos, Inventarios) por su nombre en la red."""
import os

import httpx

from .auth import Identidad
from .errores import ErrorApi

PROVEEDORES_URL = os.getenv("PROVEEDORES_URL", "http://proveedores:8000")
PRODUCTOS_URL = os.getenv("PRODUCTOS_URL", "http://productos:8000")
INVENTARIOS_URL = os.getenv("INVENTARIOS_URL", "http://inventarios:8000")
ANALITICA_URL = os.getenv("ANALITICA_URL", "http://analitica:8000")

_http = httpx.Client(timeout=httpx.Timeout(float(os.getenv("HTTP_TIMEOUT_SEGUNDOS", "10"))))


class InventariosError(Exception):
    """Inventarios no pudo registrar el movimiento (no disponible o respuesta distinta de 201)."""


def _existe(url: str, identidad: Identidad, servicio: str, codigo_404: str, mensaje_404: str) -> None:
    try:
        respuesta = _http.get(url, headers=identidad.cabeceras_salida())
    except httpx.HTTPError:
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
        respuesta = _http.post(f"{INVENTARIOS_URL}/movimientos", json=cuerpo, headers=identidad.cabeceras_salida())
    except httpx.HTTPError as error:
        raise InventariosError(f"Inventarios no disponible ({type(error).__name__})")
    if respuesta.status_code != 201:
        raise InventariosError(f"Inventarios respondió {respuesta.status_code}")
    try:
        return int(respuesta.json()["id"])
    except (ValueError, KeyError, TypeError):
        raise InventariosError("Inventarios devolvió una respuesta sin id de movimiento")


def publicar_orden_recibida(orden, recepcion) -> None:
    """Envía a Analítica el evento orden.recibida. Si Analítica no responde, la recepción no falla."""
    from .auth import SERVICE_TOKEN

    cuerpo = {
        "evento_id": f"recepcion-{recepcion.id}",
        "tipo_evento": "orden.recibida",
        "datos": {
            "orden_id": orden.id,
            "numero": orden.numero,
            "estado": orden.estado,
            "proveedor_id": orden.proveedor_id,
            "recepcion_id": recepcion.id,
            "bodega_id": recepcion.bodega_id,
            "lineas": [
                {"orden_compra_detalle_id": d.orden_compra_detalle_id, "cantidad_recibida": d.cantidad_recibida}
                for d in recepcion.detalles
            ],
        },
    }
    try:
        _http.post(f"{ANALITICA_URL}/eventos", json=cuerpo, headers={"X-Service-Token": SERVICE_TOKEN}, timeout=2)
    except httpx.HTTPError:
        pass
