FROM python:3.12-slim


# Install the blazing-fast uv package manager
RUN pip install uv

WORKDIR /app

COPY shared/ ./shared/
# Inject the FastAPI serving logic
COPY online/ ./online/

# Shift execution context to the API directory
WORKDIR /app/online

# Install production dependencies globally inside the container
RUN uv pip install --system -r requirements.txt


# Start the server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "1010"]