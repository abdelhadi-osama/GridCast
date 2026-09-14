FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY dashboard/ ./dashboard/

WORKDIR /app/dashboard

RUN uv pip install \
    --system \
    --no-cache \
    -r requirements.txt

EXPOSE 1013

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=1013", "--server.headless=true"]