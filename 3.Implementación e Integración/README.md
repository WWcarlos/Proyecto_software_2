# Sistema de Gestión de Inventarios – Implementación e Integración

Microservicios en Flask + MySQL, con un API Gateway propio como único punto de entrada.
Los contratos de cada API son los de `2.Diseño y Arquitectura/Contratos/`; cada servicio publica su copia en `/docs`.

## Arquitectura
```
cliente ──► gateway :8080 ──┬─► usuarios ──► usuarios-db       (login, JWT, roles, permisos, recuperación de contraseña)
 (único puerto publicado)   ├─► compras ───► compras-db        (órdenes, recepciones)
                            ├─► productos ─► productos-db      (productos, precio, proveedores, categorías)
                            ├─► proveedores► proveedores-db
                            ├─► inventarios► inventarios-db    (bodegas, saldos, movimientos, devoluciones, alertas)
                            ├─► logistica ─► logistica-db      (clientes, paquetes, envíos, insumos)
                            └─► analitica ─► analitica-db      (eventos, indicadores, reportes, dashboard)
```
- El gateway valida el JWT con `usuarios` en cada petición y reenvía la identidad (`X-User-*`, `X-Usuario-Id`)
  y el `X-Service-Token`. Los tokens cerrados con logout se rechazan.
- Llamadas REST entre servicios (por nombre en la red):
  Compras → Productos / Proveedores / Inventarios · Inventarios → Productos · Logística → Inventarios ·
  Productos → Proveedores · Analítica → Inventarios / Productos (reportes).
- Eventos de dominio, enviados por REST a `POST /analitica/eventos` (no se usa broker de mensajes):
  `movimiento.registrado` y `stock.bajo` (Inventarios), `orden.recibida` (Compras), `envio.creado` (Logística).
- Cada servicio tiene su propia base de datos, sin puertos publicados; solo el gateway se expone.

## Levantar
```bash
cp .env.example .env        # cambia los valores (el .env no se sube a GitHub)
docker compose up --build
```
Si cambió algún `init.sql` (tablas o datos de ejemplo), hay que recrear las bases de datos. **Borra los datos locales:**
```bash
docker compose down -v && docker compose up --build
```
Todo entra por `http://localhost:8080/<servicio>/...`, por ejemplo:
```bash
curl -s -X POST localhost:8080/usuarios/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@inventarios.com","password":"Admin12345!"}'
curl -s localhost:8080/productos/ -H "Authorization: Bearer $TOKEN"
```
Documentación Swagger: `http://localhost:8080/<servicio>/docs` para los 7 servicios
(usuarios, compras, productos, proveedores, inventarios, logistica, analitica).

## Pruebas de rendimiento (Locust)
Cada integrante ejecuta sus 15 pruebas desde un contenedor de Locust (no hay que instalar nada), con el sistema levantado:
```bash
docker compose run --rm locust --integrante 1 --rapido    # comprobar que funcionan (30 s por prueba)
docker compose run --rm locust --integrante 1             # las 15 completas (~40 min)
```
Detalles, reparto de las 45 pruebas y criterios en [pruebas_rendimiento/readme](pruebas_rendimiento/readme).

## Usuarios, roles y permisos
Al arrancar, Usuarios crea el administrador (`ADMIN_EMAIL` / `ADMIN_PASSWORD` del `.env`) y dos roles:

| Permiso | ADMIN | BODEGUERO |
|---|:-:|:-:|
| `usuarios.gestionar` | ✔ | |
| `productos.gestionar` · `proveedores.gestionar` · `inventarios.bodegas.gestionar` | ✔ | |
| `compras.ordenes.gestionar` | ✔ | |
| `compras.recepciones.registrar` · `inventarios.movimientos.crear` · `logistica.gestionar` | ✔ | ✔ |

Las consultas (GET) solo requieren sesión; las operaciones de escritura exigen el permiso (si falta: 403 `SIN_PERMISO`).

**Recuperar contraseña** (no hay servidor de correo: el envío se simula en el log de Usuarios):
```bash
curl -s -X POST localhost:8080/usuarios/auth/recuperar -H 'Content-Type: application/json' -d '{"email":"admin@inventarios.com"}'
docker compose logs usuarios | grep "CORREO SIMULADO"     # muestra el código de 6 dígitos (válido 15 min, un solo uso)
curl -s -X POST localhost:8080/usuarios/auth/restablecer -H 'Content-Type: application/json' \
  -d '{"email":"admin@inventarios.com","codigo":"123456","password_nueva":"NuevaClave123!"}'
```
También: `POST /usuarios/auth/logout` (cierra la sesión) y `PUT /usuarios/auth/password` (cambio de contraseña).

## Funcionalidades principales (además del CRUD de cada servicio)
- **Productos:** precio, proveedores asociados (N:M), baja lógica (`DELETE`), filtros por nombre/SKU, categoría,
  proveedor y estado; categorías y subcategorías con edición y baja.
- **Inventarios:** entradas, salidas, ajustes, traslados y devoluciones (`DEVOLUCION_CLIENTE` entra a la bodega,
  `DEVOLUCION_PROVEEDOR` sale); stock mínimo y alertas; kardex con usuario y fecha; bodegas activas/inactivas.
- **Compras:** órdenes BORRADOR → EMITIDA → PARCIAL/RECIBIDA; cada recepción genera la ENTRADA en Inventarios.
- **Logística:** envíos con guía única y máquina de estados (historial con el usuario de cada cambio); el consumo
  de insumos genera la SALIDA en Inventarios.
- **Analítica:** indicadores diarios por dimensión (`/indicadores`, serie en `/indicadores/{nombre}`), reporte de
  inventario JSON/CSV, existencias, valorización, rotación (mayor y menor) y `/dashboard`.

## Escalar un servicio
Ningún contenedor tiene nombre fijo, así que se pueden levantar réplicas de los servicios internos, por ejemplo:
```bash
docker compose up -d --scale inventarios=3
```
Workers e hilos de gunicorn se ajustan con `GUNICORN_WORKERS` y `GUNICORN_THREADS` en el `.env`
(Usuarios y Compras usan 1 worker con 8 hilos porque al arrancar crean las tablas y los datos iniciales).

## Estructura
```
docker-compose.yml     único compose (apoyo local; Kubernetes queda fuera del alcance por ahora)
.env.example           variables y secretos
ms-gateway/            API Gateway propio
ms-<servicio>/         código, Dockerfile, init.sql (si aplica) y <servicio>.yaml (contrato OpenAPI)
pruebas_rendimiento/   pruebas con Locust, 15 por integrante, y su Dockerfile (ver su readme)
```

## Correcciones de la Entrega 3
- **Analítica escuchaba en el puerto 5000** y el resto del sistema la buscaba en el 8000: nunca quedaba "healthy"
  y el gateway no arrancaba. Ahora todos los servicios escuchan en el 8000.
- **Guía de envío única:** se calculaba con `COUNT(*)+1` y se repetía con envíos simultáneos (error 500).
  Ahora se deriva del id autoincremental.
- **Trazabilidad:** Logística no reenviaba la identidad a Inventarios y las salidas por envío quedaban con el usuario 1.
- **Swagger detrás del gateway:** cuatro servicios usaban una ruta absoluta; Usuarios y Compras no tenían `/docs`.
- **Contratos:** las respuestas de Logística y Analítica no tenían la forma definida en los contratos; ahora sí
  (validado operación por operación contra `2.Diseño y Arquitectura/Contratos/`).
- **Errores 500 corregidos:** PUT parcial de productos y proveedores, categoría o proveedor inexistente, documento o
  código de barras duplicado (ahora 422 o 409).
- **Requisitos que faltaban:** baja de productos, CRUD de categorías, precio y proveedores del producto, logout,
  cambio y recuperación de contraseña, permisos por rol en todos los servicios, devoluciones de cliente y a proveedor,
  gestión de bodegas, reportes de existencias, valorización y rotación, y dashboard.
- **Dockerfiles uniformes** con workers e hilos configurables; `debug=True` desactivado; sin `container_name`.
- **Locust en su propio contenedor** (servicio `locust`, perfil `pruebas`) y preparación de datos corregida (P43 fallaba por stock).
