"""
Ejecuta las 45 pruebas de rendimiento (15 por integrante, con Locust) contra el API Gateway
y genera un resumen.

Uso (desde la carpeta pruebas_rendimiento, con el sistema levantado con docker compose):

    python ejecutar_pruebas.py --lista                 # tabla de las 45 pruebas
    python ejecutar_pruebas.py --integrante 1          # solo las 15 del integrante 1 (~40 min)
    python ejecutar_pruebas.py --integrante 2 --rapido # las 15 del integrante 2, 30 s cada una (verificar)
    python ejecutar_pruebas.py --solo P02 P09          # solo algunas
    python ejecutar_pruebas.py                         # las 45 (~2 h)
    python ejecutar_pruebas.py --integrante 1 --etiqueta antes   # guarda en resultados/antes/ (para antes/después)

Resultados: resultados/<etiqueta>/ -> Pxx.html (gráficas), Pxx_stats.csv, resumen.csv y resumen.md
La etiqueta por defecto es "integrante1", "integrante2", "integrante3" o "todas".
"""
import argparse
import csv
import os
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).parent

# Criterios de aceptación (RNF06: consultas en menos de 2 s bajo la carga definida)
P95_MAX_MS = 2000
FALLOS_MAX_PCT = 1.0

INTEGRANTES = {
    1: "Gateway, Usuarios y Compras",
    2: "Inventarios y Analítica",
    3: "Productos, Proveedores y Logística",
}

N, P, E = "Carga normal", "Carga pico", "Estrés"

# integrante, id, escenario, tipo, clase de Locust, usuarios, usuarios nuevos por segundo, duración
PRUEBAS = [
    # ---------------- Integrante 1 · Gateway, Usuarios y Compras ----------------
    (1, "P01", "Gateway: salud, rechazo sin token y ruta inexistente",  N, "GatewayRutas",            30,  5, "2m"),
    (1, "P02", "Inicio de sesión (Usuarios)",                           N, "Login",                   10,  2, "2m"),
    (1, "P03", "Validación de sesión (/auth/validar)",                  N, "UsuariosSesion",          20,  5, "2m"),
    (1, "P04", "Consulta de usuarios, roles y permisos",                N, "UsuariosConsulta",        20,  5, "2m"),
    (1, "P05", "Consulta de órdenes de compra",                         N, "ComprasLectura",          20,  5, "2m"),
    (1, "P06", "Creación de órdenes de compra",                         N, "ComprasCrear",            20,  5, "2m"),
    (1, "P07", "Flujo de compra extremo a extremo",                     N, "FlujoCompra",             20,  4, "3m"),
    (1, "P08", "Creación de usuarios (bcrypt + escritura)",             N, "UsuariosCrear",           10,  2, "2m"),
    (1, "P09", "Gateway con token: lecturas a 4 servicios",             P, "GatewayAutenticado",     150, 25, "3m"),
    (1, "P10", "Inicio de sesión con carga pico",                       P, "Login",                   50, 10, "2m"),
    (1, "P11", "Consulta de órdenes con carga pico",                    P, "ComprasLectura",         100, 20, "3m"),
    (1, "P12", "Crear y cancelar órdenes con carga pico",               P, "ComprasCancelar",         60, 10, "3m"),
    (1, "P13", "Flujo de compra con carga pico",                        P, "FlujoCompra",             50, 10, "3m"),
    (1, "P14", "Estrés de inicio de sesión",                            E, "Login",                  200, 20, "3m"),
    (1, "P15", "Estrés del flujo de compra",                            E, "FlujoCompra",            100, 10, "4m"),
    # ---------------- Integrante 2 · Inventarios y Analítica ----------------
    (2, "P16", "Consulta de saldos y alertas",                          N, "InventariosLectura",      20,  5, "2m"),
    (2, "P17", "Consulta de bodegas y movimientos",                     N, "BodegasMovimientosLectura", 20, 5, "2m"),
    (2, "P18", "Definir stock mínimo y consultar alertas",              N, "StockMinimo",             20,  5, "2m"),
    (2, "P19", "Movimientos de ENTRADA",                                N, "MovimientosEscritura",    20,  5, "2m"),
    (2, "P20", "Movimientos de SALIDA",                                 N, "MovimientosSalida",       20,  5, "2m"),
    (2, "P21", "Traslados entre bodegas",                               N, "MovimientosTraslado",     20,  5, "2m"),
    (2, "P22", "Consulta de indicadores (Analítica)",                   N, "AnaliticaLectura",        20,  5, "2m"),
    (2, "P23", "Reportes de inventario JSON y CSV",                     N, "AnaliticaReportes",       10,  2, "2m"),
    (2, "P24", "Recepción de eventos (Analítica)",                      N, "AnaliticaEventos",        30,  5, "2m"),
    (2, "P25", "Consulta de saldos con carga pico",                     P, "InventariosLectura",     100, 20, "3m"),
    (2, "P26", "Movimientos mixtos con carga pico",                     P, "MovimientosMixtos",       80, 15, "3m"),
    (2, "P27", "Recepción de eventos con carga pico",                   P, "AnaliticaEventos",       150, 25, "3m"),
    (2, "P28", "Reportes de inventario con carga pico",                 P, "AnaliticaReportes",       60, 10, "3m"),
    (2, "P29", "Estrés de movimientos concurrentes",                    E, "MovimientosMixtos",      200, 20, "4m"),
    (2, "P30", "Estrés de lectura Inventarios + Analítica",             E, "InventariosAnaliticaMixto", 300, 20, "4m"),
    # ---------------- Integrante 3 · Productos, Proveedores y Logística ----------------
    (3, "P31", "Listado de productos, categorías y unidades",           N, "ProductosLectura",        20,  5, "2m"),
    (3, "P32", "Detalle y búsqueda de productos",                       N, "ProductosBusqueda",       20,  5, "2m"),
    (3, "P33", "Creación de productos",                                 N, "ProductosEscritura",      20,  5, "2m"),
    (3, "P34", "Actualización de productos",                            N, "ProductosActualizar",     20,  5, "2m"),
    (3, "P35", "Consulta de proveedores",                               N, "ProveedoresLectura",      20,  5, "2m"),
    (3, "P36", "Crear, actualizar y desactivar proveedores",            N, "ProveedoresEscritura",    20,  5, "2m"),
    (3, "P37", "Consulta de clientes, paquetes y envíos",               N, "LogisticaLectura",        20,  5, "2m"),
    (3, "P38", "Creación de envíos",                                    N, "EnviosEscritura",         30,  5, "2m"),
    (3, "P39", "Ciclo de vida completo de un envío",                    N, "EnviosCicloVida",         20,  4, "3m"),
    (3, "P40", "Listado de productos con carga pico",                   P, "ProductosLectura",       100, 20, "3m"),
    (3, "P41", "Consulta de proveedores con carga pico",                P, "ProveedoresLectura",     100, 20, "3m"),
    (3, "P42", "Creación de envíos con carga pico",                     P, "EnviosEscritura",         80, 15, "3m"),
    (3, "P43", "Envíos con insumos (Logística → Inventarios)",          P, "EnviosInsumos",           50, 10, "3m"),
    (3, "P44", "Estrés de creación de productos",                       E, "ProductosEscritura",     150, 15, "3m"),
    (3, "P45", "Estrés mixto: lectura 80 % + escritura 20 %",           E, "EstresMixto",            300, 15, "5m"),
]


def listar():
    print(f"{'ID':<4} {'Integr.':<8} {'Tipo':<13} {'Usuarios':>8} {'Rampa/s':>8} {'Duración':>9}  Escenario")
    anterior = None
    for integrante, pid, nombre, tipo, _clase, u, r, t in PRUEBAS:
        if integrante != anterior:
            print(f"\n-- Integrante {integrante}: {INTEGRANTES[integrante]}")
            anterior = integrante
        print(f"{pid:<4} {integrante:<8} {tipo:<13} {u:>8} {r:>8} {t:>9}  {nombre}")


def ejecutar(prueba, host, salida, duracion_forzada):
    _integrante, pid, nombre, tipo, clase, usuarios, rampa, duracion = prueba
    if duracion_forzada:
        duracion = duracion_forzada
    prefijo = salida / pid
    comando = [
        sys.executable, "-m", "locust", "-f", str(AQUI / "locustfile.py"),
        "--headless", "--host", host, "-u", str(usuarios), "-r", str(rampa), "-t", duracion,
        "--csv", str(prefijo), "--html", str(prefijo) + ".html", "--only-summary",
        clase,
    ]
    print(f"\n=== {pid} · {nombre} · {tipo} · {usuarios} usuarios · {duracion} ===", flush=True)
    return subprocess.run(comando, cwd=AQUI).returncode


def leer_agregado(salida, pid):
    ruta = salida / f"{pid}_stats.csv"
    if not ruta.exists():
        return None
    with open(ruta, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            if fila["Name"] == "Aggregated":
                total = int(fila["Request Count"])
                fallos = int(fila["Failure Count"])
                return {
                    "peticiones": total,
                    "fallos": fallos,
                    "fallos_pct": round(100 * fallos / total, 2) if total else 100.0,
                    "rps": round(float(fila["Requests/s"]), 1),
                    "mediana_ms": int(float(fila["50%"])),
                    "p95_ms": int(float(fila["95%"])),
                    "p99_ms": int(float(fila["99%"])),
                    "max_ms": int(float(fila["Max Response Time"])),
                }
    return None


def escribir_resumen(salida, pruebas):
    filas = []
    for integrante, pid, nombre, tipo, _c, usuarios, _r, _d in pruebas:
        r = leer_agregado(salida, pid)
        if r is None:
            continue
        cumple = r["p95_ms"] < P95_MAX_MS and r["fallos_pct"] <= FALLOS_MAX_PCT
        filas.append({"integrante": integrante, "id": pid, "escenario": nombre, "tipo": tipo, "usuarios": usuarios,
                      **r, "cumple": "SÍ" if cumple else "NO"})
    if not filas:
        print("No hay resultados para resumir.")
        return
    with open(salida / "resumen.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    with open(salida / "resumen.md", "w", encoding="utf-8") as f:
        f.write(f"# Resumen de pruebas de rendimiento\n\nCriterio: p95 < {P95_MAX_MS} ms y fallos ≤ {FALLOS_MAX_PCT} % (RNF06).\n")
        actual = None
        for x in filas:
            if x["integrante"] != actual:
                actual = x["integrante"]
                f.write(f"\n## Integrante {actual} · {INTEGRANTES[actual]}\n\n")
                f.write("| ID | Escenario | Tipo | Usuarios | Peticiones | Fallos % | RPS | Mediana ms | p95 ms | p99 ms | Máx ms | Cumple |\n")
                f.write("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|:--:|\n")
            f.write(f"| {x['id']} | {x['escenario']} | {x['tipo']} | {x['usuarios']} | {x['peticiones']} | {x['fallos_pct']} | "
                    f"{x['rps']} | {x['mediana_ms']} | {x['p95_ms']} | {x['p99_ms']} | {x['max_ms']} | {x['cumple']} |\n")
    print(f"\nResumen guardado en {salida / 'resumen.md'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # En el contenedor de pruebas LOCUST_HOST apunta al gateway por su nombre en la red (http://gateway:8000).
    ap.add_argument("--host", default=os.getenv("LOCUST_HOST", "http://localhost:8080"), help="URL del API Gateway")
    ap.add_argument("--integrante", type=int, choices=sorted(INTEGRANTES), help="ejecutar solo las 15 de este integrante")
    ap.add_argument("--solo", nargs="+", metavar="Pxx", help="ejecutar solo estas pruebas")
    ap.add_argument("--rapido", action="store_true", help="30 s por prueba (solo para verificar)")
    ap.add_argument("--duracion", metavar="T", help="forzar la duración de todas las pruebas, p. ej. 45s o 1m")
    ap.add_argument("--etiqueta", help="subcarpeta de resultados (p. ej. antes / despues)")
    ap.add_argument("--lista", action="store_true", help="mostrar la tabla de pruebas")
    args = ap.parse_args()

    if args.lista:
        listar()
        return 0

    solo = {s.upper() for s in args.solo} if args.solo else None
    seleccion = [p for p in PRUEBAS
                 if (args.integrante is None or p[0] == args.integrante) and (solo is None or p[1] in solo)]
    if not seleccion:
        print("Ninguna prueba coincide con los filtros")
        return 1
    etiqueta = args.etiqueta or (f"integrante{args.integrante}" if args.integrante else "todas")
    salida = AQUI / "resultados" / etiqueta
    salida.mkdir(parents=True, exist_ok=True)

    for i, prueba in enumerate(seleccion):
        codigo = ejecutar(prueba, args.host, salida, args.duracion or ("30s" if args.rapido else None))
        if codigo not in (0, 1):  # locust devuelve 1 cuando hubo peticiones fallidas; otro código = error real
            print(f"Locust terminó con código {codigo} en {prueba[1]}; revisa que el sistema esté levantado en {args.host}")
        if i < len(seleccion) - 1:
            time.sleep(5)  # pausa para que el sistema se estabilice entre pruebas
    escribir_resumen(salida, seleccion)
    return 0


if __name__ == "__main__":
    sys.exit(main())
