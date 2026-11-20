import os
from datetime import datetime
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from inventarios_client import registrar_salida, SinStock, InventariosCaido

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///logistica.db")
db = SQLAlchemy(app)

# A que estado puede pasar un envio desde cada estado
TRANSICIONES = {
    "CREADO": ["EN_PREPARACION", "FALLIDO"],
    "EN_PREPARACION": ["DESPACHADO", "FALLIDO"],
    "DESPACHADO": ["EN_RUTA", "FALLIDO"],
    "EN_RUTA": ["ENTREGADO", "FALLIDO"],
    "ENTREGADO": [],
    "FALLIDO": [],
}


# Tablas
class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo_documento = db.Column(db.String(10))
    numero_documento = db.Column(db.String(40), unique=True)
    nombre = db.Column(db.String(200))
    direccion = db.Column(db.String(300))
    telefono = db.Column(db.String(40))
    email = db.Column(db.String(160))


class Paquete(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer)
    codigo_barras = db.Column(db.String(60))
    peso_kg = db.Column(db.Float)
    descripcion = db.Column(db.String(300))
    estado = db.Column(db.String(20), default="RECIBIDO")


class Envio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    guia_numero = db.Column(db.String(30))
    cliente_id = db.Column(db.Integer)
    bodega_origen_id = db.Column(db.Integer)
    destino = db.Column(db.String(300))
    estado_actual = db.Column(db.String(20), default="CREADO")
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)


class EnvioInsumo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    envio_id = db.Column(db.Integer)
    producto_id = db.Column(db.Integer)
    cantidad = db.Column(db.Integer)
    movimiento_salida_id = db.Column(db.Integer)


class HistorialEstado(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    envio_id = db.Column(db.Integer)
    estado = db.Column(db.String(20))
    observacion = db.Column(db.String(300))
    fecha = db.Column(db.DateTime, default=datetime.utcnow)


# Clientes
@app.get("/logistica/clientes")
def listar_clientes():
    q = request.args.get("q")
    consulta = Cliente.query
    if q:
        consulta = consulta.filter(Cliente.nombre.ilike(f"%{q}%"))
    return jsonify([{"id": c.id, "nombre": c.nombre, "numero_documento": c.numero_documento}
                    for c in consulta.all()])


@app.post("/logistica/clientes")
def crear_cliente():
    datos = request.get_json()
    if not datos.get("numero_documento") or not datos.get("nombre"):
        return jsonify({"mensaje": "numero_documento y nombre son obligatorios"}), 422
    c = Cliente(
        tipo_documento=datos.get("tipo_documento"),
        numero_documento=datos["numero_documento"],
        nombre=datos["nombre"],
        direccion=datos.get("direccion"),
        telefono=datos.get("telefono"),
        email=datos.get("email"),
    )
    db.session.add(c)
    db.session.commit()
    return jsonify({"id": c.id, "nombre": c.nombre}), 201


# Paquetes
@app.get("/logistica/paquetes")
def listar_paquetes():
    estado = request.args.get("estado")
    consulta = Paquete.query
    if estado:
        consulta = consulta.filter_by(estado=estado)
    return jsonify([{"id": p.id, "cliente_id": p.cliente_id, "codigo_barras": p.codigo_barras,
                     "estado": p.estado} for p in consulta.all()])


@app.post("/logistica/paquetes")
def crear_paquete():
    datos = request.get_json()
    if not datos.get("cliente_id") or not datos.get("codigo_barras"):
        return jsonify({"mensaje": "cliente_id y codigo_barras son obligatorios"}), 422
    if not Cliente.query.get(datos["cliente_id"]):
        return jsonify({"mensaje": "El cliente no existe"}), 404
    p = Paquete(
        cliente_id=datos["cliente_id"],
        codigo_barras=datos["codigo_barras"],
        peso_kg=datos.get("peso_kg"),
        descripcion=datos.get("descripcion"),
    )
    db.session.add(p)
    db.session.commit()
    return jsonify({"id": p.id, "estado": p.estado}), 201


# Envios
@app.get("/logistica/envios")
def listar_envios():
    estado = request.args.get("estado")
    consulta = Envio.query
    if estado:
        consulta = consulta.filter_by(estado_actual=estado)
    return jsonify([{"id": e.id, "guia_numero": e.guia_numero, "destino": e.destino,
                     "estado_actual": e.estado_actual} for e in consulta.all()])


@app.post("/logistica/envios")
def crear_envio():
    datos = request.get_json()
    if not datos.get("cliente_id") or not datos.get("destino"):
        return jsonify({"mensaje": "cliente_id y destino son obligatorios"}), 422
    if not Cliente.query.get(datos["cliente_id"]):
        return jsonify({"mensaje": "El cliente no existe"}), 404

    numero = Envio.query.count() + 1
    e = Envio(
        guia_numero=f"GUI-{numero:06d}",
        cliente_id=datos["cliente_id"],
        bodega_origen_id=datos.get("bodega_origen_id"),
        destino=datos["destino"],
        estado_actual="CREADO",
    )
    db.session.add(e)
    db.session.commit()
    db.session.add(HistorialEstado(envio_id=e.id, estado="CREADO", observacion="Envio creado"))
    db.session.commit()
    return jsonify({"id": e.id, "guia_numero": e.guia_numero, "estado_actual": e.estado_actual}), 201


@app.get("/logistica/envios/<int:id>")
def obtener_envio(id):
    e = Envio.query.get(id)
    if not e:
        return jsonify({"mensaje": "No existe"}), 404
    insumos = EnvioInsumo.query.filter_by(envio_id=id).all()
    historial = HistorialEstado.query.filter_by(envio_id=id).all()
    return jsonify({
        "id": e.id, "guia_numero": e.guia_numero, "destino": e.destino,
        "estado_actual": e.estado_actual,
        "insumos": [{"producto_id": i.producto_id, "cantidad": i.cantidad,
                     "movimiento_salida_id": i.movimiento_salida_id} for i in insumos],
        "historial_estados": [{"estado": h.estado, "observacion": h.observacion} for h in historial],
    })


@app.post("/logistica/envios/<int:id>/estado")
def cambiar_estado(id):
    e = Envio.query.get(id)
    if not e:
        return jsonify({"mensaje": "No existe"}), 404
    datos = request.get_json()
    nuevo = datos.get("estado")
    # Solo se permite si esta en la lista de transiciones del estado actual
    if nuevo not in TRANSICIONES.get(e.estado_actual, []):
        return jsonify({"mensaje": f"No se puede pasar de {e.estado_actual} a {nuevo}"}), 409
    e.estado_actual = nuevo
    db.session.add(HistorialEstado(envio_id=e.id, estado=nuevo, observacion=datos.get("observacion")))
    db.session.commit()
    return jsonify({"id": e.id, "estado_actual": e.estado_actual})


@app.post("/logistica/envios/<int:id>/insumos")
def registrar_insumos(id):
    e = Envio.query.get(id)
    if not e:
        return jsonify({"mensaje": "No existe"}), 404
    datos = request.get_json()
    insumos = datos.get("insumos", [])
    if len(insumos) == 0:
        return jsonify({"mensaje": "Debe enviar al menos un insumo"}), 422

    token = request.headers.get("Authorization")
    creados = []
    for linea in insumos:
        try:
            # Le pedimos a Inventarios que descuente el stock
            mov_id = registrar_salida(linea["producto_id"], linea["bodega_id"],
                                      linea["cantidad"], token)
        except SinStock:
            return jsonify({"mensaje": "Stock insuficiente en Inventarios"}), 409
        except InventariosCaido:
            return jsonify({"mensaje": "Inventarios no disponible"}), 502
        ei = EnvioInsumo(envio_id=e.id, producto_id=linea["producto_id"],
                         cantidad=linea["cantidad"], movimiento_salida_id=mov_id)
        db.session.add(ei)
        creados.append(ei)

    db.session.commit()
    return jsonify([{"producto_id": i.producto_id, "cantidad": i.cantidad,
                     "movimiento_salida_id": i.movimiento_salida_id} for i in creados]), 201


@app.get("/health")
def health():
    return {"status": "ok"}


def datos_ejemplo():
    if Cliente.query.count() == 0:
        db.session.add(Cliente(tipo_documento="CC", numero_documento="100200300",
                               nombre="Comercial Andina"))
        db.session.commit()
        db.session.add(Paquete(cliente_id=1, codigo_barras="PKG-0001", estado="EN_CUSTODIA"))
        db.session.add(Paquete(cliente_id=1, codigo_barras="PKG-0002", estado="EN_CUSTODIA"))
        db.session.commit()


with app.app_context():
    db.create_all()
    datos_ejemplo()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003)
