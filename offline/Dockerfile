FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

RUN uv pip install \
    --system \
    --no-cache \
    -r offline/requirements.txt

# GridCast shared infrastructure
COPY shared/ ./shared/

# Offline forecasting service
COPY offline/ ./offline/

# Allows imports such as:
# from shared.model_loader import load_model
ENV PYTHONPATH=/app

WORKDIR /app/offline

EXPOSE 8001

CMD [
    "uvicorn",
    "api:app",
    "--host",
    "0.0.0.0",
    "--port",
    "1012"
]