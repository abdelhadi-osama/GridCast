FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY shared/ ./shared/
COPY online/ ./online/

WORKDIR /app/online

RUN uv pip install \
    --system \
    --no-cache \
    -r requirements.txt

EXPOSE 1011

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "1011"]