import hmac
import os
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
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

# Proveedores se consulta por REST para validar los proveedores asociados a un producto.
PROVEEDORES_URL = os.getenv("PROVEEDORES_URL", "http://proveedores:8000")

# Permiso que se exige para crear, modificar o dar de baja productos y categorías.
GESTIONAR = "productos.gestionar"

# Campos que se pueden modificar con PUT.
CAMPOS_EDITABLES = ("sku", "nombre", "descripcion", "categoria_id", "unidad_medida_id", "precio")
# Error cuando la categoría o la unidad de medida indicadas no existen (violación de clave foránea).
REFERENCIA_INVALIDA = ("VALIDACION_FALLIDA", "La categoría o la unidad de medida indicada no existe", 422)

COLUMNAS_PRODUCTO = "id, sku, nombre, descripcion, categoria_id, unidad_medida_id, precio, activo, creado_en"


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


def leer_precio(valor):
    """Convierte el precio a Decimal (>= 0, dos decimales). Devuelve None si no es válido."""
    if isinstance(valor, bool):
        return None
    try:
        precio = Decimal(str(valor)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    return precio if precio >= 0 else None


def leer_proveedor_ids(valor):
    """Lista de ids de proveedor (enteros positivos, sin repetir). Devuelve None si no es válida."""
    if not isinstance(valor, list):
        return None
    if any(not isinstance(v, int) or isinstance(v, bool) or v <= 0 for v in valor):
        return None
    return sorted(set(valor))


def verificar_proveedores(proveedor_ids):
    """Comprueba en el servicio de Proveedores que cada proveedor exista. Devuelve un error o None."""
    for proveedor_id in proveedor_ids:
        req = urllib.request.Request(f"{PROVEEDORES_URL}/{proveedor_id}", headers={"X-Service-Token": API_TOKEN})
        try:
            with urllib.request.urlopen(req, timeout=5):
                pass
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return error_response("VALIDACION_FALLIDA", f"El proveedor {proveedor_id} no existe", 422)
            return error_response("SERVICIO_NO_DISPONIBLE", f"Proveedores respondió {e.code}", 502)
        except Exception:
            return error_response("SERVICIO_NO_DISPONIBLE", "Proveedores no disponible", 502)
    return None


def proveedores_de(cur, producto_ids):
    """Devuelve {producto_id: [proveedor_id, ...]} para los productos indicados."""
    resultado = {pid: [] for pid in producto_ids}
    if not producto_ids:
        return resultado
    marcas = ", ".join(["%s"] * len(producto_ids))
    cur.execute(
        f"SELECT producto_id, proveedor_id FROM PRODUCTO_PROVEEDOR WHERE producto_id IN ({marcas}) "
        "ORDER BY proveedor_id",
        list(producto_ids),
    )
    for fila in cur.fetchall():
        resultado[fila["producto_id"]].append(fila["proveedor_id"])
    return resultado


def guardar_proveedores(cur, producto_id, proveedor_ids):
    """Reemplaza los proveedores asociados al producto."""
    cur.execute("DELETE FROM PRODUCTO_PROVEEDOR WHERE producto_id = %s", (producto_id,))
    for proveedor_id in proveedor_ids:
        cur.execute(
            "INSERT INTO PRODUCTO_PROVEEDOR (producto_id, proveedor_id) VALUES (%s, %s)",
            (producto_id, proveedor_id),
        )


def serializar(f, proveedor_ids):
    return {
        "id": f["id"], "sku": f["sku"], "nombre": f["nombre"],
        "descripcion": f["descripcion"], "categoria_id": f["categoria_id"],
        "unidad_medida_id": f["unidad_medida_id"], "precio": float(f["precio"]),
        "proveedor_ids": proveedor_ids, "activo": bool(f["activo"]),
        "creado_en": f["creado_en"].isoformat() if f["creado_en"] else None,
    }


def leer_producto(cur, producto_id):
    cur.execute(f"SELECT {COLUMNAS_PRODUCTO} FROM PRODUCTO WHERE id = %s", (producto_id,))
    f = cur.fetchone()
    if not f:
        return None
    return serializar(f, proveedores_de(cur, [producto_id])[producto_id])


def serializar_categoria(f):
    return {"id": f["id"], "nombre": f["nombre"], "padre_id": f["padre_id"], "activa": bool(f["activa"])}


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
  <script>SwaggerUIBundle({ url: 'openapi.yaml', dom_id: '#swagger-ui' });</script>
</body>
</html>""", 200, {"Content-Type": "text/html"}


#PRODUCTOS
@app.get("/")
def listar_productos():
    q = request.args.get("q")
    categoria_id = request.args.get("categoria_id", type=int)
    proveedor_id = request.args.get("proveedor_id", type=int)
    activo = request.args.get("activo")
    page = max(request.args.get("page", default=1, type=int), 1)
    size = request.args.get("size", default=20, type=int)
    if size > 100:
        size = 100

    sql = f"SELECT {COLUMNAS_PRODUCTO} FROM PRODUCTO WHERE 1=1"
    params = []
    if categoria_id is not None:
        sql += " AND categoria_id = %s"
        params.append(categoria_id)
    if proveedor_id is not None:
        sql += " AND id IN (SELECT producto_id FROM PRODUCTO_PROVEEDOR WHERE proveedor_id = %s)"
        params.append(proveedor_id)
    if activo is not None:
        sql += " AND activo = %s"
        params.append(1 if activo.lower() == "true" else 0)
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
        proveedores = proveedores_de(cur, [f["id"] for f in filas])
        items = [serializar(f, proveedores[f["id"]]) for f in filas]
        return jsonify({"items": items, "total": total, "page": page, "size": size}), 200
    finally:
        cur.close()
        db.close()


@app.post("/")
def crear_producto():
    sin_permiso = requiere_permiso(GESTIONAR)
    if sin_permiso:
        return sin_permiso

    data = request.get_json(silent=True) or {}
    sku = (data.get("sku") or "").strip()
    nombre = (data.get("nombre") or "").strip()
    categoria_id = data.get("categoria_id")
    unidad_medida_id = data.get("unidad_medida_id")

    if not sku or not nombre or not categoria_id or not unidad_medida_id:
        return error_response("VALIDACION_FALLIDA",
                              "sku, nombre, categoria_id y unidad_medida_id son obligatorios", 422)
    precio = leer_precio(data.get("precio", 0))
    if precio is None:
        return error_response("VALIDACION_FALLIDA", "precio debe ser un número >= 0", 422)
    proveedor_ids = leer_proveedor_ids(data.get("proveedor_ids", []))
    if proveedor_ids is None:
        return error_response("VALIDACION_FALLIDA", "proveedor_ids debe ser una lista de enteros positivos", 422)
    error_proveedor = verificar_proveedores(proveedor_ids)
    if error_proveedor:
        return error_proveedor

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "INSERT INTO PRODUCTO (sku, nombre, descripcion, categoria_id, unidad_medida_id, precio, activo) "
            "VALUES (%s, %s, %s, %s, %s, %s, TRUE)",
            (sku, nombre, data.get("descripcion"), categoria_id, unidad_medida_id, precio),
        )
        nuevo_id = cur.lastrowid
        guardar_proveedores(cur, nuevo_id, proveedor_ids)
        db.commit()
        return jsonify(leer_producto(cur, nuevo_id)), 201
    except MySQLError as e:
        db.rollback()
        if e.errno == errorcode.ER_DUP_ENTRY:
            return error_response("SKU_DUPLICADO", "SKU ya existe", 409)
        if e.errno == errorcode.ER_NO_REFERENCED_ROW_2:
            return error_response(*REFERENCIA_INVALIDA)
        return error_response("ERROR_BD", str(e), 500)
    finally:
        cur.close()
        db.close()


@app.get("/<int:producto_id>")
def obtener_producto(producto_id):
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        producto = leer_producto(cur, producto_id)
        if producto is None:
            return error_response("NO_ENCONTRADO", "Producto no existe", 404)
        return jsonify(producto), 200
    finally:
        cur.close()
        db.close()


@app.put("/<int:producto_id>")
def actualizar_producto(producto_id):
    sin_permiso = requiere_permiso(GESTIONAR)
    if sin_permiso:
        return sin_permiso

    data = request.get_json(silent=True) or {}
    # Solo se actualizan los campos que vienen en el cuerpo (actualización parcial).
    for obligatorio in ("sku", "nombre", "categoria_id", "unidad_medida_id"):
        if obligatorio in data and not data[obligatorio]:
            return error_response("VALIDACION_FALLIDA", f"{obligatorio} no puede estar vacío", 422)
    cambios = {campo: data[campo] for campo in CAMPOS_EDITABLES if campo in data}
    for campo in ("sku", "nombre"):
        if campo in cambios:
            cambios[campo] = str(cambios[campo]).strip()
    if "precio" in cambios:
        cambios["precio"] = leer_precio(cambios["precio"])
        if cambios["precio"] is None:
            return error_response("VALIDACION_FALLIDA", "precio debe ser un número >= 0", 422)
    proveedor_ids = None
    if "proveedor_ids" in data:
        proveedor_ids = leer_proveedor_ids(data["proveedor_ids"])
        if proveedor_ids is None:
            return error_response("VALIDACION_FALLIDA", "proveedor_ids debe ser una lista de enteros positivos", 422)

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM PRODUCTO WHERE id = %s", (producto_id,))
        if not cur.fetchone():
            return error_response("NO_ENCONTRADO", "Producto no existe", 404)

        if proveedor_ids is not None:
            error_proveedor = verificar_proveedores(proveedor_ids)
            if error_proveedor:
                return error_proveedor
            guardar_proveedores(cur, producto_id, proveedor_ids)
        if cambios:
            asignaciones = ", ".join(f"{campo} = %s" for campo in cambios)
            cur.execute(f"UPDATE PRODUCTO SET {asignaciones} WHERE id = %s", (*cambios.values(), producto_id))
        db.commit()
        return jsonify(leer_producto(cur, producto_id)), 200
    except MySQLError as e:
        db.rollback()
        if e.errno == errorcode.ER_DUP_ENTRY:
            return error_response("SKU_DUPLICADO", "SKU ya existe", 409)
        if e.errno == errorcode.ER_NO_REFERENCED_ROW_2:
            return error_response(*REFERENCIA_INVALIDA)
        return error_response("ERROR_BD", str(e), 500)
    finally:
        cur.close()
        db.close()


@app.delete("/<int:producto_id>")
def dar_de_baja_producto(producto_id):
    """Baja lógica: el producto queda inactivo pero se conserva su historial (movimientos, órdenes)."""
    sin_permiso = requiere_permiso(GESTIONAR)
    if sin_permiso:
        return sin_permiso

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM PRODUCTO WHERE id = %s", (producto_id,))
        if not cur.fetchone():
            return error_response("NO_ENCONTRADO", "Producto no existe", 404)
        cur.execute("UPDATE PRODUCTO SET activo = FALSE WHERE id = %s", (producto_id,))
        db.commit()
        return jsonify(leer_producto(cur, producto_id)), 200
    finally:
        cur.close()
        db.close()


#CATEGORIAS
@app.get("/categorias")
def listar_categorias():
    padre_id = request.args.get("padre_id", type=int)
    activa = request.args.get("activa")
    sql = "SELECT id, nombre, padre_id, activa FROM CATEGORIA WHERE 1=1"
    params = []
    if padre_id is not None:
        sql += " AND padre_id = %s"
        params.append(padre_id)
    if activa is not None:
        sql += " AND activa = %s"
        params.append(1 if activa.lower() == "true" else 0)
    sql += " ORDER BY id ASC"

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return jsonify([serializar_categoria(f) for f in cur.fetchall()]), 200
    finally:
        cur.close()
        db.close()


@app.post("/categorias")
def crear_categoria():
    sin_permiso = requiere_permiso(GESTIONAR)
    if sin_permiso:
        return sin_permiso

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
        if e.errno == errorcode.ER_NO_REFERENCED_ROW_2:
            return error_response("VALIDACION_FALLIDA", "La categoría padre indicada no existe", 422)
        return error_response("ERROR_BD", str(e), 500)
    finally:
        cur.close()
        db.close()


@app.put("/categorias/<int:categoria_id>")
def actualizar_categoria(categoria_id):
    sin_permiso = requiere_permiso(GESTIONAR)
    if sin_permiso:
        return sin_permiso

    data = request.get_json(silent=True) or {}
    cambios = {}
    if "nombre" in data:
        nombre = str(data["nombre"] or "").strip()
        if not nombre:
            return error_response("VALIDACION_FALLIDA", "nombre no puede estar vacío", 422)
        cambios["nombre"] = nombre
    if "padre_id" in data:
        if data["padre_id"] == categoria_id:
            return error_response("VALIDACION_FALLIDA", "Una categoría no puede ser su propia categoría padre", 422)
        cambios["padre_id"] = data["padre_id"]

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM CATEGORIA WHERE id = %s", (categoria_id,))
        if not cur.fetchone():
            return error_response("NO_ENCONTRADO", "Categoría no existe", 404)
        if cambios:
            asignaciones = ", ".join(f"{campo} = %s" for campo in cambios)
            cur.execute(f"UPDATE CATEGORIA SET {asignaciones} WHERE id = %s", (*cambios.values(), categoria_id))
            db.commit()
        cur.execute("SELECT id, nombre, padre_id, activa FROM CATEGORIA WHERE id = %s", (categoria_id,))
        return jsonify(serializar_categoria(cur.fetchone())), 200
    except MySQLError as e:
        db.rollback()
        if e.errno == errorcode.ER_NO_REFERENCED_ROW_2:
            return error_response("VALIDACION_FALLIDA", "La categoría padre indicada no existe", 422)
        return error_response("ERROR_BD", str(e), 500)
    finally:
        cur.close()
        db.close()


@app.delete("/categorias/<int:categoria_id>")
def eliminar_categoria(categoria_id):
    """Baja lógica: la categoría queda inactiva; los productos que la usan no se modifican."""
    sin_permiso = requiere_permiso(GESTIONAR)
    if sin_permiso:
        return sin_permiso

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM CATEGORIA WHERE id = %s", (categoria_id,))
        if not cur.fetchone():
            return error_response("NO_ENCONTRADO", "Categoría no existe", 404)
        cur.execute("UPDATE CATEGORIA SET activa = FALSE WHERE id = %s", (categoria_id,))
        db.commit()
        cur.execute("SELECT id, nombre, padre_id, activa FROM CATEGORIA WHERE id = %s", (categoria_id,))
        return jsonify(serializar_categoria(cur.fetchone())), 200
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
    app.run(host="0.0.0.0", port=8000, debug=False)
