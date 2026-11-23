# Resumen de pruebas de rendimiento

Criterio: p95 < 2000 ms y fallos ≤ 1.0 % (RNF06).

## Integrante 2 · Inventarios y Analítica

| ID | Escenario | Tipo | Usuarios | Peticiones | Fallos % | RPS | Mediana ms | p95 ms | p99 ms | Máx ms | Cumple |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|:--:|
| P16 | Consulta de saldos y alertas | Carga normal | 20 | 2277 | 0.0 | 19.1 | 31 | 41 | 54 | 97 | SÍ |
| P17 | Consulta de bodegas y movimientos | Carga normal | 20 | 2273 | 0.0 | 19.1 | 36 | 84 | 120 | 171 | SÍ |
| P18 | Definir stock mínimo y consultar alertas | Carga normal | 20 | 2215 | 0.0 | 18.6 | 60 | 89 | 100 | 145 | SÍ |
| P19 | Movimientos de ENTRADA | Carga normal | 20 | 2118 | 0.0 | 17.8 | 110 | 140 | 170 | 191 | SÍ |
| P20 | Movimientos de SALIDA | Carga normal | 20 | 2086 | 0.05 | 17.5 | 110 | 150 | 190 | 316 | SÍ |
| P21 | Traslados entre bodegas | Carga normal | 20 | 2120 | 0.0 | 17.8 | 110 | 150 | 180 | 233 | SÍ |
| P22 | Consulta de indicadores (Analítica) | Carga normal | 20 | 2286 | 0.0 | 19.2 | 32 | 42 | 57 | 70 | SÍ |
| P23 | Reportes de inventario JSON y CSV | Carga normal | 10 | 1069 | 0.0 | 9.0 | 85 | 110 | 120 | 159 | SÍ |
| P24 | Recepción de eventos (Analítica) | Carga normal | 30 | 3350 | 0.0 | 28.1 | 41 | 64 | 84 | 152 | SÍ |
| P25 | Consulta de saldos con carga pico | Carga pico | 100 | 17263 | 0.0 | 96.3 | 25 | 47 | 68 | 143 | SÍ |
| P26 | Movimientos mixtos con carga pico | Carga pico | 80 | 6624 | 0.0 | 37.0 | 980 | 5400 | 11000 | 11958 | NO |
| P27 | Recepción de eventos con carga pico | Carga pico | 150 | 24560 | 0.0 | 137.1 | 72 | 150 | 200 | 304 | SÍ |
| P28 | Reportes de inventario con carga pico | Carga pico | 60 | 3910 | 0.0 | 21.8 | 1700 | 2300 | 2400 | 2602 | NO |
| P29 | Estrés de movimientos concurrentes | Estrés | 200 | 11654 | 0.0 | 48.7 | 3500 | 3900 | 4000 | 4256 | NO |
| P30 | Estrés de lectura Inventarios + Analítica | Estrés | 300 | 10747 | 0.0 | 44.9 | 6000 | 8000 | 9200 | 11116 | NO |
