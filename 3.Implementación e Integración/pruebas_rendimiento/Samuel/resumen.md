# Resumen de pruebas de rendimiento

Criterio: p95 < 2000 ms y fallos ≤ 1.0 % (RNF06).

## Integrante 3 · Productos, Proveedores y Logística

| ID | Escenario | Tipo | Usuarios | Peticiones | Fallos % | RPS | Mediana ms | p95 ms | p99 ms | Máx ms | Cumple |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|:--:|
| P31 | Listado de productos, categorías y unidades | Carga normal | 20 | 2317 | 0.0 | 19.5 | 17 | 21 | 26 | 40 | SÍ |
| P32 | Detalle y búsqueda de productos | Carga normal | 20 | 2307 | 0.0 | 19.4 | 17 | 21 | 25 | 55 | SÍ |
| P33 | Creación de productos | Carga normal | 20 | 2292 | 0.0 | 19.3 | 19 | 23 | 29 | 54 | SÍ |
| P34 | Actualización de productos | Carga normal | 20 | 2318 | 0.0 | 19.5 | 19 | 31 | 50 | 60 | SÍ |
| P35 | Consulta de proveedores | Carga normal | 20 | 2293 | 0.0 | 19.3 | 16 | 21 | 23 | 28 | SÍ |
| P36 | Crear, actualizar y desactivar proveedores | Carga normal | 20 | 6637 | 0.0 | 55.7 | 18 | 31 | 44 | 84 | SÍ |
| P37 | Consulta de clientes, paquetes y envíos | Carga normal | 20 | 2307 | 0.0 | 19.4 | 16 | 21 | 25 | 40 | SÍ |
| P38 | Creación de envíos | Carga normal | 30 | 9827 | 0.01 | 82.5 | 19 | 33 | 41 | 76 | SÍ |
| P39 | Ciclo de vida completo de un envío | Carga normal | 20 | 15048 | 0.0 | 84.0 | 18 | 34 | 46 | 114 | SÍ |
| P40 | Listado de productos con carga pico | Carga pico | 100 | 17379 | 0.01 | 97.0 | 18 | 26 | 43 | 134 | SÍ |
| P41 | Consulta de proveedores con carga pico | Carga pico | 100 | 17121 | 0.0 | 95.6 | 29 | 68 | 110 | 246 | SÍ |
| P42 | Creación de envíos con carga pico | Carga pico | 80 | 37824 | 0.0 | 211.0 | 37 | 81 | 110 | 178 | SÍ |
| P43 | Envíos con insumos (Logística → Inventarios) | Carga pico | 50 | 16476 | 0.0 | 92.0 | 33 | 65 | 85 | 135 | SÍ |
| P44 | Estrés de creación de productos | Estrés | 150 | 25603 | 0.0 | 142.9 | 19 | 33 | 50 | 108 | SÍ |
| P45 | Estrés mixto: lectura 80 % + escritura 20 % | Estrés | 300 | 15697 | 0.0 | 52.4 | 5100 | 7100 | 8100 | 10020 | NO |
