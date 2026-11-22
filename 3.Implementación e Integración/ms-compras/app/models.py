from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def ahora() -> datetime:
    # MySQL no guarda zona horaria: se almacena siempre UTC "ingenuo" y al responder se agrega la Z.
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
