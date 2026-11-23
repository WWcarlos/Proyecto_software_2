# Resumen de pruebas de rendimiento

Criterio: p95 < 2000 ms y fallos ≤ 1.0 % (RNF06).

## Integrante 2 · Inventarios y Analítica

| ID | Escenario | Tipo | Usuarios | Peticiones | Fallos % | RPS | Mediana ms | p95 ms | p99 ms | Máx ms | Cumple |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|:--:|
| P16 | Consulta de saldos y alertas | Carga normal | 20 | 525 | 0.0 | 18.1 | 32 | 42 | 56 | 65 | SÍ |
| P17 | Consulta de bodegas y movimientos | Carga normal | 20 | 537 | 0.0 | 18.6 | 31 | 43 | 60 | 67 | SÍ |
| P18 | Definir stock mínimo y consultar alertas | Carga normal | 20 | 525 | 0.0 | 18.1 | 56 | 83 | 95 | 104 | SÍ |
| P19 | Movimientos de ENTRADA | Carga normal | 20 | 489 | 0.0 | 16.9 | 110 | 160 | 180 | 216 | SÍ |
| P20 | Movimientos de SALIDA | Carga normal | 20 | 499 | 0.0 | 17.3 | 110 | 160 | 200 | 211 | SÍ |
| P21 | Traslados entre bodegas | Carga normal | 20 | 498 | 0.0 | 17.2 | 110 | 160 | 220 | 238 | SÍ |
| P22 | Consulta de indicadores (Analítica) | Carga normal | 20 | 537 | 0.0 | 18.5 | 33 | 42 | 64 | 69 | SÍ |
| P23 | Reportes de inventario JSON y CSV | Carga normal | 10 | 251 | 0.0 | 8.7 | 63 | 81 | 89 | 92 | SÍ |
| P24 | Recepción de eventos (Analítica) | Carga normal | 30 | 761 | 0.13 | 26.3 | 40 | 70 | 89 | 107 | SÍ |
| P25 | Consulta de saldos con carga pico | Carga pico | 100 | 2619 | 0.0 | 90.3 | 26 | 58 | 110 | 141 | SÍ |
| P26 | Movimientos mixtos con carga pico | Carga pico | 80 | 1346 | 0.0 | 46.4 | 1100 | 1400 | 1400 | 1533 | SÍ |
| P27 | Recepción de eventos con carga pico | Carga pico | 150 | 3631 | 0.0 | 125.1 | 74 | 190 | 250 | 317 | SÍ |
| P28 | Reportes de inventario con carga pico | Carga pico | 60 | 1475 | 0.0 | 50.8 | 62 | 120 | 170 | 222 | SÍ |
| P29 | Estrés de movimientos concurrentes | Estrés | 200 | 1374 | 0.0 | 47.3 | 2700 | 5100 | 5200 | 5288 | NO |
| P30 | Estrés de lectura Inventarios + Analítica | Estrés | 300 | 4426 | 0.0 | 152.4 | 1100 | 1500 | 1700 | 1828 | SÍ |
