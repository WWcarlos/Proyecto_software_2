"""Formato de error común: {codigo, mensaje, detalles}, más utilidades de validación y respuesta."""
import logging

from flask import Flask, jsonify, request
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

log = logging.getLogger(__name__)


class ErrorApi(Exception):
    def __init__(self, status: int, codigo: str, mensaje: str, detalles: list | None = None):
        super().__init__(mensaje)
        self.status = status
        self.codigo = codigo
        self.mensaje = mensaje
        self.detalles = detalles or []


def _respuesta(status: int, codigo: str, mensaje: str, detalles: list | None = None):
    return jsonify({"codigo": codigo, "mensaje": mensaje, "detalles": detalles or []}), status


def detalles_validacion(exc: ValidationError) -> list[dict]:
    return [{"campo": ".".join(str(p) for p in e["loc"]), "error": e["msg"]} for e in exc.errors()]


def validar_cuerpo(modelo):
    """Valida el JSON de la petición con un modelo pydantic; si falla responde 422."""
    cuerpo = request.get_json(force=True, silent=True)
    try:
        return modelo.model_validate(cuerpo if cuerpo is not None else {})
    except ValidationError as exc:
        raise ErrorApi(422, "VALIDACION_FALLIDA", "Datos inválidos", detalles_validacion(exc))


def salida(objeto, status: int = 200):
    """Serializa un modelo pydantic (o una lista de ellos) como respuesta JSON."""
    if isinstance(objeto, list):
        return jsonify([o.model_dump(mode="json") for o in objeto]), status
    return jsonify(objeto.model_dump(mode="json")), status


def registrar_manejadores(app: Flask) -> None:
    @app.errorhandler(ErrorApi)
    def _error_api(exc: ErrorApi):
        return _respuesta(exc.status, exc.codigo, exc.mensaje, exc.detalles)

    @app.errorhandler(HTTPException)
    def _http(exc: HTTPException):
        return _respuesta(exc.code or 500, "ERROR_HTTP", exc.description or exc.name)

    @app.errorhandler(Exception)
    def _inesperado(exc: Exception):
        log.exception("Error no controlado")
        return _respuesta(500, "ERROR_INTERNO", "Error interno del servidor")
