FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
# 1 worker + hilos: el arranque (crear tablas y sembrar datos) corre una sola vez.
CMD ["gunicorn", "-b", "0.0.0.0:8000", "--workers", "1", "--threads", "8", "--timeout", "60", "app.main:app"]
