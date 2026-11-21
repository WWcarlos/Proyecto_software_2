FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
RUN useradd --create-home appuser
USER appuser

EXPOSE 5000
CMD ["gunicorn", "--workers", "2", "--threads", "8", "--timeout", "60", "--access-logfile", "-", "--bind", "0.0.0.0:5000", "app:app"]
