"""API Gateway propio: único punto de entrada. Valida el JWT y enruta por prefijo. Sin reglas de negocio."""
import logging
import os

import httpx
from flask import Flask, Response, jsonify, request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("gateway")

# Service Discovery en Docker Compose: cada servicio se resuelve por su nombre en la red.
SERVICIOS = {
    nombre: os.getenv(f"{nombre.upper()}_URL", f"http://{nombre}:8000")
    for nombre in ("usuarios", "compras", "productos", "proveedores", "inventarios", "logistica", "analitica")
}

# Token compartido entre servicios (Inventarios lo exige en X-Service-Token).
SERVICE_TOKEN = os.getenv("SERVICE_TOKEN", "")

METODOS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
CABECERAS_SALTADAS = {
    "host", "content-length", "connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade",
    "accept-encoding",  # httpx negocia su propia codificación y la descomprime
}
# Cabeceras de identidad que solo el Gateway puede poner: se descartan las que envíe el cliente.
CABECERAS_IDENTIDAD = {"x-usuario-id", "x-service-token"}
CABECERAS_RESPUESTA_SALTADAS = CABECERAS_SALTADAS | {"content-encoding"}

app = Flask(__name__)
app.json.ensure_ascii = False
app.json.sort_keys = False

http = httpx.Client(timeout=httpx.Timeout(float(os.getenv("HTTP_TIMEOUT_SEGUNDOS", "30"))))


def error(status: int, codigo: str, mensaje: str):
    return jsonify({"codigo": codigo, "mensaje": mensaje, "detalles": []}), status


def es_publica(metodo: str, prefijo: str, ruta: str) -> bool:
    # Rutas de Usuarios que se usan sin sesión: login y recuperación de contraseña.
    if metodo == "POST" and prefijo == "usuarios" and ruta in ("/auth/login", "/auth/recuperar", "/auth/restablecer"):
        return True
    # Documentación de cada servicio
    return metodo == "GET" and ruta in ("/docs", "/openapi.json", "/openapi.yaml")


@app.get("/health")
def health():
    return jsonify(estado="ok")


@app.route("/", defaults={"ruta_completa": ""}, methods=METODOS)
@app.route("/<path:ruta_completa>", methods=METODOS)
def enrutar(ruta_completa: str):
    prefijo, _, resto = ruta_completa.partition("/")
    destino = SERVICIOS.get(prefijo)
    if destino is None:
        return error(404, "RUTA_NO_ENCONTRADA", f"No existe un servicio para la ruta /{prefijo}")
    ruta = "/" + resto  # el prefijo se quita: los contratos definen las rutas relativas al servicio

    # Se descartan las cabeceras de identidad del cliente para que nadie pueda falsificarlas.
    cabeceras = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in CABECERAS_SALTADAS
        and k.lower() not in CABECERAS_IDENTIDAD
        and not k.lower().startswith("x-user-")
    }
    if SERVICE_TOKEN:
        cabeceras["X-Service-Token"] = SERVICE_TOKEN

    usuario_id = "-"
    if not es_publica(request.method, prefijo, ruta):
        autorizacion = request.headers.get("Authorization", "")
        if autorizacion[:7].lower() != "bearer " or not autorizacion[7:].strip():
            return error(401, "NO_AUTENTICADO", "Token ausente o inválido")
        try:
            validacion = http.get(
                f"{SERVICIOS['usuarios']}/auth/validar", headers={"Authorization": autorizacion}
            )
        except httpx.HTTPError:
            return error(502, "USUARIOS_NO_DISPONIBLE", "No fue posible validar el token")
        if validacion.status_code in (401, 403):
            return error(401, "TOKEN_INVALIDO", "Token inválido o expirado")
        if validacion.status_code != 200:
            return error(502, "USUARIOS_RESPUESTA_INESPERADA", "No fue posible validar el token")
        sesion = validacion.json()
        usuario_id = str(sesion["usuario_id"])
        cabeceras["X-User-Id"] = usuario_id
        cabeceras["X-Usuario-Id"] = usuario_id  # nombre que usa Inventarios
        cabeceras["X-User-Email"] = sesion["email"]
        cabeceras["X-User-Roles"] = ",".join(sesion["roles"])
        cabeceras["X-User-Permissions"] = ",".join(sesion["permisos"])

    try:
        respuesta = http.request(
            request.method,
            f"{destino}{ruta}",
            params=list(request.args.items(multi=True)),
            headers=cabeceras,
            content=request.get_data() or None,
        )
    except httpx.TimeoutException:
        return error(504, "SERVICIO_SIN_RESPUESTA", f"El servicio {prefijo} tardó demasiado en responder")
    except httpx.HTTPError:
        return error(502, "SERVICIO_NO_DISPONIBLE", f"El servicio {prefijo} no está disponible")

    log.info("%s /%s -> %s%s [%s] usuario=%s", request.method, ruta_completa, prefijo, ruta, respuesta.status_code, usuario_id)
    return Response(
        respuesta.content,
        status=respuesta.status_code,
        headers=[(k, v) for k, v in respuesta.headers.items() if k.lower() not in CABECERAS_RESPUESTA_SALTADAS],
    )
