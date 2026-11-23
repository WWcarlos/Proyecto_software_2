import hmac
import json
import os
import urllib.error
import urllib.request
import uuid
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
import mysql.connector
from mysql.connector import Error as MySQLError, errorcode

load_dotenv()

app = Flask(__name__)

DB_HOST = os.getenv("DB_HOST", "mysql-logistica")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "clave")
DB_NAME = os.getenv("DB_NAME", "bd_logistica")
API_TOKEN = os.getenv("token", "mi-token-super-secreto")

# Conexion hacia Inventarios (del integrante 2). En la red del Gateway el
# servicio se llama "inventarios" y escucha en el puerto 8000.
INVENTARIOS_URL = os.getenv("INVENTARIOS_URL", "http://inventarios:8000")
# "stub" simula Inventarios para probar sin depender del otro servicio.
# "http" hace la llamada real.
INVENTARIOS_MODE = os.getenv("INVENTARIOS_MODE", "stub")
# Analítica recibe los eventos de dominio (envio.creado) por REST.
ANALITICA_URL = os.getenv("ANALITICA_URL", "http://analitica:8000")

# A que estado puede pasar un envio desde cada estado
TRANSICIONES = {
    "CREADO": ["EN_PREPARACION", "FALLIDO"],
    "EN_PREPARACION": ["DESPACHADO", "FALLIDO"],
    "DESPACHADO": ["EN_RUTA", "FALLIDO"],
    "EN_RUTA": ["ENTREGADO", "FALLIDO"],
    "ENTREGADO": [],
    "FALLIDO": [],
}

_mov_stub = 9000


def get_db():
    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )


def error_response(codigo, mensaje, status_code, detalles=None):
    return jsonify({"codigo": codigo, "mensaje": mensaje, "detalles": detalles or []}), status_code


def requiere_permiso(permiso):
    """El Gateway reenvía los permisos del usuario en X-User-Permissions. Devuelve un error 403 o None."""
    permisos = {p for p in request.headers.get("X-User-Permissions", "").split(",") if p}
    if permiso not in permisos:
        return error_response("SIN_PERMISO", f"Se requiere el permiso {permiso}", 403)
    return None


def publicar_evento(tipo_evento, evento_id, datos):
    """Envía un evento de dominio a Analítica. Si Analítica no responde, el envío no falla."""
    payload = json.dumps({"evento_id": evento_id, "tipo_evento": tipo_evento, "datos": datos},
                         default=str).encode("utf-8")
    req = urllib.request.Request(
        f"{ANALITICA_URL}/eventos", data=payload, method="POST",
        headers={"Content-Type": "application/json", "X-Service-Token": API_TOKEN},
    )
    try:
        with urllib.request.urlopen(req, timeout=2):
            pass
    except Exception:
        pass


class SinStock(Exception):
    pass


class InventariosCaido(Exception):
    pass


def registrar_salida(producto_id, bodega_id, cantidad, envio_id):
    """Le pide a Inventarios una SALIDA de stock y devuelve el id del movimiento."""
    global _mov_stub
    if INVENTARIOS_MODE == "stub":
        if cantidad > 1000:
            raise SinStock()
        _mov_stub += 1
        return _mov_stub

    payload = json.dumps({
        "tipo": "SALIDA",
        "producto_id": producto_id,
        "bodega_origen_id": bodega_id,
        "cantidad": cantidad,
        "referencia_tipo": "ENVIO",
        "referencia_id": envio_id,
    }).encode("utf-8")
    # Se reenvía la identidad que puso el Gateway para que Inventarios registre quién hizo la salida.
    cabeceras = {"Content-Type": "application/json", "X-Service-Token": API_TOKEN}
    for nombre in ("X-Usuario-Id", "X-User-Id", "X-User-Email", "X-User-Roles", "X-User-Permissions"):
        if request.headers.get(nombre):
            cabeceras[nombre] = request.headers[nombre]
    req = urllib.request.Request(
        f"{INVENTARIOS_URL}/movimientos",
        data=payload,
        headers=cabeceras,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read()).get("id")
    except urllib.error.HTTPError as e:
        if e.code == 409:
            raise SinStock()
        raise InventariosCaido()
    except Exception:
        raise InventariosCaido()


# =====================================================================
# MIDDLEWARE DE SEGURIDAD (token de servicio)
# =====================================================================
@app.before_request
def verificar_token():
    if request.method == "OPTIONS" or request.path in ("/health", "/docs", "/openapi.yaml"):
        return None

    request_token = request.headers.get("X-Service-Token")
    if not request_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            request_token = auth_header.split(" ", 1)[1].strip()
        else:
            request_token = (request.get_json(silent=True) or {}).get("token")

    if (
        not isinstance(request_token, str)
        or not API_TOKEN
        or not hmac.compare_digest(request_token, API_TOKEN)
    ):
        return error_response("NO_AUTORIZADO", "Token invalido o ausente", 401)

    return None


# =====================================================================
# SALUD Y DOCUMENTACIÓN
# =====================================================================
@app.get("/health")
def health():
    return jsonify(status="ok", servicio="logistica"), 200


@app.get("/openapi.yaml")
def openapi_spec():
    return send_from_directory(".", "logistica.yaml", mimetype="text/yaml")


@app.get("/docs")
def swagger_ui():
    return """<!DOCTYPE html>
<html>
<head>
  <title>API Logistica - Swagger</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>SwaggerUIBundle({ url: 'openapi.yaml', dom_id: '#swagger-ui' });</script>
</body>
</html>""", 200, {"Content-Type": "text/html"}


# =====================================================================
# SERIALIZACIÓN (formas definidas en el contrato logistica.yaml)
# =====================================================================
COLUMNAS_CLIENTE = "id, tipo_documento, numero_documento, nombre, direccion, telefono, email"
COLUMNAS_PAQUETE = "id, cliente_id, codigo_barras, peso_kg, descripcion, estado"
COLUMNAS_ENVIO = ("id, guia_numero, cliente_id, bodega_origen_id, destino, estado_actual, "
                  "creado_por_usuario_id, fecha_creacion")
COLUMNAS_INSUMO = "id, envio_id, producto_id, cantidad, movimiento_salida_id"


def fecha_iso(valor):
    return valor.isoformat() if valor else None


def serializar_paquete(f):
    f = dict(f)
    f["peso_kg"] = float(f["peso_kg"]) if f["peso_kg"] is not None else None  # DECIMAL -> número
    return f


def serializar_envio(f):
    f = dict(f)
    f["fecha_creacion"] = fecha_iso(f["fecha_creacion"])
    return f


def leer_envio(cur, envio_id):
    cur.execute(f"SELECT {COLUMNAS_ENVIO} FROM ENVIO WHERE id = %s", (envio_id,))
    fila = cur.fetchone()
    return serializar_envio(fila) if fila else None


def usuario_actual_id():
    """Id del usuario que el Gateway reenvía en las cabeceras (None si no viene)."""
    valor = request.headers.get("X-Usuario-Id") or request.headers.get("X-User-Id") or ""
    return int(valor) if valor.isdigit() else None


# =====================================================================
# 1. CLIENTES
# =====================================================================
@app.get("/clientes")
def listar_clientes():
    q = request.args.get("q")
    sql = f"SELECT {COLUMNAS_CLIENTE} FROM CLIENTE WHERE 1=1"
    params = []
    if q:
        sql += " AND (nombre LIKE %s OR numero_documento LIKE %s)"
        params.extend([f"%{q}%", f"%{q}%"])
    sql += " ORDER BY id ASC"

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return jsonify(cur.fetchall()), 200
    finally:
        cur.close()
        db.close()


@app.post("/clientes")
def crear_cliente():
    sin_permiso = requiere_permiso("logistica.gestionar")
    if sin_permiso:
        return sin_permiso

    data = request.get_json(silent=True) or {}
    tipo_documento = (data.get("tipo_documento") or "").strip()
    numero_documento = (data.get("numero_documento") or "").strip()
    nombre = (data.get("nombre") or "").strip()

    if not tipo_documento or not numero_documento or not nombre:
        return error_response("VALIDACION_FALLIDA",
                              "tipo_documento, numero_documento y nombre son obligatorios", 422)

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "INSERT INTO CLIENTE (tipo_documento, numero_documento, nombre, direccion, telefono, email) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (tipo_documento, numero_documento, nombre, data.get("direccion"),
             data.get("telefono"), data.get("email")),
        )
        nuevo_id = cur.lastrowid
        db.commit()
        cur.execute(f"SELECT {COLUMNAS_CLIENTE} FROM CLIENTE WHERE id = %s", (nuevo_id,))
        return jsonify(cur.fetchone()), 201
    except MySQLError as e:
        db.rollback()
        if e.errno == errorcode.ER_DUP_ENTRY:
            return error_response("DOCUMENTO_DUPLICADO", "Documento ya registrado", 409)
        return error_response("ERROR_BD", str(e), 500)
    finally:
        cur.close()
        db.close()


# =====================================================================
# 2. PAQUETES
# =====================================================================
@app.get("/paquetes")
def listar_paquetes():
    estado = request.args.get("estado")
    cliente_id = request.args.get("cliente_id", type=int)
    sql = f"SELECT {COLUMNAS_PAQUETE} FROM PAQUETE WHERE 1=1"
    params = []
    if estado:
        sql += " AND estado = %s"
        params.append(estado)
    if cliente_id is not None:
        sql += " AND cliente_id = %s"
        params.append(cliente_id)
    sql += " ORDER BY id ASC"

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return jsonify([serializar_paquete(f) for f in cur.fetchall()]), 200
    finally:
        cur.close()
        db.close()


@app.post("/paquetes")
def crear_paquete():
    sin_permiso = requiere_permiso("logistica.gestionar")
    if sin_permiso:
        return sin_permiso

    data = request.get_json(silent=True) or {}
    cliente_id = data.get("cliente_id")
    codigo_barras = (data.get("codigo_barras") or "").strip()

    if not cliente_id or not codigo_barras:
        return error_response("VALIDACION_FALLIDA", "cliente_id y codigo_barras son obligatorios", 422)

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM CLIENTE WHERE id = %s", (cliente_id,))
        if not cur.fetchone():
            return error_response("NO_ENCONTRADO", "El cliente no existe", 404)

        cur.execute(
            "INSERT INTO PAQUETE (cliente_id, codigo_barras, peso_kg, descripcion, estado) "
            "VALUES (%s, %s, %s, %s, 'RECIBIDO')",
            (cliente_id, codigo_barras, data.get("peso_kg"), data.get("descripcion")),
        )
        nuevo_id = cur.lastrowid
        db.commit()
        cur.execute(f"SELECT {COLUMNAS_PAQUETE} FROM PAQUETE WHERE id = %s", (nuevo_id,))
        return jsonify(serializar_paquete(cur.fetchone())), 201
    except MySQLError as e:
        db.rollback()
        if e.errno == errorcode.ER_DUP_ENTRY:
            return error_response("CODIGO_BARRAS_DUPLICADO", "Ya existe un paquete con ese código de barras", 409)
        return error_response("ERROR_BD", str(e), 500)
    finally:
        cur.close()
        db.close()


# =====================================================================
# 3. ENVIOS (maquina de estados)
# =====================================================================
@app.get("/envios")
def listar_envios():
    estado = request.args.get("estado")
    desde = request.args.get("desde")  # fecha AAAA-MM-DD (incluida)
    hasta = request.args.get("hasta")  # fecha AAAA-MM-DD (incluida)
    sql = f"SELECT {COLUMNAS_ENVIO} FROM ENVIO WHERE 1=1"
    params = []
    if estado:
        sql += " AND estado_actual = %s"
        params.append(estado)
    if desde:
        sql += " AND DATE(fecha_creacion) >= %s"
        params.append(desde)
    if hasta:
        sql += " AND DATE(fecha_creacion) <= %s"
        params.append(hasta)
    sql += " ORDER BY id ASC"

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return jsonify([serializar_envio(f) for f in cur.fetchall()]), 200
    except MySQLError:
        return error_response("VALIDACION_FALLIDA", "desde y hasta deben tener el formato AAAA-MM-DD", 422)
    finally:
        cur.close()
        db.close()


@app.post("/envios")
def crear_envio():
    sin_permiso = requiere_permiso("logistica.gestionar")
    if sin_permiso:
        return sin_permiso

    data = request.get_json(silent=True) or {}
    cliente_id = data.get("cliente_id")
    bodega_origen_id = data.get("bodega_origen_id")
    destino = (data.get("destino") or "").strip()
    paquetes = data.get("paquetes") or []

    if not cliente_id or not bodega_origen_id or not destino or len(paquetes) == 0:
        return error_response("VALIDACION_FALLIDA",
                              "cliente_id, bodega_origen_id, destino y paquetes son obligatorios", 422)

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM CLIENTE WHERE id = %s", (cliente_id,))
        if not cur.fetchone():
            return error_response("NO_ENCONTRADO", "El cliente no existe", 404)

        for pid in paquetes:
            cur.execute("SELECT id FROM PAQUETE WHERE id = %s", (pid,))
            if not cur.fetchone():
                return error_response("NO_ENCONTRADO", f"El paquete {pid} no existe", 404)

        # La guía se deriva del id autoincremental (único) para que dos envíos simultáneos
        # no obtengan el mismo número. Primero se inserta con una guía provisional única.
        cur.execute(
            "INSERT INTO ENVIO (guia_numero, cliente_id, bodega_origen_id, destino, estado_actual, creado_por_usuario_id) "
            "VALUES (%s, %s, %s, %s, 'CREADO', %s)",
            (f"PEND-{uuid.uuid4().hex[:20]}", cliente_id, bodega_origen_id, destino, usuario_actual_id()),
        )
        envio_id = cur.lastrowid
        guia = f"GUI-{envio_id:06d}"
        cur.execute("UPDATE ENVIO SET guia_numero = %s WHERE id = %s", (guia, envio_id))

        for pid in paquetes:
            cur.execute("INSERT INTO ENVIO_PAQUETE (envio_id, paquete_id) VALUES (%s, %s)", (envio_id, pid))
            cur.execute("UPDATE PAQUETE SET estado = 'DESPACHADO' WHERE id = %s", (pid,))

        cur.execute(
            "INSERT INTO HISTORIAL_ESTADO (envio_id, estado, observacion, usuario_id) "
            "VALUES (%s, 'CREADO', 'Envio creado', %s)",
            (envio_id, usuario_actual_id()),
        )
        db.commit()
        envio = leer_envio(cur, envio_id)
        publicar_evento("envio.creado", f"envio-{envio_id}", envio)
        return jsonify(envio), 201
    except MySQLError as e:
        db.rollback()
        return error_response("ERROR_BD", str(e), 500)
    finally:
        cur.close()
        db.close()


@app.get("/envios/<int:envio_id>")
def obtener_envio(envio_id):
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        envio = leer_envio(cur, envio_id)
        if not envio:
            return error_response("NO_ENCONTRADO", "Envio no existe", 404)

        cur.execute(
            "SELECT p.id, p.cliente_id, p.codigo_barras, p.peso_kg, p.descripcion, p.estado "
            "FROM PAQUETE p JOIN ENVIO_PAQUETE ep ON ep.paquete_id = p.id WHERE ep.envio_id = %s",
            (envio_id,),
        )
        envio["paquetes"] = [serializar_paquete(f) for f in cur.fetchall()]

        cur.execute(f"SELECT {COLUMNAS_INSUMO} FROM ENVIO_INSUMO WHERE envio_id = %s ORDER BY id ASC", (envio_id,))
        envio["insumos"] = cur.fetchall()

        cur.execute(
            "SELECT estado, observacion, usuario_id, fecha FROM HISTORIAL_ESTADO WHERE envio_id = %s ORDER BY id ASC",
            (envio_id,),
        )
        historial = cur.fetchall()
        for h in historial:
            h["fecha"] = fecha_iso(h["fecha"])
        envio["historial_estados"] = historial

        return jsonify(envio), 200
    finally:
        cur.close()
        db.close()


@app.post("/envios/<int:envio_id>/estado")
def cambiar_estado(envio_id):
    sin_permiso = requiere_permiso("logistica.gestionar")
    if sin_permiso:
        return sin_permiso

    data = request.get_json(silent=True) or {}
    nuevo = data.get("estado")

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT estado_actual FROM ENVIO WHERE id = %s", (envio_id,))
        envio = cur.fetchone()
        if not envio:
            return error_response("NO_ENCONTRADO", "Envio no existe", 404)

        actual = envio["estado_actual"]
        if nuevo not in TRANSICIONES.get(actual, []):
            return error_response("TRANSICION_INVALIDA", f"No se puede pasar de {actual} a {nuevo}", 409)

        cur.execute("UPDATE ENVIO SET estado_actual = %s WHERE id = %s", (nuevo, envio_id))
        cur.execute(
            "INSERT INTO HISTORIAL_ESTADO (envio_id, estado, observacion, usuario_id) VALUES (%s, %s, %s, %s)",
            (envio_id, nuevo, data.get("observacion"), usuario_actual_id()),
        )
        db.commit()
        return jsonify(leer_envio(cur, envio_id)), 200
    except MySQLError as e:
        db.rollback()
        return error_response("ERROR_BD", str(e), 500)
    finally:
        cur.close()
        db.close()


@app.post("/envios/<int:envio_id>/insumos")
def registrar_insumos(envio_id):
    sin_permiso = requiere_permiso("logistica.gestionar")
    if sin_permiso:
        return sin_permiso

    data = request.get_json(silent=True) or {}
    insumos = data.get("insumos") or []
    if len(insumos) == 0:
        return error_response("VALIDACION_FALLIDA", "Debe enviar al menos un insumo", 422)

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM ENVIO WHERE id = %s", (envio_id,))
        if not cur.fetchone():
            return error_response("NO_ENCONTRADO", "Envio no existe", 404)

        # Se validan todas las líneas antes de pedir cualquier salida a Inventarios.
        for linea in insumos:
            cantidad = linea.get("cantidad")
            if (not linea.get("producto_id") or not linea.get("bodega_id")
                    or not isinstance(cantidad, int) or isinstance(cantidad, bool) or cantidad < 1):
                return error_response("VALIDACION_FALLIDA", "Cada insumo necesita producto_id, bodega_id y cantidad >= 1", 422)

        # Cada SALIDA que Inventarios confirma se guarda de inmediato (commit por línea). Así, si una línea
        # falla, las anteriores no quedan descontadas en Inventarios sin su registro aquí.
        creados = []
        for linea in insumos:
            producto_id, bodega_id, cantidad = linea["producto_id"], linea["bodega_id"], linea["cantidad"]
            try:
                mov_id = registrar_salida(producto_id, bodega_id, cantidad, envio_id)
            except (SinStock, InventariosCaido) as fallo:
                pendientes = insumos[len(creados):]
                detalles = [{"insumos_registrados": creados, "insumos_pendientes": pendientes}]
                if isinstance(fallo, SinStock):
                    return error_response("STOCK_INSUFICIENTE", "Stock insuficiente en Inventarios", 409, detalles)
                return error_response("INVENTARIOS_NO_DISPONIBLE", "Inventarios no disponible", 502, detalles)

            cur.execute(
                "INSERT INTO ENVIO_INSUMO (envio_id, producto_id, cantidad, movimiento_salida_id) "
                "VALUES (%s, %s, %s, %s)",
                (envio_id, producto_id, cantidad, mov_id),
            )
            db.commit()
            creados.append({"id": cur.lastrowid, "envio_id": envio_id, "producto_id": producto_id,
                            "cantidad": cantidad, "movimiento_salida_id": mov_id})

        return jsonify(creados), 201
    except MySQLError as e:
        db.rollback()
        return error_response("ERROR_BD", str(e), 500)
    finally:
        cur.close()
        db.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
