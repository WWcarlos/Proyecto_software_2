import hmac
import json
import os
import urllib.error
import urllib.request
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
import mysql.connector
from mysql.connector import Error as MySQLError, errorcode

load_dotenv()

app = Flask(__name__)

DB_HOST = os.getenv("DB_HOST", "inventarios-db")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "clave")
DB_NAME = os.getenv("DB_NAME", "bd_inventarios")
API_TOKEN = os.getenv("token", "mi-token-super-secreto")

ANALITICA_URL = os.getenv("ANALITICA_URL", "http://analitica:8000")
VALIDAR_PRODUCTO = os.getenv("VALIDAR_PRODUCTO", "false").lower() == "true"
PRODUCTOS_URL = os.getenv("PRODUCTOS_URL", "http://productos:8000")


def get_db():
    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )


def error_response(codigo, mensaje, status_code, detalles=None):
    return jsonify({
        "codigo": codigo,
        "mensaje": mensaje,
        "detalles": detalles or []
    }), status_code


def es_entero_positivo(valor):
    return isinstance(valor, int) and not isinstance(valor, bool) and valor > 0


# =====================================================================
# MIDDLEWARE DE SEGURIDAD (Compatible con Gateway y pruebas directas)
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


def obtener_usuario_id():
    raw_id = request.headers.get("X-Usuario-Id", "1")
    try:
        return int(raw_id)
    except ValueError:
        return 1


def producto_existe(producto_id):
    if not VALIDAR_PRODUCTO:
        return True
    req = urllib.request.Request(
        f"{PRODUCTOS_URL}/{producto_id}",
        headers={"X-Service-Token": API_TOKEN},
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        return True
    except Exception:
        return True


def publicar_evento_analitica(movimiento):
    payload = json.dumps({
        "evento_id": f"mov-{movimiento['id']}",
        "tipo_evento": "movimiento.registrado",
        "datos": movimiento,
    }, default=str).encode("utf-8")

    req = urllib.request.Request(
        f"{ANALITICA_URL}/eventos",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Service-Token": API_TOKEN,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=2):
            pass
    except Exception:
        pass


def serializar_saldo(row):
    return {
        "producto_id": row["producto_id"],
        "bodega_id": row["bodega_id"],
        "cantidad_disponible": row["cantidad_disponible"],
        "stock_minimo": row["stock_minimo"],
        "bajo_minimo": bool(row["cantidad_disponible"] < row["stock_minimo"]),
        "actualizado_en": row["actualizado_en"].isoformat() if row["actualizado_en"] else None,
    }


def serializar_movimiento(row):
    return {
        "id": row["id"],
        "tipo": row["tipo"],
        "producto_id": row["producto_id"],
        "cantidad": row["cantidad"],
        "bodega_origen_id": row["bodega_origen_id"],
        "bodega_destino_id": row["bodega_destino_id"],
        "motivo": row["motivo"],
        "referencia_tipo": row["referencia_tipo"],
        "referencia_id": row["referencia_id"],
        "usuario_id": row["usuario_id"],
        "fecha": row["fecha"].isoformat() if row["fecha"] else None,
    }


# =====================================================================
# SALUD Y DOCUMENTACIÓN OPENAPI / SWAGGER
# =====================================================================
@app.get("/health")
def health():
    return jsonify(status="ok", servicio="inventarios"), 200


@app.get("/openapi.yaml")
def openapi_spec():
    return send_from_directory(".", "inventarios.yaml", mimetype="text/yaml")


@app.get("/docs")
def swagger_ui():
    return """<!DOCTYPE html>
<html>
<head>
  <title>API Inventarios - Swagger</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>SwaggerUIBundle({ url: 'openapi.yaml', dom_id: '#swagger-ui' });</script>
</body>
</html>""", 200, {"Content-Type": "text/html"}


# =====================================================================
# 1. BODEGAS (/bodegas)
# =====================================================================
@app.get("/bodegas")
def listar_bodegas():
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, codigo, nombre, ubicacion, activa FROM BODEGA ORDER BY id ASC")
        filas = cur.fetchall()
        resultado = [
            {
                "id": f["id"],
                "codigo": f["codigo"],
                "nombre": f["nombre"],
                "ubicacion": f["ubicacion"],
                "activa": bool(f["activa"]),
            }
            for f in filas
        ]
        return jsonify(resultado), 200
    finally:
        cur.close()
        db.close()


@app.post("/bodegas")
def crear_bodega():
    data = request.get_json(silent=True) or {}
    codigo = (data.get("codigo") or "").strip()
    nombre = (data.get("nombre") or "").strip()
    ubicacion = (data.get("ubicacion") or "").strip() or None

    if not codigo or not nombre:
        return error_response("VALIDACION_FALLIDA", "codigo y nombre son obligatorios", 422)

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "INSERT INTO BODEGA (codigo, nombre, ubicacion, activa) VALUES (%s, %s, %s, TRUE)",
            (codigo, nombre, ubicacion),
        )
        db.commit()
        return jsonify({
            "id": cur.lastrowid,
            "codigo": codigo,
            "nombre": nombre,
            "ubicacion": ubicacion,
            "activa": True,
        }), 201
    except MySQLError as e:
        db.rollback()
        if e.errno == errorcode.ER_DUP_ENTRY:
            return error_response("CODIGO_DUPLICADO", "Código ya existe", 409)
        return error_response("ERROR_BD", str(e), 500)
    finally:
        cur.close()
        db.close()


# =====================================================================
# 2. SALDOS Y ALERTAS (/saldos, /alertas/stock-minimo)
# =====================================================================
@app.get("/saldos")
def consultar_saldos():
    producto_id = request.args.get("producto_id", type=int)
    bodega_id = request.args.get("bodega_id", type=int)

    sql = "SELECT producto_id, bodega_id, cantidad_disponible, stock_minimo, actualizado_en FROM SALDO WHERE 1=1"
    params = []

    if producto_id is not None:
        sql += " AND producto_id = %s"
        params.append(producto_id)
    if bodega_id is not None:
        sql += " AND bodega_id = %s"
        params.append(bodega_id)

    sql += " ORDER BY bodega_id ASC, producto_id ASC"

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        filas = cur.fetchall()
        return jsonify([serializar_saldo(f) for f in filas]), 200
    finally:
        cur.close()
        db.close()


@app.put("/saldos/<int:producto_id>/<int:bodega_id>/stock-minimo")
def definir_stock_minimo(producto_id, bodega_id):
    data = request.get_json(silent=True) or {}
    stock_minimo = data.get("stock_minimo")

    if not isinstance(stock_minimo, int) or isinstance(stock_minimo, bool) or stock_minimo < 0:
        return error_response("VALIDACION_FALLIDA", "stock_minimo debe ser un entero >= 0", 422)

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM BODEGA WHERE id = %s", (bodega_id,))
        if not cur.fetchone():
            return error_response("BODEGA_NO_EXISTE", "La bodega indicada no existe", 404)

        cur.execute(
            "SELECT id FROM SALDO WHERE producto_id = %s AND bodega_id = %s",
            (producto_id, bodega_id),
        )
        saldo = cur.fetchone()

        if saldo:
            cur.execute(
                "UPDATE SALDO SET stock_minimo = %s WHERE id = %s",
                (stock_minimo, saldo["id"]),
            )
        else:
            cur.execute(
                "INSERT INTO SALDO (producto_id, bodega_id, cantidad_disponible, stock_minimo) VALUES (%s, %s, 0, %s)",
                (producto_id, bodega_id, stock_minimo),
            )
        db.commit()

        cur.execute(
            "SELECT producto_id, bodega_id, cantidad_disponible, stock_minimo, actualizado_en "
            "FROM SALDO WHERE producto_id = %s AND bodega_id = %s",
            (producto_id, bodega_id),
        )
        actualizado = cur.fetchone()
        return jsonify(serializar_saldo(actualizado)), 200
    except MySQLError as e:
        db.rollback()
        return error_response("ERROR_BD", str(e), 500)
    finally:
        cur.close()
        db.close()


@app.get("/alertas/stock-minimo")
def alertas_stock_minimo():
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT producto_id, bodega_id, cantidad_disponible, stock_minimo, actualizado_en "
            "FROM SALDO WHERE cantidad_disponible < stock_minimo ORDER BY bodega_id ASC, producto_id ASC"
        )
        filas = cur.fetchall()
        return jsonify([serializar_saldo(f) for f in filas]), 200
    finally:
        cur.close()
        db.close()


# =====================================================================
# 3. MOVIMIENTOS Y KARDEX (/movimientos)
# =====================================================================
@app.get("/movimientos")
def consultar_movimientos():
    producto_id = request.args.get("producto_id", type=int)
    bodega_id = request.args.get("bodega_id", type=int)
    tipo = request.args.get("tipo")
    referencia_tipo = request.args.get("referencia_tipo")
    referencia_id = request.args.get("referencia_id", type=int)
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")

    sql = (
        "SELECT id, tipo, producto_id, cantidad, bodega_origen_id, bodega_destino_id, "
        "motivo, referencia_tipo, referencia_id, usuario_id, fecha FROM MOVIMIENTO WHERE 1=1"
    )
    params = []

    if producto_id is not None:
        sql += " AND producto_id = %s"
        params.append(producto_id)
    if bodega_id is not None:
        sql += " AND (bodega_origen_id = %s OR bodega_destino_id = %s)"
        params.extend([bodega_id, bodega_id])
    if tipo:
        sql += " AND tipo = %s"
        params.append(tipo)
    if referencia_tipo:
        sql += " AND referencia_tipo = %s"
        params.append(referencia_tipo)
    if referencia_id is not None:
        sql += " AND referencia_id = %s"
        params.append(referencia_id)
    if desde:
        sql += " AND fecha >= %s"
        params.append(desde)
    if hasta:
        sql += " AND fecha <= %s"
        params.append(hasta)

    sql += " ORDER BY fecha DESC, id DESC"

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        filas = cur.fetchall()
        return jsonify([serializar_movimiento(f) for f in filas]), 200
    finally:
        cur.close()
        db.close()


@app.get("/movimientos/<int:movimiento_id>")
def obtener_movimiento(movimiento_id):
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, tipo, producto_id, cantidad, bodega_origen_id, bodega_destino_id, "
            "motivo, referencia_tipo, referencia_id, usuario_id, fecha FROM MOVIMIENTO WHERE id = %s",
            (movimiento_id,),
        )
        fila = cur.fetchone()
        if not fila:
            return error_response("NO_ENCONTRADO", "Movimiento no existe", 404)
        return jsonify(serializar_movimiento(fila)), 200
    finally:
        cur.close()
        db.close()


@app.post("/movimientos")
def registrar_movimiento():
    data = request.get_json(silent=True) or {}

    tipo = data.get("tipo")
    producto_id = data.get("producto_id")
    cantidad = data.get("cantidad")
    bodega_origen_id = data.get("bodega_origen_id")
    bodega_destino_id = data.get("bodega_destino_id")
    motivo = (data.get("motivo") or "").strip() or None
    referencia_tipo = data.get("referencia_tipo")
    referencia_id = data.get("referencia_id")
    usuario_id = obtener_usuario_id()

    tipos_validos = ("ENTRADA", "SALIDA", "AJUSTE", "TRASLADO", "DEVOLUCION")
    refs_validas = (None, "ORDEN_COMPRA", "ENVIO", "AJUSTE_MANUAL")

    if tipo not in tipos_validos:
        return error_response("VALIDACION_FALLIDA", f"tipo debe ser uno de {tipos_validos}", 422)
    if not es_entero_positivo(producto_id):
        return error_response("VALIDACION_FALLIDA", "producto_id debe ser un entero positivo", 422)
    if not es_entero_positivo(cantidad):
        return error_response("VALIDACION_FALLIDA", "cantidad debe ser un entero >= 1", 422)
    if referencia_tipo not in refs_validas:
        return error_response("VALIDACION_FALLIDA", "referencia_tipo inválido", 422)
    if bodega_origen_id is not None and not es_entero_positivo(bodega_origen_id):
        return error_response("VALIDACION_FALLIDA", "bodega_origen_id debe ser un entero positivo", 422)
    if bodega_destino_id is not None and not es_entero_positivo(bodega_destino_id):
        return error_response("VALIDACION_FALLIDA", "bodega_destino_id debe ser un entero positivo", 422)

    if tipo == "ENTRADA" and not bodega_destino_id:
        return error_response("VALIDACION_FALLIDA", "ENTRADA requiere bodega_destino_id", 422)
    if tipo == "SALIDA" and not bodega_origen_id:
        return error_response("VALIDACION_FALLIDA", "SALIDA requiere bodega_origen_id", 422)
    if tipo == "TRASLADO":
        if not bodega_origen_id or not bodega_destino_id:
            return error_response("VALIDACION_FALLIDA", "TRASLADO requiere bodega_origen_id y bodega_destino_id", 422)
        if bodega_origen_id == bodega_destino_id:
            return error_response("VALIDACION_FALLIDA", "La bodega origen y destino no pueden ser iguales", 422)
    if tipo in ("AJUSTE", "DEVOLUCION"):
        if bool(bodega_origen_id) == bool(bodega_destino_id):
            return error_response(
                "VALIDACION_FALLIDA",
                f"{tipo} requiere exactamente bodega_origen_id (salida) o bodega_destino_id (entrada)",
                422,
            )

    if not producto_existe(producto_id):
        return error_response("VALIDACION_FALLIDA", f"El producto {producto_id} no existe", 422)

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        db.start_transaction()

        for bid in (bodega_origen_id, bodega_destino_id):
            if bid is not None:
                cur.execute("SELECT id FROM BODEGA WHERE id = %s", (bid,))
                if not cur.fetchone():
                    db.rollback()
                    return error_response("VALIDACION_FALLIDA", f"La bodega {bid} no existe", 422)

        if bodega_origen_id is not None:
            cur.execute(
                "SELECT id, cantidad_disponible FROM SALDO "
                "WHERE producto_id = %s AND bodega_id = %s FOR UPDATE",
                (producto_id, bodega_origen_id),
            )
            saldo_origen = cur.fetchone()
            disponible = saldo_origen["cantidad_disponible"] if saldo_origen else 0

            if disponible < cantidad:
                db.rollback()
                return error_response(
                    "STOCK_INSUFICIENTE",
                    f"Stock insuficiente en bodega {bodega_origen_id}. Disponible: {disponible}, solicitado: {cantidad}",
                    409,
                    [{"producto_id": producto_id, "bodega_id": bodega_origen_id, "disponible": disponible}],
                )

            cur.execute(
                "UPDATE SALDO SET cantidad_disponible = cantidad_disponible - %s WHERE id = %s",
                (cantidad, saldo_origen["id"]),
            )

        if bodega_destino_id is not None:
            cur.execute(
                "SELECT id FROM SALDO WHERE producto_id = %s AND bodega_id = %s FOR UPDATE",
                (producto_id, bodega_destino_id),
            )
            saldo_destino = cur.fetchone()

            if saldo_destino:
                cur.execute(
                    "UPDATE SALDO SET cantidad_disponible = cantidad_disponible + %s WHERE id = %s",
                    (cantidad, saldo_destino["id"]),
                )
            else:
                cur.execute(
                    "INSERT INTO SALDO (producto_id, bodega_id, cantidad_disponible, stock_minimo) "
                    "VALUES (%s, %s, %s, 0)",
                    (producto_id, bodega_destino_id, cantidad),
                )

        cur.execute(
            "INSERT INTO MOVIMIENTO (tipo, producto_id, cantidad, bodega_origen_id, bodega_destino_id, "
            "motivo, referencia_tipo, referencia_id, usuario_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                tipo,
                producto_id,
                cantidad,
                bodega_origen_id,
                bodega_destino_id,
                motivo,
                referencia_tipo,
                referencia_id,
                usuario_id,
            ),
        )
        nuevo_id = cur.lastrowid
        db.commit()

        cur.execute(
            "SELECT id, tipo, producto_id, cantidad, bodega_origen_id, bodega_destino_id, "
            "motivo, referencia_tipo, referencia_id, usuario_id, fecha FROM MOVIMIENTO WHERE id = %s",
            (nuevo_id,),
        )
        creado = serializar_movimiento(cur.fetchone())
        publicar_evento_analitica(creado)
        return jsonify(creado), 201

    except MySQLError as e:
        db.rollback()
        return error_response("ERROR_BD", str(e), 500)
    finally:
        cur.close()
        db.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)