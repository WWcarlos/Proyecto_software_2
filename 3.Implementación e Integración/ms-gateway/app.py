"""API Gateway propio: único punto de entrada. Valida el JWT y enruta por prefijo. Sin reglas de negocio."""
import logging
import os

import requests
from flask import Flask, Response, jsonify, request

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gateway")

app = Flask(__name__)
app.json.sort_keys = False
app.json.ensure_ascii = False

# Service Discovery en Docker Compose: cada servicio se resuelve por su nombre en la red.
SERVICIOS = {
    nombre: os.getenv(f"{nombre.upper()}_URL", f"http://ms-{nombre}:5000")
    for nombre in ("usuarios", "compras", "productos", "proveedores", "inventarios", "logistica", "analitica")
}
TIMEOUT = float(os.getenv("HTTP_TIMEOUT_SEGUNDOS", "30"))

METODOS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
CABECERAS_SALTADAS = {
    "host", "content-length", "connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade",
}
CABECERAS_SALTADAS_PETICION = CABECERAS_SALTADAS | {"accept-encoding"}
CABECERAS_SALTADAS_RESPUESTA = CABECERAS_SALTADAS | {"content-encoding"}


def error(status: int, codigo: str, mensaje: str):
    respuesta = jsonify({"codigo": codigo, "mensaje": mensaje, "detalles": []})
    respuesta.status_code = status
    return respuesta


def es_publica(metodo: str, prefijo: str, ruta: str) -> bool:
    if metodo == "POST" and prefijo == "usuarios" and ruta == "/auth/login":
        return True
    # Documentación Swagger de cada servicio
    return metodo == "GET" and ruta in ("/docs", "/openapi.yaml")


@app.get("/health")
def health():
    return jsonify({"estado": "ok"})


@app.route("/", defaults={"ruta_completa": ""}, methods=METODOS)
@app.route("/<path:ruta_completa>", methods=METODOS)
def enrutar(ruta_completa: str):
    prefijo, _, resto = ruta_completa.partition("/")
    destino = SERVICIOS.get(prefijo)
    if destino is None:
        return error(404, "RUTA_NO_ENCONTRADA", f"No existe un servicio para la ruta /{prefijo}")
    ruta = "/" + resto  # el prefijo se quita: los contratos definen las rutas relativas al servicio

    # Se descartan las cabeceras X-User-* del cliente para que nadie pueda falsificar su identidad.
    cabeceras = {
        k: v
        for k, v in request.headers
        if k.lower() not in CABECERAS_SALTADAS_PETICION and not k.lower().startswith("x-user-")
    }

    usuario_id = "-"
    if not es_publica(request.method, prefijo, ruta):
        autorizacion = request.headers.get("Authorization", "")
        if autorizacion[:7].lower() != "bearer " or not autorizacion[7:].strip():
            return error(401, "NO_AUTENTICADO", "Token ausente o inválido")
        try:
            validacion = requests.get(
                f"{SERVICIOS['usuarios']}/auth/validar", headers={"Authorization": autorizacion}, timeout=10
            )
        except requests.RequestException:
            return error(502, "USUARIOS_NO_DISPONIBLE", "No fue posible validar el token")
        if validacion.status_code in (401, 403):
            return error(401, "TOKEN_INVALIDO", "Token inválido o expirado")
        if validacion.status_code != 200:
            return error(502, "USUARIOS_RESPUESTA_INESPERADA", "No fue posible validar el token")
        sesion = validacion.json()
        usuario_id = str(sesion["usuario_id"])
        cabeceras["X-User-Id"] = usuario_id
        cabeceras["X-User-Email"] = sesion["email"]
        cabeceras["X-User-Roles"] = ",".join(sesion["roles"])
        cabeceras["X-User-Permissions"] = ",".join(sesion["permisos"])

    try:
        respuesta = requests.request(
            request.method,
            f"{destino}{ruta}",
            params=list(request.args.items(multi=True)),
            headers=cabeceras,
            data=request.get_data() or None,
            timeout=TIMEOUT,
            allow_redirects=False,
        )
    except requests.Timeout:
        return error(504, "SERVICIO_SIN_RESPUESTA", f"El servicio {prefijo} tardó demasiado en responder")
    except requests.RequestException:
        return error(502, "SERVICIO_NO_DISPONIBLE", f"El servicio {prefijo} no está disponible")

    log.info("%s /%s -> %s%s [%s] usuario=%s", request.method, ruta_completa, prefijo, ruta, respuesta.status_code, usuario_id)
    return Response(
        respuesta.content,
        status=respuesta.status_code,
        headers=[(k, v) for k, v in respuesta.headers.items() if k.lower() not in CABECERAS_SALTADAS_RESPUESTA],
    )
