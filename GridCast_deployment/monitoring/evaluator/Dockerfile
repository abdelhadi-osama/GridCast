FROM python:3.12-slim

WORKDIR /app

COPY evaluator.py .
COPY metrics.py .

RUN uv pip install --no-cache-dir prometheus-client

EXPOSE 8000

CMD ["python", "metrics.py"]
