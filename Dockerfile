FROM python:3.14.0-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY helpers helpers
COPY sql sql
COPY etl.py simulador.py preparar_datos.py ./
USER 10001
CMD ["python", "etl.py"]
