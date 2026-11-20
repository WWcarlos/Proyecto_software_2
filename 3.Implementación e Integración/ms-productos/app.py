import hmac
import os
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
import mysql.connector
from mysql.connector import Error as MySQLError, errorcode

load_dotenv()

app = Flask(__name__)

DB_HOST = os.getenv("DB_HOST", "mysql-productos")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "clave")
DB_NAME = os.getenv("DB_NAME", "bd_productos")
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
    return jsonify(status="ok", servicio="productos"), 200


@app.get("/openapi.yaml")
def openapi_spec():
    return send_from_directory(".", "productos.yaml", mimetype="text/yaml")


@app.get("/docs")
def swagger_ui():
    return """<!DOCTYPE html>
<html>
<head>
  <title>API Productos - Swagger</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>SwaggerUIBundle({ url: '/openapi.yaml', dom_id: '#swagger-ui' });</script>
</body>
</html>""", 200, {"Content-Type": "text/html"}


#PRODUCTOS
@app.get("/")
def listar_productos():
    q = request.args.get("q")
    categoria_id = request.args.get("categoria_id", type=int)
    page = request.args.get("page", default=1, type=int)
    size = request.args.get("size", default=20, type=int)
    if size > 100:
        size = 100

    sql = "SELECT id, sku, nombre, descripcion, categoria_id, unidad_medida_id, activo FROM PRODUCTO WHERE 1=1"
    params = []
    if categoria_id is not None:
        sql += " AND categoria_id = %s"
        params.append(categoria_id)
    if q:
        sql += " AND (nombre LIKE %s OR sku LIKE %s)"
        params.extend([f"%{q}%", f"%{q}%"])

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT COUNT(*) AS total FROM (" + sql + ") AS t", params)
        total = cur.fetchone()["total"]

        sql += " ORDER BY id ASC LIMIT %s OFFSET %s"
        params.extend([size, (page - 1) * size])
        cur.execute(sql, params)
        filas = cur.fetchall()
        items = [
            {
                "id": f["id"], "sku": f["sku"], "nombre": f["nombre"],
                "descripcion": f["descripcion"], "categoria_id": f["categoria_id"],
                "unidad_medida_id": f["unidad_medida_id"], "activo": bool(f["activo"]),
            }
            for f in filas
        ]
        return jsonify({"items": items, "total": total, "page": page, "size": size}), 200
    finally:
        cur.close()
        db.close()


@app.post("/")
def crear_producto():
    data = request.get_json(silent=True) or {}
    sku = (data.get("sku") or "").strip()
    nombre = (data.get("nombre") or "").strip()
    categoria_id = data.get("categoria_id")
    unidad_medida_id = data.get("unidad_medida_id")

    if not sku or not nombre or not categoria_id or not unidad_medida_id:
        return error_response("VALIDACION_FALLIDA",
                              "sku, nombre, categoria_id y unidad_medida_id son obligatorios", 422)

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "INSERT INTO PRODUCTO (sku, nombre, descripcion, categoria_id, unidad_medida_id, activo) "
            "VALUES (%s, %s, %s, %s, %s, TRUE)",
            (sku, nombre, data.get("descripcion"), categoria_id, unidad_medida_id),
        )
        db.commit()
        return jsonify({
            "id": cur.lastrowid, "sku": sku, "nombre": nombre,
            "descripcion": data.get("descripcion"), "categoria_id": categoria_id,
            "unidad_medida_id": unidad_medida_id, "activo": True,
        }), 201
    except MySQLError as e:
        db.rollback()
        if e.errno == errorcode.ER_DUP_ENTRY:
            return error_response("SKU_DUPLICADO", "SKU ya existe", 409)
        return error_response("ERROR_BD", str(e), 500)
    finally:
        cur.close()
        db.close()


@app.get("/<int:producto_id>")
def obtener_producto(producto_id):
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, sku, nombre, descripcion, categoria_id, unidad_medida_id, activo "
            "FROM PRODUCTO WHERE id = %s",
            (producto_id,),
        )
        f = cur.fetchone()
        if not f:
            return error_response("NO_ENCONTRADO", "Producto no existe", 404)
        return jsonify({
            "id": f["id"], "sku": f["sku"], "nombre": f["nombre"],
            "descripcion": f["descripcion"], "categoria_id": f["categoria_id"],
            "unidad_medida_id": f["unidad_medida_id"], "activo": bool(f["activo"]),
        }), 200
    finally:
        cur.close()
        db.close()


@app.put("/<int:producto_id>")
def actualizar_producto(producto_id):
    data = request.get_json(silent=True) or {}
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM PRODUCTO WHERE id = %s", (producto_id,))
        if not cur.fetchone():
            return error_response("NO_ENCONTRADO", "Producto no existe", 404)

        cur.execute(
            "UPDATE PRODUCTO SET nombre = %s, descripcion = %s, categoria_id = %s, unidad_medida_id = %s "
            "WHERE id = %s",
            (data.get("nombre"), data.get("descripcion"), data.get("categoria_id"),
             data.get("unidad_medida_id"), producto_id),
        )
        db.commit()
        cur.execute(
            "SELECT id, sku, nombre, descripcion, categoria_id, unidad_medida_id, activo "
            "FROM PRODUCTO WHERE id = %s",
            (producto_id,),
        )
        f = cur.fetchone()
        return jsonify({
            "id": f["id"], "sku": f["sku"], "nombre": f["nombre"],
            "descripcion": f["descripcion"], "categoria_id": f["categoria_id"],
            "unidad_medida_id": f["unidad_medida_id"], "activo": bool(f["activo"]),
        }), 200
    except MySQLError as e:
        db.rollback()
        return error_response("ERROR_BD", str(e), 500)
    finally:
        cur.close()
        db.close()


#CATEGORIAS
@app.get("/categorias")
def listar_categorias():
    padre_id = request.args.get("padre_id", type=int)
    sql = "SELECT id, nombre, padre_id, activa FROM CATEGORIA WHERE 1=1"
    params = []
    if padre_id is not None:
        sql += " AND padre_id = %s"
        params.append(padre_id)
    sql += " ORDER BY id ASC"

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        filas = cur.fetchall()
        return jsonify([
            {"id": f["id"], "nombre": f["nombre"], "padre_id": f["padre_id"], "activa": bool(f["activa"])}
            for f in filas
        ]), 200
    finally:
        cur.close()
        db.close()


@app.post("/categorias")
def crear_categoria():
    data = request.get_json(silent=True) or {}
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        return error_response("VALIDACION_FALLIDA", "nombre es obligatorio", 422)

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "INSERT INTO CATEGORIA (nombre, padre_id, activa) VALUES (%s, %s, TRUE)",
            (nombre, data.get("padre_id")),
        )
        db.commit()
        return jsonify({"id": cur.lastrowid, "nombre": nombre, "padre_id": data.get("padre_id"), "activa": True}), 201
    except MySQLError as e:
        db.rollback()
        return error_response("ERROR_BD", str(e), 500)
    finally:
        cur.close()
        db.close()


# UNIDADES DE MEDIDA
@app.get("/unidades-medida")
def listar_unidades():
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, codigo, nombre FROM UNIDAD_MEDIDA ORDER BY id ASC")
        filas = cur.fetchall()
        return jsonify([{"id": f["id"], "codigo": f["codigo"], "nombre": f["nombre"]} for f in filas]), 200
    finally:
        cur.close()
        db.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
