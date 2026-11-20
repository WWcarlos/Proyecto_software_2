FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn==22.0.0

COPY app.py .
COPY inventarios_client.py .

ENV PORT=5003
ENV INVENTARIOS_MODE=stub
EXPOSE 5003

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5003", "app:app"]
