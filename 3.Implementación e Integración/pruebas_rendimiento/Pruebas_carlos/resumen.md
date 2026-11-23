# Resumen de pruebas de rendimiento

Criterio: p95 < 2000 ms y fallos ≤ 1.0 % (RNF06).

## Integrante 1 · Gateway, Usuarios y Compras

| ID | Escenario | Tipo | Usuarios | Peticiones | Fallos % | RPS | Mediana ms | p95 ms | p99 ms | Máx ms | Cumple |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|:--:|
| P01 | Gateway: salud, rechazo sin token y ruta inexistente | Carga normal | 30 | 1520 | 0.0 | 52.3 | 3 | 6 | 10 | 24 | SÍ |
| P02 | Inicio de sesión (Usuarios) | Carga normal | 10 | 168 | 0.0 | 5.8 | 580 | 630 | 650 | 650 | SÍ |
| P03 | Validación de sesión (/auth/validar) | Carga normal | 20 | 524 | 0.0 | 18.1 | 30 | 63 | 95 | 110 | SÍ |
| P04 | Consulta de usuarios, roles y permisos | Carga normal | 20 | 505 | 0.0 | 17.4 | 34 | 98 | 150 | 168 | SÍ |
| P05 | Consulta de órdenes de compra | Carga normal | 20 | 529 | 0.0 | 18.3 | 22 | 33 | 70 | 90 | SÍ |
| P06 | Creación de órdenes de compra | Carga normal | 20 | 473 | 0.0 | 16.3 | 110 | 150 | 180 | 184 | SÍ |
| P07 | Flujo de compra extremo a extremo | Carga normal | 20 | 1086 | 0.0 | 37.5 | 100 | 250 | 280 | 294 | SÍ |
| P08 | Creación de usuarios (bcrypt + escritura) | Carga normal | 10 | 123 | 0.0 | 4.3 | 610 | 660 | 670 | 683 | SÍ |
| P09 | Gateway con token: lecturas a 4 servicios | Carga pico | 150 | 459 | 0.0 | 15.8 | 7300 | 12000 | 13000 | 13848 | NO |
| P10 | Inicio de sesión con carga pico | Carga pico | 50 | 315 | 0.0 | 10.8 | 2400 | 3900 | 4000 | 4232 | NO |
| P11 | Consulta de órdenes con carga pico | Carga pico | 100 | 133 | 0.0 | 4.6 | 11000 | 21000 | 22000 | 22748 | NO |
| P12 | Crear y cancelar órdenes con carga pico | Carga pico | 60 | 1060 | 0.0 | 36.5 | 260 | 490 | 570 | 644 | SÍ |
| P13 | Flujo de compra con carga pico | Carga pico | 50 | 1639 | 0.06 | 56.5 | 410 | 690 | 840 | 1035 | SÍ |
| P14 | Estrés de inicio de sesión | Estrés | 200 | 370 | 0.0 | 12.7 | 8400 | 14000 | 14000 | 14362 | NO |
| P15 | Estrés del flujo de compra | Estrés | 100 | 1278 | 0.0 | 44.0 | 910 | 1900 | 2100 | 2226 | SÍ |
