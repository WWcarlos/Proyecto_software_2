FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY productos.yaml .

# Todos los microservicios escuchan en el 8000 (el gateway los resuelve por nombre en la red).
# Workers e hilos se pueden cambiar por variable de entorno (útil para las pruebas de rendimiento).
EXPOSE 8000
CMD ["sh", "-c", "exec gunicorn -b 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-2} --threads ${GUNICORN_THREADS:-4} --timeout 60 app:app"]
