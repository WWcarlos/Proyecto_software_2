# Participante 3 – Gateway + Usuarios + Compras (Flask + MySQL) + Inventarios

## Levantar
```bash
docker compose up --build
```
Todo entra por el gateway: `http://localhost:8080`.

## Probar
```bash
# 1) Login (admin sembrado automáticamente)
curl -s -X POST localhost:8080/usuarios/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@inventarios.local","password":"Admin12345!"}'

TOKEN=<access_token>

# 2) Crear una bodega en Inventarios
curl -s -X POST localhost:8080/inventarios/bodegas -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"codigo":"BOG-01","nombre":"Bodega Bogotá"}'

# 3) Consultar saldos / alertas
curl -s localhost:8080/inventarios/saldos -H "Authorization: Bearer $TOKEN"

# 4) Listar órdenes de compra
curl -s localhost:8080/compras/ordenes -H "Authorization: Bearer $TOKEN"
```
Crear órdenes de compra requiere que **productos** y **proveedores** (de los otros compañeros) estén en el compose.

## Cómo encajan las piezas
- **Gateway** valida el JWT contra `usuarios /auth/validar` y reenvía `X-User-*`, `X-Usuario-Id` y `X-Service-Token`.
- **Inventarios** (sin modificar) exige `X-Service-Token == token` y lee el usuario de `X-Usuario-Id`;
  por eso el gateway y compras envían esas cabeceras.
- Inventarios escucha en el puerto **5000** (los demás en 8000); ya está configurado en el compose.
- Cada servicio tiene su MySQL; las tablas de usuarios y compras se crean solas al arrancar.


# Gateway y microservicios (Flask + MySQL)

**Rama:** `carlosdev`
**Autor:** carlos francisco moreno casas

## Descripción
Parte del Participante 3 del proyecto de microservicios de inventarios:

- **API Gateway:** único punto de entrada (puerto 8080). Valida el JWT y enruta por prefijo a cada servicio.
- **Usuarios:** autenticación, usuarios, roles y permisos.
- **Compras:** órdenes de compra y recepciones. Al recibir mercancía solicita la entrada a Inventarios.
- **Inventarios:** microservicio de mi compañero (bodegas, saldos, movimientos y alertas de stock mínimo).

Todos están hechos en Flask, y cada servicio tiene su propia base de datos MySQL.

## Cómo ejecutarlo
```bash
docker compose up --build
```
Todo entra por `http://localhost:8080`.

## Pruebas rápidas
```bash
# Login (el admin se crea automáticamente)
curl -s -X POST localhost:8080/usuarios/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@inventarios.local","password":"Admin12345!"}'

# Con el access_token obtenido
curl -s localhost:8080/inventarios/saldos -H "Authorization: Bearer $TOKEN"
curl -s localhost:8080/compras/ordenes -H "Authorization: Bearer $TOKEN"
```

## Estructura
```
gateway/      API Gateway
usuarios/     Microservicio de usuarios
compras/      Microservicio de compras
inventarios/  Microservicio de inventarios
docker-compose.yml
```
