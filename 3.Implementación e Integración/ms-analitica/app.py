import csv
import hmac
import io
import json
import os
import uuid
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory
import mysql.connector
from mysql.connector import Error as MySQLError, errorcode

load_dotenv()

app = Flask(__name__)

DB_HOST = os.getenv("DB_HOST", "mysql-analitica")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "clave")
DB_NAME = os.getenv("DB_NAME", "bd_analitica")
API_TOKEN = os.getenv("token", "mi-token-super-secreto")


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


def serializar_indicador(row):
    return {
        "nombre": row["nombre"],
        "valor": float(row["valor"]),
        "unidad": row["unidad"],
        "actualizado_en": row["actualizado_en"].isoformat() if row["actualizado_en"] else None,
    }


# =====================================================================
# SALUD Y DOCUMENTACIÓN OPENAPI / SWAGGER
# =====================================================================
@app.get("/health")
def health():
    return jsonify(status="ok", servicio="analitica"), 200


@app.get("/openapi.yaml")
def openapi_spec():
    return send_from_directory(".", "analitica.yaml", mimetype="text/yaml")


@app.get("/docs")
def swagger_ui():
    return """<!DOCTYPE html>
<html>
<head>
  <title>API Analitica - Swagger</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>SwaggerUIBundle({ url: '/openapi.yaml', dom_id: '#swagger-ui' });</script>
</body>
</html>""", 200, {"Content-Type": "text/html"}


# =====================================================================
# 1. RECEPCIÓN DE EVENTOS DE DOMINIO (POST /eventos)
# =====================================================================
@app.post("/eventos")
def recibir_evento():
    data = request.get_json(silent=True) or {}
    tipo_evento = (data.get("tipo_evento") or "").strip()
    evento_id = (data.get("evento_id") or str(uuid.uuid4())).strip()
    datos = data.get("datos") if isinstance(data.get("datos"), dict) else data

    eventos_validos = ("movimiento.registrado", "orden.recibida", "envio.creado", "stock.bajo")
    if tipo_evento not in eventos_validos:
        return error_response(
            "VALIDACION_FALLIDA",
            f"tipo_evento debe ser uno de {eventos_validos}",
            422,
        )

    producto_id = datos.get("producto_id")
    bodega_id = datos.get("bodega_destino_id") or datos.get("bodega_origen_id") or datos.get("bodega_id")
    tipo_movimiento = datos.get("tipo")

    try:
        cantidad = int(datos.get("cantidad") or 0)
    except (ValueError, TypeError):
        return error_response("VALIDACION_FALLIDA", "cantidad debe ser numérica", 422)

    db = get_db()
    cur = db.cursor()
    try:
        db.start_transaction()

        cur.execute(
            "INSERT INTO EVENTO_RECIBIDO (evento_id, tipo_evento, producto_id, bodega_id, cantidad, tipo_movimiento, payload) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                evento_id,
                tipo_evento,
                producto_id,
                bodega_id,
                cantidad,
                tipo_movimiento,
                json.dumps(data, default=str),
            ),
        )

        if tipo_evento == "movimiento.registrado":
            cur.execute(
                "UPDATE INDICADOR SET valor = valor + %s WHERE nombre = 'ROTACION_INVENTARIO'",
                (abs(cantidad),),
            )
        elif tipo_evento == "envio.creado":
            cur.execute(
                "UPDATE INDICADOR SET valor = valor + 1 WHERE nombre = 'ENVIOS_DIA'"
            )
        elif tipo_evento == "stock.bajo":
            cur.execute(
                "UPDATE INDICADOR SET valor = %s WHERE nombre = 'STOCK_BAJO'",
                (int(datos.get("total_alertas", 1)),),
            )

        db.commit()
        return jsonify({"mensaje": "Evento procesado", "evento_id": evento_id}), 201

    except MySQLError as e:
        db.rollback()
        if e.errno == errorcode.ER_DUP_ENTRY:
            return jsonify({"mensaje": "Evento ya procesado previamente", "evento_id": evento_id}), 200
        return error_response("ERROR_BD", str(e), 500)
    finally:
        cur.close()
        db.close()


# =====================================================================
# 2. INDICADORES (/indicadores)
# =====================================================================
@app.get("/indicadores")
def listar_indicadores():
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT nombre, valor, unidad, actualizado_en FROM INDICADOR ORDER BY id ASC")
        filas = cur.fetchall()
        return jsonify([serializar_indicador(f) for f in filas]), 200
    finally:
        cur.close()
        db.close()


@app.get("/indicadores/<string:nombre>")
def obtener_indicador(nombre):
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT nombre, valor, unidad, actualizado_en FROM INDICADOR WHERE nombre = %s",
            (nombre.upper(),),
        )
        fila = cur.fetchone()
        if not fila:
            return error_response("NO_ENCONTRADO", f"El indicador '{nombre}' no existe", 404)
        return jsonify(serializar_indicador(fila)), 200
    finally:
        cur.close()
        db.close()


# =====================================================================
# 3. REPORTES DE INVENTARIO (/reportes/inventario?formato=json|csv)
# =====================================================================
@app.get("/reportes/inventario")
def reporte_inventario():
    formato = (request.args.get("formato") or "json").lower()
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    bodega_id = request.args.get("bodega_id", type=int)

    if formato not in ("json", "csv"):
        return error_response("VALIDACION_FALLIDA", "formato debe ser 'json' o 'csv'", 422)

    sql = (
        "SELECT producto_id, bodega_id, tipo_movimiento, "
        "COUNT(*) AS total_operaciones, COALESCE(SUM(cantidad), 0) AS unidades_totales, "
        "MAX(recibido_en) AS ultimo_movimiento "
        "FROM EVENTO_RECIBIDO WHERE tipo_evento = 'movimiento.registrado'"
    )
    params = []

    if bodega_id is not None:
        sql += " AND bodega_id = %s"
        params.append(bodega_id)
    if desde:
        sql += " AND recibido_en >= %s"
        params.append(desde)
    if hasta:
        sql += " AND recibido_en <= %s"
        params.append(hasta)

    sql += " GROUP BY producto_id, bodega_id, tipo_movimiento ORDER BY bodega_id ASC, producto_id ASC"

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        filas = cur.fetchall()

        registros = [
            {
                "producto_id": f["producto_id"],
                "bodega_id": f["bodega_id"],
                "tipo_movimiento": f["tipo_movimiento"],
                "total_operaciones": int(f["total_operaciones"]),
                "unidades_totales": int(f["unidades_totales"]),
                "ultimo_movimiento": f["ultimo_movimiento"].isoformat() if f["ultimo_movimiento"] else None,
            }
            for f in filas
        ]

        if formato == "json":
            return jsonify({"total_filas": len(registros), "datos": registros}), 200

        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "producto_id",
                "bodega_id",
                "tipo_movimiento",
                "total_operaciones",
                "unidades_totales",
                "ultimo_movimiento",
            ],
        )
        writer.writeheader()
        writer.writerows(registros)

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=reporte_inventario.csv"},
        )
    finally:
        cur.close()
        db.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)