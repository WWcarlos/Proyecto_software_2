"""
Pruebas de rendimiento del Sistema de Gestión de Inventarios (Locust).

TODAS las peticiones entran por el API Gateway (por defecto http://localhost:8080),
que es el único punto de entrada del sistema.

Cada clase (HttpUser) es un escenario. ejecutar_pruebas.py define las 45 pruebas
(15 por integrante) y las ejecuta. También se puede usar a mano, por ejemplo:

    locust -f locustfile.py --host http://localhost:8080 ProductosLectura
    locust -f locustfile.py --host http://localhost:8080 --headless -u 50 -r 10 -t 2m ProductosLectura

Variables de entorno opcionales:
    LOCUST_EMAIL / LOCUST_PASSWORD   credenciales (por defecto el admin sembrado)
"""
import logging
import os
import random
import uuid

import requests
from locust import HttpUser, between, events, task

log = logging.getLogger("pruebas")

EMAIL = os.getenv("LOCUST_EMAIL", "admin@inventarios.com")
PASSWORD = os.getenv("LOCUST_PASSWORD", "Admin12345!")

# Datos compartidos que se preparan una sola vez al iniciar la prueba (ver preparar_datos).
DATOS = {
    "token": None,
    "bodega_id": None,
    "bodega2_id": None,
    "producto_ids": [],
    "movimiento_id": None,
    "categoria_id": None,
    "unidad_id": None,
    "proveedor_id": None,
    "cliente_id": None,
}


def _lista(cuerpo):
    """Los servicios devuelven una lista, o un objeto con 'items' (productos)."""
    if isinstance(cuerpo, dict):
        return cuerpo.get("items", [])
    return cuerpo or []


def _unico(prefijo):
    return f"{prefijo}-{uuid.uuid4().hex[:12]}"


def _bodega(host, headers, codigo, nombre):
    """Crea la bodega de pruebas o, si ya existe, devuelve su id."""
    r = requests.post(f"{host}/inventarios/bodegas", json={"codigo": codigo, "nombre": nombre, "ubicacion": "Pruebas"},
                      headers=headers, timeout=15)
    if r.status_code == 201:
        return r.json()["id"]
    bodegas = requests.get(f"{host}/inventarios/bodegas", headers=headers, timeout=15).json()
    return next(b["id"] for b in _lista(bodegas) if b["codigo"] == codigo)


# ----------------------------------------------------------------------------
# Preparación de datos (se ejecuta una vez, antes de lanzar los usuarios virtuales)
# ----------------------------------------------------------------------------
@events.test_start.add_listener
def preparar_datos(environment, **_):
    host = (environment.host or "http://localhost:8080").rstrip("/")
    try:
        login = requests.post(
            f"{host}/usuarios/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=15
        )
        login.raise_for_status()
        DATOS["token"] = login.json()["access_token"]
        h = {"Authorization": f"Bearer {DATOS['token']}"}

        # Dos bodegas de pruebas (la segunda se usa para los traslados)
        DATOS["bodega_id"] = _bodega(host, h, "LOCUST-01", "Bodega de pruebas Locust 1")
        DATOS["bodega2_id"] = _bodega(host, h, "LOCUST-02", "Bodega de pruebas Locust 2")

        # Productos, categoría y unidad existentes (datos sembrados por el servicio de productos)
        productos = _lista(requests.get(f"{host}/productos/?size=10", headers=h, timeout=15).json())
        DATOS["producto_ids"] = [p["id"] for p in productos]
        DATOS["categoria_id"] = productos[0]["categoria_id"]
        DATOS["unidad_id"] = productos[0]["unidad_medida_id"]

        proveedores = _lista(requests.get(f"{host}/proveedores/", headers=h, timeout=15).json())
        DATOS["proveedor_id"] = proveedores[0]["id"]

        clientes = _lista(requests.get(f"{host}/logistica/clientes", headers=h, timeout=15).json())
        DATOS["cliente_id"] = clientes[0]["id"] if clientes else 1

        # Stock inicial amplio en la bodega 1 para que salidas, traslados y recepciones no fallen por falta de existencias
        for pid in DATOS["producto_ids"][:2]:
            r = requests.post(
                f"{host}/inventarios/movimientos",
                json={"tipo": "ENTRADA", "producto_id": pid, "cantidad": 1000000,
                      "bodega_destino_id": DATOS["bodega_id"], "motivo": "Stock inicial pruebas Locust"},
                headers=h, timeout=15,
            )
            r.raise_for_status()
            DATOS["movimiento_id"] = r.json()["id"]
        log.info("Datos de prueba listos: %s", {k: v for k, v in DATOS.items() if k != "token"})
    except Exception as e:  # sin datos de base no tiene sentido continuar
        log.error("No se pudieron preparar los datos de prueba: %s", e)
        if environment.runner:
            environment.runner.quit()
        raise


class UsuarioAutenticado(HttpUser):
    """Base: lleva el token JWT en todas las peticiones."""

    abstract = True
    wait_time = between(0.5, 1.5)

    def on_start(self):
        self.client.headers.update({"Authorization": f"Bearer {DATOS['token']}"})

    def _producto(self):
        return random.choice(DATOS["producto_ids"])

    def _movimiento(self, cuerpo):
        self.client.post("/inventarios/movimientos", json={"producto_id": self._producto(), **cuerpo},
                         name=f"POST /inventarios/movimientos ({cuerpo['tipo']})")


# ============================================================================
# INTEGRANTE 1 · GATEWAY, USUARIOS Y COMPRAS
# ============================================================================
class GatewayRutas(HttpUser):
    """Comportamiento propio del gateway: salud, rechazo sin token (401) y ruta inexistente (404).
    Las respuestas 401 y 404 son lo ESPERADO, por eso se marcan como correctas."""

    wait_time = between(0.2, 0.8)

    @task(2)
    def salud(self):
        self.client.get("/health", name="GET /health (gateway)")

    @task(3)
    def sin_token(self):
        with self.client.get("/productos/", name="GET /productos/ sin token (401)", catch_response=True) as r:
            r.success() if r.status_code == 401 else r.failure(f"se esperaba 401 y llegó {r.status_code}")

    @task(1)
    def ruta_inexistente(self):
        with self.client.get("/noexiste/x", name="GET /noexiste (404)", catch_response=True) as r:
            r.success() if r.status_code == 404 else r.failure(f"se esperaba 404 y llegó {r.status_code}")


class Login(HttpUser):
    """Usuarios -> POST /usuarios/auth/login (bcrypt: operación intensiva en CPU)."""

    wait_time = between(0.5, 1.5)

    @task
    def iniciar_sesion(self):
        self.client.post("/usuarios/auth/login", json={"email": EMAIL, "password": PASSWORD},
                         name="POST /usuarios/auth/login")


class UsuariosSesion(UsuarioAutenticado):
    """GET /usuarios/auth/validar: lo que el gateway consulta en CADA petición autenticada."""

    @task
    def validar(self):
        self.client.get("/usuarios/auth/validar", name="GET /usuarios/auth/validar")


class UsuariosConsulta(UsuarioAutenticado):
    @task(3)
    def usuarios(self):
        self.client.get("/usuarios/", name="GET /usuarios/")

    @task(2)
    def roles(self):
        self.client.get("/usuarios/roles", name="GET /usuarios/roles")

    @task(2)
    def permisos(self):
        self.client.get("/usuarios/permisos", name="GET /usuarios/permisos")


class UsuariosCrear(UsuarioAutenticado):
    """POST /usuarios/ (hash bcrypt de la contraseña + escritura en BD)."""

    wait_time = between(1, 2)

    @task
    def crear(self):
        self.client.post(
            "/usuarios/",
            json={"nombre": "Usuario de prueba", "email": f"loc-{uuid.uuid4().hex[:12]}@example.com",
                  "password": "PruebaLocust123!", "roles": []},
            name="POST /usuarios/",
        )


class GatewayAutenticado(UsuarioAutenticado):
    """Lecturas hacia 4 servicios distintos: cada una pasa por la validación de token del gateway."""

    wait_time = between(0.2, 0.8)

    @task
    def lecturas(self):
        ruta, nombre = random.choice([
            ("/productos/?page=1&size=20", "GET /productos/"),
            ("/compras/ordenes", "GET /compras/ordenes"),
            ("/proveedores/", "GET /proveedores/"),
            ("/usuarios/roles", "GET /usuarios/roles"),
        ])
        self.client.get(ruta, name=nombre)


class ComprasLectura(UsuarioAutenticado):
    @task(4)
    def listar(self):
        self.client.get("/compras/ordenes", name="GET /compras/ordenes")

    @task(1)
    def filtrar(self):
        self.client.get("/compras/ordenes?estado=EMITIDA", name="GET /compras/ordenes?estado=")


def _crear_orden(cliente, pid):
    return cliente.post(
        "/compras/ordenes",
        json={"proveedor_id": DATOS["proveedor_id"],
              "detalles": [{"producto_id": pid, "cantidad_solicitada": 5, "costo_unitario": 1200.5}]},
        name="POST /compras/ordenes",
    )


class ComprasCrear(UsuarioAutenticado):
    """POST /compras/ordenes: Compras valida proveedor y producto llamando a otros 2 servicios."""

    @task
    def crear(self):
        _crear_orden(self.client, self._producto())


class ComprasCancelar(UsuarioAutenticado):
    @task
    def crear_y_cancelar(self):
        orden = _crear_orden(self.client, self._producto())
        if orden.status_code == 201:
            self.client.post(f"/compras/ordenes/{orden.json()['id']}/cancelar",
                             name="POST /compras/ordenes/{id}/cancelar")


class FlujoCompra(UsuarioAutenticado):
    """Extremo a extremo: crea orden -> emite -> recibe mercancía (Compras llama a Productos,
    Proveedores e Inventarios, y este a Analítica) -> consulta la orden."""

    wait_time = between(1, 2)

    @task
    def orden_completa(self):
        orden = _crear_orden(self.client, self._producto())
        if orden.status_code != 201:
            return
        cuerpo = orden.json()
        orden_id = cuerpo["id"]
        detalle_id = cuerpo["detalles"][0]["id"]
        emitida = self.client.post(f"/compras/ordenes/{orden_id}/emitir", name="POST /compras/ordenes/{id}/emitir")
        if emitida.status_code != 200:
            return
        self.client.post(
            f"/compras/ordenes/{orden_id}/recepciones",
            json={"bodega_id": DATOS["bodega_id"],
                  "lineas": [{"orden_compra_detalle_id": detalle_id, "cantidad_recibida": 5}]},
            name="POST /compras/ordenes/{id}/recepciones",
        )
        self.client.get(f"/compras/ordenes/{orden_id}", name="GET /compras/ordenes/{id}")

##participante 2 ahi para abajo

# ============================================================================
# INTEGRANTE 3 · PRODUCTOS, PROVEEDORES Y LOGÍSTICA
# ============================================================================
class ProductosLectura(UsuarioAutenticado):
    @task(5)
    def listar(self):
        self.client.get("/productos/?page=1&size=20", name="GET /productos/")

    @task(1)
    def categorias(self):
        self.client.get("/productos/categorias", name="GET /productos/categorias")

    @task(1)
    def unidades(self):
        self.client.get("/productos/unidades-medida", name="GET /productos/unidades-medida")


class ProductosBusqueda(UsuarioAutenticado):
    @task(3)
    def detalle(self):
        self.client.get(f"/productos/{self._producto()}", name="GET /productos/{id}")

    @task(2)
    def buscar(self):
        self.client.get("/productos/?q=caja", name="GET /productos/?q=")

    @task(1)
    def por_categoria(self):
        self.client.get(f"/productos/?categoria_id={DATOS['categoria_id']}", name="GET /productos/?categoria_id=")


class ProductosEscritura(UsuarioAutenticado):
    """POST /productos/ con SKU único."""

    @task
    def crear(self):
        self.client.post(
            "/productos/",
            json={"sku": _unico("LOC"), "nombre": "Producto de prueba", "descripcion": "Creado por Locust",
                  "categoria_id": DATOS["categoria_id"], "unidad_medida_id": DATOS["unidad_id"]},
            name="POST /productos/",
        )


class ProductosActualizar(UsuarioAutenticado):
    """PUT /productos/{id}: crea su propio producto (no toca los sembrados) y lo actualiza."""

    def on_start(self):
        super().on_start()
        r = self.client.post(
            "/productos/",
            json={"sku": _unico("UPD"), "nombre": "Producto a actualizar", "categoria_id": DATOS["categoria_id"],
                  "unidad_medida_id": DATOS["unidad_id"]},
            name="POST /productos/ (preparación)",
        )
        self.mi_producto = r.json()["id"] if r.status_code == 201 else None

    @task
    def actualizar(self):
        if self.mi_producto is None:
            return
        self.client.put(
            f"/productos/{self.mi_producto}",
            json={"nombre": f"Producto actualizado {random.randint(1, 9999)}", "descripcion": "Actualizado por Locust",
                  "categoria_id": DATOS["categoria_id"], "unidad_medida_id": DATOS["unidad_id"]},
            name="PUT /productos/{id}",
        )


class ProveedoresLectura(UsuarioAutenticado):
    @task(3)
    def listar(self):
        self.client.get("/proveedores/", name="GET /proveedores/")

    @task(2)
    def detalle(self):
        self.client.get(f"/proveedores/{DATOS['proveedor_id']}", name="GET /proveedores/{id}")


class ProveedoresEscritura(UsuarioAutenticado):
    """Crea un proveedor propio (NIT único) y lo actualiza y desactiva; no toca los sembrados."""

    @task
    def ciclo(self):
        nit = f"{random.randint(100000000, 999999999)}-{random.randint(0, 9)}"
        r = self.client.post("/proveedores/", json={"nit": nit, "razon_social": "Proveedor de prueba",
                                                    "plazo_entrega_dias": 3}, name="POST /proveedores/")
        if r.status_code != 201:
            return
        pid = r.json()["id"]
        self.client.put(f"/proveedores/{pid}", json={"razon_social": "Proveedor actualizado", "contacto_nombre": "Locust",
                                                      "plazo_entrega_dias": 5}, name="PUT /proveedores/{id}")
        self.client.patch(f"/proveedores/{pid}/estado", json={"activo": False}, name="PATCH /proveedores/{id}/estado")


class LogisticaLectura(UsuarioAutenticado):
    @task(2)
    def clientes(self):
        self.client.get("/logistica/clientes", name="GET /logistica/clientes")

    @task(2)
    def paquetes(self):
        self.client.get("/logistica/paquetes", name="GET /logistica/paquetes")

    @task(3)
    def envios(self):
        self.client.get("/logistica/envios", name="GET /logistica/envios")


def _crear_envio(cliente):
    """Crea un paquete y un envío con él. Devuelve el id del envío (o None si algo falló)."""
    paquete = cliente.post(
        "/logistica/paquetes",
        json={"cliente_id": DATOS["cliente_id"], "codigo_barras": _unico("PKG"), "peso_kg": 1.5,
              "descripcion": "Paquete Locust"},
        name="POST /logistica/paquetes",
    )
    if paquete.status_code != 201:
        return None
    envio = cliente.post(
        "/logistica/envios",
        json={"cliente_id": DATOS["cliente_id"], "bodega_origen_id": DATOS["bodega_id"],
              "destino": "Bogotá", "paquetes": [paquete.json()["id"]]},
        name="POST /logistica/envios",
    )
    return envio.json()["id"] if envio.status_code == 201 else None


class EnviosEscritura(UsuarioAutenticado):
    """Crear paquete -> crear envío -> primer cambio de estado. Ejercita la guía única bajo concurrencia."""

    @task
    def flujo_envio(self):
        envio_id = _crear_envio(self.client)
        if envio_id:
            self.client.post(f"/logistica/envios/{envio_id}/estado",
                             json={"estado": "EN_PREPARACION", "observacion": "Locust"},
                             name="POST /logistica/envios/{id}/estado")


class EnviosCicloVida(UsuarioAutenticado):
    """Recorre toda la máquina de estados de un envío y lo consulta al final."""

    wait_time = between(1, 2)

    @task
    def ciclo(self):
        envio_id = _crear_envio(self.client)
        if not envio_id:
            return
        for estado in ("EN_PREPARACION", "DESPACHADO", "EN_RUTA", "ENTREGADO"):
            r = self.client.post(f"/logistica/envios/{envio_id}/estado", json={"estado": estado},
                                 name="POST /logistica/envios/{id}/estado")
            if r.status_code != 200:
                return
        self.client.get(f"/logistica/envios/{envio_id}", name="GET /logistica/envios/{id}")


class EnviosInsumos(UsuarioAutenticado):
    """Logística -> Inventarios: registrar insumos de un envío descuenta stock (SALIDA) vía REST."""

    wait_time = between(1, 2)

    @task
    def con_insumos(self):
        envio_id = _crear_envio(self.client)
        if not envio_id:
            return
        self.client.post(
            f"/logistica/envios/{envio_id}/insumos",
            json={"insumos": [{"producto_id": self._producto(), "bodega_id": DATOS["bodega_id"], "cantidad": 1}]},
            name="POST /logistica/envios/{id}/insumos",
        )


class EstresMixto(UsuarioAutenticado):
    """Mezcla lectura (80 %) y escritura (20 %) sobre 6 servicios para buscar el punto de quiebre."""

    wait_time = between(0.2, 0.8)

    @task(8)
    def lectura(self):
        ruta, nombre = random.choice([
            ("/productos/?page=1&size=20", "GET /productos/"),
            ("/proveedores/", "GET /proveedores/"),
            ("/logistica/envios", "GET /logistica/envios"),
            ("/inventarios/saldos", "GET /inventarios/saldos"),
            ("/compras/ordenes", "GET /compras/ordenes"),
        ])
        self.client.get(ruta, name=nombre)

    @task(1)
    def crear_producto(self):
        self.client.post(
            "/productos/",
            json={"sku": _unico("EST"), "nombre": "Producto estrés", "categoria_id": DATOS["categoria_id"],
                  "unidad_medida_id": DATOS["unidad_id"]},
            name="POST /productos/",
        )

    @task(1)
    def crear_envio(self):
        _crear_envio(self.client)
