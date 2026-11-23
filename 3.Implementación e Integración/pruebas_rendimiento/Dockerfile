# Contenedor para ejecutar las pruebas de rendimiento con Locust dentro de la red del sistema.
# Se usa desde el docker-compose.yml (servicio "locust", perfil "pruebas"); ver el readme de esta carpeta.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /pruebas

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY locustfile.py ejecutar_pruebas.py ./

# Usuario sin privilegios; el uid 1000 suele coincidir con el usuario de la máquina, así los
# resultados que se escriben en la carpeta montada quedan a nombre del usuario y no de root.
RUN useradd --uid 1000 --create-home locust && mkdir -p resultados && chown locust resultados
USER locust

# Los argumentos de "docker compose run locust ..." se pasan a ejecutar_pruebas.py
ENTRYPOINT ["python", "ejecutar_pruebas.py"]
CMD ["--lista"]
