import hmac
import os
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
import mysql.connector
from mysql.connector import Error as MySQLError, errorcode

load_dotenv()

app = Flask(__name__)

DB_HOST = os.getenv("DB_HOST", "mysql-proveedores")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "clave")
DB_NAME = os.getenv("DB_NAME", "bd_proveedores")
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
    return jsonify({"codigo": codigo, "mensaje": mensaje, "detalles": detalles or []}), status_code


def serializar(f):
    return {
        "id": f["id"], "nit": f["nit"], "razon_social": f["razon_social"],
        "contacto_nombre": f["contacto_nombre"], "email": f["email"], "telefono": f["telefono"],
        "direccion": f["direccion"], "condiciones_pago": f["condiciones_pago"],
        "plazo_entrega_dias": f["plazo_entrega_dias"], "activo": bool(f["activo"]),
    }


# MIDDLEWARE DE SEGURIDAD (token de servicio)
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


# SALUD Y DOCUMENTACIÓN
@app.get("/health")
def health():
    return jsonify(status="ok", servicio="proveedores"), 200


@app.get("/openapi.yaml")
def openapi_spec():
    return send_from_directory(".", "proveedores.yaml", mimetype="text/yaml")


@app.get("/docs")
def swagger_ui():
    return """<!DOCTYPE html>
<html>
<head>
  <title>API Proveedores - Swagger</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>SwaggerUIBundle({ url: '/openapi.yaml', dom_id: '#swagger-ui' });</script>
</body>
</html>""", 200, {"Content-Type": "text/html"}


# PROVEEDORES
@app.get("/")
def listar_proveedores():
    activo = request.args.get("activo")
    q = request.args.get("q")

    sql = ("SELECT id, nit, razon_social, contacto_nombre, email, telefono, direccion, "
           "condiciones_pago, plazo_entrega_dias, activo FROM PROVEEDOR WHERE 1=1")
    params = []
    if activo is not None:
        sql += " AND activo = %s"
        params.append(1 if activo.lower() == "true" else 0)
    if q:
        sql += " AND (razon_social LIKE %s OR nit LIKE %s)"
        params.extend([f"%{q}%", f"%{q}%"])
    sql += " ORDER BY id ASC"

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return jsonify([serializar(f) for f in cur.fetchall()]), 200
    finally:
        cur.close()
        db.close()


@app.post("/")
def crear_proveedor():
    data = request.get_json(silent=True) or {}
    nit = (data.get("nit") or "").strip()
    razon_social = (data.get("razon_social") or "").strip()

    if not nit or not razon_social:
        return error_response("VALIDACION_FALLIDA", "nit y razon_social son obligatorios", 422)

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "INSERT INTO PROVEEDOR (nit, razon_social, contacto_nombre, email, telefono, direccion, "
            "condiciones_pago, plazo_entrega_dias, activo) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)",
            (nit, razon_social, data.get("contacto_nombre"), data.get("email"), data.get("telefono"),
             data.get("direccion"), data.get("condiciones_pago"), data.get("plazo_entrega_dias")),
        )
        db.commit()
        nuevo_id = cur.lastrowid
    except MySQLError as e:
        db.rollback()
        if e.errno == errorcode.ER_DUP_ENTRY:
            return error_response("NIT_DUPLICADO", "NIT ya registrado", 409)
        return error_response("ERROR_BD", str(e), 500)
    finally:
        cur.close()
        db.close()

    return obtener_proveedor(nuevo_id)


@app.get("/<int:proveedor_id>")
def obtener_proveedor(proveedor_id):
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, nit, razon_social, contacto_nombre, email, telefono, direccion, "
            "condiciones_pago, plazo_entrega_dias, activo FROM PROVEEDOR WHERE id = %s",
            (proveedor_id,),
        )
        f = cur.fetchone()
        if not f:
            return error_response("NO_ENCONTRADO", "Proveedor no existe", 404)
        return jsonify(serializar(f)), 200
    finally:
        cur.close()
        db.close()


@app.put("/<int:proveedor_id>")
def actualizar_proveedor(proveedor_id):
    data = request.get_json(silent=True) or {}
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM PROVEEDOR WHERE id = %s", (proveedor_id,))
        if not cur.fetchone():
            return error_response("NO_ENCONTRADO", "Proveedor no existe", 404)

        cur.execute(
            "UPDATE PROVEEDOR SET razon_social = %s, contacto_nombre = %s, email = %s, telefono = %s, "
            "direccion = %s, condiciones_pago = %s, plazo_entrega_dias = %s WHERE id = %s",
            (data.get("razon_social"), data.get("contacto_nombre"), data.get("email"),
             data.get("telefono"), data.get("direccion"), data.get("condiciones_pago"),
             data.get("plazo_entrega_dias"), proveedor_id),
        )
        db.commit()
        cur.execute(
            "SELECT id, nit, razon_social, contacto_nombre, email, telefono, direccion, "
            "condiciones_pago, plazo_entrega_dias, activo FROM PROVEEDOR WHERE id = %s",
            (proveedor_id,),
        )
        return jsonify(serializar(cur.fetchone())), 200
    except MySQLError as e:
        db.rollback()
        return error_response("ERROR_BD", str(e), 500)
    finally:
        cur.close()
        db.close()


@app.patch("/<int:proveedor_id>/estado")
def cambiar_estado(proveedor_id):
    data = request.get_json(silent=True) or {}
    activo = data.get("activo")
    if not isinstance(activo, bool):
        return error_response("VALIDACION_FALLIDA", "activo debe ser true o false", 422)

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM PROVEEDOR WHERE id = %s", (proveedor_id,))
        if not cur.fetchone():
            return error_response("NO_ENCONTRADO", "Proveedor no existe", 404)

        cur.execute("UPDATE PROVEEDOR SET activo = %s WHERE id = %s", (activo, proveedor_id))
        db.commit()
        cur.execute(
            "SELECT id, nit, razon_social, contacto_nombre, email, telefono, direccion, "
            "condiciones_pago, plazo_entrega_dias, activo FROM PROVEEDOR WHERE id = %s",
            (proveedor_id,),
        )
        return jsonify(serializar(cur.fetchone())), 200
    except MySQLError as e:
        db.rollback()
        return error_response("ERROR_BD", str(e), 500)
    finally:
        cur.close()
        db.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
