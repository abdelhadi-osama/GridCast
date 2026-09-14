FROM python:3.12-slim

# Install uv
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy dashboard application
COPY dashboard/ ./dashboard/

WORKDIR /app/dashboard
# Install dashboard dependencies
RUN uv pip install \
    --system \
    --no-cache \
    -r dashboard/requirements.txt

EXPOSE 1013

CMD [
    "streamlit",
    "run",
    "app.py",
    "--server.address=0.0.0.0",
    "--server.port=1013",
    "--server.headless=true"
]