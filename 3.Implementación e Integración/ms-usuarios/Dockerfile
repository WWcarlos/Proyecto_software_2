FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py openapi.yaml ./
RUN useradd --create-home appuser
USER appuser

EXPOSE 5000
# "python app.py" crea las tablas (y los datos iniciales) una sola vez antes de levantar gunicorn.
CMD ["sh", "-c", "python app.py && exec gunicorn --workers 2 --threads 4 --timeout 60 --access-logfile - --bind 0.0.0.0:5000 app:app"]
