import csv
import hmac
import io
import json
import os
import urllib.error
import urllib.request
import uuid
from datetime import date
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

# Los reportes de existencias y valorización consultan por REST a los servicios dueños de los datos
# (Analítica no accede a sus bases de datos): Inventarios tiene los saldos y Productos los precios.
INVENTARIOS_URL = os.getenv("INVENTARIOS_URL", "http://inventarios:8000")
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
    """Forma del esquema Indicador del contrato analitica.yaml."""
    return {
        "nombre": row["nombre"],
        "dimension": row["dimension"],
        "clave_dimension": row["clave_dimension"] or None,
        "valor": float(row["valor"]),
        "periodo_inicio": row["periodo_inicio"].isoformat(),
        "periodo_fin": row["periodo_fin"].isoformat(),
        "calculado_en": row["calculado_en"].isoformat() if row["calculado_en"] else None,
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
  <script>SwaggerUIBundle({ url: 'openapi.yaml', dom_id: '#swagger-ui' });</script>
</body>
</html>""", 200, {"Content-Type": "text/html"}


# =====================================================================
# 1. RECEPCIÓN DE EVENTOS DE DOMINIO (POST /eventos)
# =====================================================================
# Servicio que origina cada tipo de evento (columna "origen" del modelo EVENTO_RECIBIDO).
ORIGEN_EVENTO = {
    "movimiento.registrado": "inventarios",
    "stock.bajo": "inventarios",
    "orden.recibida": "compras",
    "envio.creado": "logistica",
}


def sumar_indicador(cur, nombre, dimension, clave, valor):
    """Suma valor al indicador del día para esa dimensión (crea la fila si no existe)."""
    cur.execute(
        "INSERT INTO INDICADOR (nombre, dimension, clave_dimension, valor, periodo_inicio, periodo_fin) "
        "VALUES (%s, %s, %s, %s, CURDATE(), CURDATE()) "
        "ON DUPLICATE KEY UPDATE valor = valor + VALUES(valor)",
        (nombre, dimension, "" if clave is None else str(clave), valor),
    )


def fijar_indicador(cur, nombre, valor):
    """Reemplaza el valor general del indicador del día (para valores que no se acumulan)."""
    cur.execute(
        "INSERT INTO INDICADOR (nombre, dimension, clave_dimension, valor, periodo_inicio, periodo_fin) "
        "VALUES (%s, 'general', '', %s, CURDATE(), CURDATE()) "
        "ON DUPLICATE KEY UPDATE valor = VALUES(valor)",
        (nombre, valor),
    )


@app.post("/eventos")
def recibir_evento():
    data = request.get_json(silent=True) or {}
    tipo_evento = (data.get("tipo_evento") or "").strip()
    evento_id = (data.get("evento_id") or str(uuid.uuid4())).strip()
    datos = data.get("datos") if isinstance(data.get("datos"), dict) else data

    if tipo_evento not in ORIGEN_EVENTO:
        return error_response(
            "VALIDACION_FALLIDA",
            f"tipo_evento debe ser uno de {tuple(ORIGEN_EVENTO)}",
            422,
        )

    producto_id = datos.get("producto_id")
    bodega_origen_id = datos.get("bodega_origen_id")
    bodega_destino_id = datos.get("bodega_destino_id")
    bodega_id = bodega_destino_id or bodega_origen_id or datos.get("bodega_id")
    cliente_id = datos.get("cliente_id")
    tipo_movimiento = datos.get("tipo")

    try:
        cantidad = int(datos.get("cantidad") or 0)
        total_alertas = int(datos.get("total_alertas", 0))
    except (ValueError, TypeError):
        return error_response("VALIDACION_FALLIDA", "cantidad y total_alertas deben ser numéricos", 422)

    db = get_db()
    cur = db.cursor()
    try:
        db.start_transaction()

        cur.execute(
            "INSERT INTO EVENTO_RECIBIDO (evento_id, tipo_evento, origen, producto_id, bodega_id, bodega_origen_id, "
            "bodega_destino_id, cliente_id, cantidad, tipo_movimiento, payload) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                evento_id,
                tipo_evento,
                ORIGEN_EVENTO[tipo_evento],
                producto_id,
                bodega_id,
                bodega_origen_id,
                bodega_destino_id,
                cliente_id,
                cantidad,
                tipo_movimiento,
                json.dumps(data, default=str),
            ),
        )

        # Indicadores del día: valor general y por dimensión.
        if tipo_evento == "movimiento.registrado" and tipo_movimiento == "SALIDA":
            # Rotación = unidades que salieron (consumo).
            sumar_indicador(cur, "ROTACION_INVENTARIO", "general", None, abs(cantidad))
            sumar_indicador(cur, "ROTACION_INVENTARIO", "bodega", bodega_origen_id, abs(cantidad))
            sumar_indicador(cur, "ROTACION_INVENTARIO", "producto", producto_id, abs(cantidad))
        elif tipo_evento == "envio.creado":
            sumar_indicador(cur, "ENVIOS_DIA", "general", None, 1)
            sumar_indicador(cur, "ENVIOS_DIA", "cliente", cliente_id, 1)
            sumar_indicador(cur, "ENVIOS_DIA", "bodega", bodega_origen_id, 1)
        elif tipo_evento == "stock.bajo":
            # Número de saldos por debajo del mínimo en el momento del evento.
            fijar_indicador(cur, "STOCK_BAJO", total_alertas)

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
INDICADORES = ("ROTACION_INVENTARIO", "STOCK_BAJO", "ENVIOS_DIA")
DIMENSIONES = ("bodega", "producto", "cliente")
COLUMNAS_INDICADOR = "nombre, dimension, clave_dimension, valor, periodo_inicio, periodo_fin, calculado_en"


def leer_fecha(valor, campo):
    """Valida una fecha AAAA-MM-DD. Devuelve (fecha, error)."""
    if not valor:
        return None, None
    try:
        return date.fromisoformat(valor), None
    except ValueError:
        return None, error_response("VALIDACION_FALLIDA", f"{campo} debe tener el formato AAAA-MM-DD", 422)


def ultimos_indicadores(dimension="general"):
    """Último valor (periodo más reciente) de cada indicador para la dimensión indicada."""
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            f"SELECT {COLUMNAS_INDICADOR} FROM INDICADOR i WHERE dimension = %s AND periodo_inicio = ("
            "  SELECT MAX(periodo_inicio) FROM INDICADOR j"
            "  WHERE j.nombre = i.nombre AND j.dimension = i.dimension AND j.clave_dimension = i.clave_dimension"
            ") ORDER BY nombre, clave_dimension",
            (dimension,),
        )
        filas = [serializar_indicador(f) for f in cur.fetchall()]
    finally:
        cur.close()
        db.close()
    if dimension == "general":
        # Los indicadores que aún no tienen eventos se informan con valor 0.
        existentes = {f["nombre"] for f in filas}
        hoy = date.today().isoformat()
        for nombre in INDICADORES:
            if nombre not in existentes:
                filas.append({"nombre": nombre, "dimension": "general", "clave_dimension": None, "valor": 0.0,
                              "periodo_inicio": hoy, "periodo_fin": hoy, "calculado_en": None})
        filas.sort(key=lambda f: INDICADORES.index(f["nombre"]))
    return filas


@app.get("/indicadores")
def listar_indicadores():
    dimension = request.args.get("dimension")
    if dimension is not None and dimension not in DIMENSIONES:
        return error_response("VALIDACION_FALLIDA", f"dimension debe ser uno de {DIMENSIONES}", 422)
    return jsonify(ultimos_indicadores(dimension or "general")), 200


@app.get("/indicadores/<string:nombre>")
def serie_indicador(nombre):
    """Serie histórica (un valor por día) del indicador, en su dimensión general."""
    nombre = nombre.upper()
    if nombre not in INDICADORES:
        return error_response("NO_ENCONTRADO", f"El indicador '{nombre}' no existe", 404)
    desde, error = leer_fecha(request.args.get("desde"), "desde")
    if error:
        return error
    hasta, error = leer_fecha(request.args.get("hasta"), "hasta")
    if error:
        return error

    sql = f"SELECT {COLUMNAS_INDICADOR} FROM INDICADOR WHERE nombre = %s AND dimension = 'general'"
    params = [nombre]
    if desde:
        sql += " AND periodo_inicio >= %s"
        params.append(desde)
    if hasta:
        sql += " AND periodo_fin <= %s"
        params.append(hasta)
    sql += " ORDER BY periodo_inicio ASC"

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return jsonify([serializar_indicador(f) for f in cur.fetchall()]), 200
    finally:
        cur.close()
        db.close()


# =====================================================================
# 3. REPORTE DE INVENTARIO (/reportes/inventario?formato=json|csv)
# =====================================================================
COLUMNAS_REPORTE = ["bodega_id", "producto_id", "cantidad_disponible", "stock_minimo",
                    "entradas_periodo", "salidas_periodo"]


def movimientos_periodo(columna_bodega, bodega_id, desde, hasta):
    """Unidades por (producto, bodega) según los eventos de movimiento. columna_bodega indica
    si se cuentan las que entran (bodega_destino_id) o las que salen (bodega_origen_id)."""
    sql = (f"SELECT producto_id, {columna_bodega} AS bodega_id, COALESCE(SUM(cantidad), 0) AS unidades "
           f"FROM EVENTO_RECIBIDO WHERE tipo_evento = 'movimiento.registrado' AND {columna_bodega} IS NOT NULL")
    params = []
    if bodega_id is not None:
        sql += f" AND {columna_bodega} = %s"
        params.append(bodega_id)
    if desde:
        sql += " AND DATE(recibido_en) >= %s"
        params.append(desde)
    if hasta:
        sql += " AND DATE(recibido_en) <= %s"
        params.append(hasta)
    sql += f" GROUP BY producto_id, {columna_bodega}"
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return {(f["producto_id"], f["bodega_id"]): int(f["unidades"]) for f in cur.fetchall()}
    finally:
        cur.close()
        db.close()


@app.get("/reportes/inventario")
def reporte_inventario():
    """Por producto y bodega: existencias actuales (de Inventarios) y unidades que entraron
    y salieron en el periodo (de los eventos recibidos)."""
    formato = (request.args.get("formato") or "json").lower()
    bodega_id = request.args.get("bodega_id", type=int)
    if formato not in ("json", "csv"):
        return error_response("VALIDACION_FALLIDA", "formato debe ser 'json' o 'csv'", 422)
    desde, error = leer_fecha(request.args.get("desde"), "desde")
    if error:
        return error
    hasta, error = leer_fecha(request.args.get("hasta"), "hasta")
    if error:
        return error

    try:
        lista = saldos(bodega_id)
    except ServicioNoDisponible as e:
        return error_response("SERVICIO_NO_DISPONIBLE", str(e), 502)
    entradas = movimientos_periodo("bodega_destino_id", bodega_id, desde, hasta)
    salidas = movimientos_periodo("bodega_origen_id", bodega_id, desde, hasta)

    registros = [
        {
            "bodega_id": sd["bodega_id"],
            "producto_id": sd["producto_id"],
            "cantidad_disponible": sd["cantidad_disponible"],
            "stock_minimo": sd["stock_minimo"],
            "entradas_periodo": entradas.get((sd["producto_id"], sd["bodega_id"]), 0),
            "salidas_periodo": salidas.get((sd["producto_id"], sd["bodega_id"]), 0),
        }
        for sd in lista
    ]

    if formato == "json":
        return jsonify(registros), 200

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=COLUMNAS_REPORTE)
    writer.writeheader()
    writer.writerows(registros)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=reporte_inventario.csv"},
    )


# =====================================================================
# 4. REPORTES CON DATOS DE OTROS SERVICIOS (existencias, valorización, rotación, dashboard)
# =====================================================================
class ServicioNoDisponible(Exception):
    pass


def consultar(url):
    """GET a otro microservicio con el token de servicio. Lanza ServicioNoDisponible si falla."""
    req = urllib.request.Request(url, headers={"X-Service-Token": API_TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        raise ServicioNoDisponible(f"{url.split('/')[2]} no disponible ({type(e).__name__})")


def productos_activos():
    """Todos los productos activos, recorriendo las páginas de Productos. Devuelve {id: producto}."""
    productos, page = {}, 1
    while True:
        pagina = consultar(f"{PRODUCTOS_URL}/?activo=true&size=100&page={page}")
        for p in pagina["items"]:
            productos[p["id"]] = p
        if not pagina["items"] or len(productos) >= pagina["total"]:
            return productos
        page += 1


def saldos(bodega_id=None):
    url = f"{INVENTARIOS_URL}/saldos"
    if bodega_id is not None:
        url += f"?bodega_id={bodega_id}"
    return consultar(url)


def existencias_por_producto(lista_saldos):
    total = {}
    for sd in lista_saldos:
        total[sd["producto_id"]] = total.get(sd["producto_id"], 0) + sd["cantidad_disponible"]
    return total


def calcular_valorizacion(productos, lista_saldos):
    """Valor = cantidad disponible x precio del producto, por producto y por bodega."""
    por_producto, por_bodega = {}, {}
    for sd in lista_saldos:
        producto = productos.get(sd["producto_id"])
        if producto is None:  # producto dado de baja o inexistente: no se valoriza
            continue
        valor = round(sd["cantidad_disponible"] * producto["precio"], 2)
        fila = por_producto.setdefault(sd["producto_id"], {
            "producto_id": producto["id"], "sku": producto["sku"], "nombre": producto["nombre"],
            "precio": producto["precio"], "cantidad": 0, "valor": 0.0,
        })
        fila["cantidad"] += sd["cantidad_disponible"]
        fila["valor"] = round(fila["valor"] + valor, 2)
        por_bodega[sd["bodega_id"]] = round(por_bodega.get(sd["bodega_id"], 0.0) + valor, 2)
    valor_total = round(sum(f["valor"] for f in por_producto.values()), 2)
    return sorted(por_producto.values(), key=lambda f: -f["valor"]), por_bodega, valor_total


def calcular_rotacion(productos, desde=None, hasta=None):
    """Unidades que salieron (movimientos SALIDA recibidos como eventos) por producto activo."""
    sql = ("SELECT producto_id, COALESCE(SUM(cantidad), 0) AS unidades FROM EVENTO_RECIBIDO "
           "WHERE tipo_evento = 'movimiento.registrado' AND tipo_movimiento = 'SALIDA'")
    params = []
    if desde:
        sql += " AND recibido_en >= %s"
        params.append(desde)
    if hasta:
        sql += " AND recibido_en <= %s"
        params.append(hasta)
    sql += " GROUP BY producto_id"
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        salidas = {f["producto_id"]: int(f["unidades"]) for f in cur.fetchall()}
    finally:
        cur.close()
        db.close()
    # Los productos sin salidas también cuentan (rotación 0): son los de menor rotación.
    filas = [
        {"producto_id": p["id"], "sku": p["sku"], "nombre": p["nombre"], "unidades_salida": salidas.get(p["id"], 0)}
        for p in productos.values()
    ]
    return sorted(filas, key=lambda f: (-f["unidades_salida"], f["producto_id"]))


@app.get("/reportes/existencias")
def reporte_existencias():
    bodega_id = request.args.get("bodega_id", type=int)
    try:
        productos = productos_activos()
        lista = saldos(bodega_id)
    except ServicioNoDisponible as e:
        return error_response("SERVICIO_NO_DISPONIBLE", str(e), 502)
    datos = [
        {
            "producto_id": sd["producto_id"],
            "sku": productos.get(sd["producto_id"], {}).get("sku"),
            "nombre": productos.get(sd["producto_id"], {}).get("nombre"),
            "bodega_id": sd["bodega_id"],
            "cantidad_disponible": sd["cantidad_disponible"],
            "stock_minimo": sd["stock_minimo"],
            "bajo_minimo": sd["bajo_minimo"],
        }
        for sd in lista
    ]
    return jsonify({
        "total_filas": len(datos),
        "unidades_totales": sum(d["cantidad_disponible"] for d in datos),
        "datos": datos,
    }), 200


@app.get("/reportes/valorizacion")
def reporte_valorizacion():
    bodega_id = request.args.get("bodega_id", type=int)
    try:
        productos = productos_activos()
        lista = saldos(bodega_id)
    except ServicioNoDisponible as e:
        return error_response("SERVICIO_NO_DISPONIBLE", str(e), 502)
    por_producto, por_bodega, valor_total = calcular_valorizacion(productos, lista)
    return jsonify({
        "valor_total": valor_total,
        "por_bodega": [{"bodega_id": b, "valor": v} for b, v in sorted(por_bodega.items())],
        "por_producto": por_producto,
    }), 200


@app.get("/reportes/rotacion")
def reporte_rotacion():
    limite = request.args.get("limite", default=5, type=int)
    if limite < 1:
        return error_response("VALIDACION_FALLIDA", "limite debe ser >= 1", 422)
    try:
        productos = productos_activos()
    except ServicioNoDisponible as e:
        return error_response("SERVICIO_NO_DISPONIBLE", str(e), 502)
    filas = calcular_rotacion(productos, request.args.get("desde"), request.args.get("hasta"))
    return jsonify({
        "mayor_rotacion": filas[:limite],
        "menor_rotacion": list(reversed(filas))[:limite],
    }), 200


@app.get("/dashboard")
def dashboard():
    """Indicadores clave del inventario en una sola respuesta (RF14)."""
    try:
        productos = productos_activos()
        lista = saldos()
    except ServicioNoDisponible as e:
        return error_response("SERVICIO_NO_DISPONIBLE", str(e), 502)
    _, _, valor_total = calcular_valorizacion(productos, lista)
    existencias = existencias_por_producto(lista)
    rotacion = calcular_rotacion(productos)

    indicadores = ultimos_indicadores("general")

    return jsonify({
        "valor_total_inventario": valor_total,
        "unidades_totales": sum(existencias.get(pid, 0) for pid in productos),
        "productos_activos": len(productos),
        # Quiebre de stock: producto activo sin existencias en ninguna bodega.
        "quiebres_stock": sorted(pid for pid in productos if existencias.get(pid, 0) <= 0),
        "saldos_bajo_minimo": sum(1 for sd in lista if sd["bajo_minimo"]),
        "mayor_rotacion": rotacion[:3],
        "indicadores": indicadores,
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)