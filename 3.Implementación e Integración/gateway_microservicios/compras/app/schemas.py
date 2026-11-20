from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

Estado = Literal["BORRADOR", "EMITIDA", "PARCIAL", "RECIBIDA", "CANCELADA"]


def _iso_utc(valor: datetime) -> str:
    if valor.tzinfo is None:
        return valor.isoformat() + "Z"
    return valor.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


FechaUTC = Annotated[datetime, PlainSerializer(_iso_utc, return_type=str)]


class DetalleNuevo(BaseModel):
    producto_id: int
    cantidad_solicitada: int = Field(ge=1)
    costo_unitario: float = Field(gt=0)


class OrdenCompraNueva(BaseModel):
    proveedor_id: int
    detalles: list[DetalleNuevo] = Field(min_length=1)


class DetalleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    producto_id: int
    cantidad_solicitada: int
    cantidad_recibida: int
    costo_unitario: float
    subtotal: float


class OrdenCompraOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    numero: str
    proveedor_id: int
    estado: Estado
    total: float
    fecha_creacion: FechaUTC
    detalles: list[DetalleOut]


class RecepcionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    orden_compra_id: int
    bodega_id: int
    fecha_recepcion: FechaUTC
    movimientos_inventario_ids: list[int]


class OrdenCompraConRecepciones(OrdenCompraOut):
    recepciones: list[RecepcionOut]


class LineaRecepcion(BaseModel):
    orden_compra_detalle_id: int
    cantidad_recibida: int = Field(ge=1)


class RecepcionNueva(BaseModel):
    bodega_id: int
    observaciones: str | None = Field(default=None, max_length=500)
    lineas: list[LineaRecepcion] = Field(min_length=1)
