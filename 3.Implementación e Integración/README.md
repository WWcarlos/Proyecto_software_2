# Sistema de Gestión de Inventarios – Implementación e Integración

Microservicios en Flask + MySQL, con un API Gateway propio como único punto de entrada.

## Arquitectura
```
cliente ──► gateway :8080 ──┬─► usuarios ──► usuarios-db       (login, JWT, roles, permisos)
 (único puerto publicado)   ├─► compras ───► compras-db        (órdenes, recepciones)
                            ├─► productos ─► productos-db
                            ├─► proveedores► proveedores-db
                            ├─► inventarios► inventarios-db    (bodegas, saldos, movimientos, alertas)
                            ├─► logistica ─► logistica-db      (clientes, paquetes, envíos)
                            └─► analitica ─► analitica-db      (eventos, indicadores, reportes)
```
- El gateway valida el JWT con `usuarios` y reenvía la identidad (`X-User-*`, `X-Usuario-Id`) y `X-Service-Token`.
- Compras → Productos / Proveedores / Inventarios · Inventarios → Analítica / Productos · Logística → Inventarios (REST).
- Cada servicio tiene su propia base de datos, sin puertos publicados; solo el gateway se expone.

## Levantar
```bash
cp .env.example .env        # cambia los valores (el .env no se sube a GitHub)
docker compose up --build
```
Todo entra por `http://localhost:8080/<servicio>/...`, por ejemplo:
```bash
curl -s -X POST localhost:8080/usuarios/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@inventarios.com","password":"Admin12345!"}'
curl -s localhost:8080/productos/ -H "Authorization: Bearer $TOKEN"
```
Documentación Swagger de cada servicio: `http://localhost:8080/<servicio>/docs` (productos, proveedores, inventarios, logística, analítica).

## Estructura
```
docker-compose.yml     único compose (apoyo local; la orquestación final será Kubernetes)
.env.example           variables y secretos
ms-gateway/            API Gateway propio
ms-usuarios/ ms-compras/ ms-productos/ ms-proveedores/ ms-inventarios/ ms-logistica/ ms-analitica/
pruebas_rendimiento/   pruebas con Locust (ver su README)
```

## Cambios respecto a la versión anterior
- **Un solo `docker-compose.yml`** con el gateway incluido. Antes había dos compose, dos copias de Inventarios y
  redes distintas (`red-gateway` externa y `red-microservicios`), así que Inventarios y Analítica no eran alcanzables desde el gateway.
- **Todos los servicios escuchan en el puerto 8000** (Inventarios y Analítica usaban el 5000) y se resuelven por nombre.
- **Solo el gateway publica un puerto**; se quitaron los puertos de MySQL y de cada microservicio.
- **Secretos por variables de entorno** (`.env`) en lugar de valores escritos en el compose.
- **Logística integrada de verdad con Inventarios** (`INVENTARIOS_MODE=http`; antes estaba en `stub`) y
  Inventarios valida los productos contra el servicio de Productos (`VALIDAR_PRODUCTO=true`).
- **Healthchecks** en todos los servicios; el gateway espera a que estén sanos.
- **Dockerfiles uniformes**, con gunicorn de 2 workers × 4 hilos configurable (`GUNICORN_WORKERS`, `GUNICORN_THREADS`).
  Antes los servicios corrían con 1 worker.
- **Error corregido en Logística**: el número de guía se calculaba con `COUNT(*)+1`; con dos envíos simultáneos salía la misma
  guía y la restricción UNIQUE devolvía error 500. Ahora se deriva del id autoincremental.
- **Error corregido en el login del admin**: el correo `admin@inventarios.local` era rechazado por la validación de emails (`.local` es un dominio reservado) y el login devolvía 422. El admin por defecto ahora es `admin@inventarios.com`.
- **Swagger detrás del gateway**: `/docs` cargaba `/openapi.yaml` con ruta absoluta y fallaba en `/<servicio>/docs`; ahora es relativa.
- `debug=True` desactivado en los `app.run` de los servicios.
