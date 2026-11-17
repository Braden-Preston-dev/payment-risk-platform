FROM python:3.12-slim

# Set working directory inside container
WORKDIR /app

# Copy dependency file first (better layer caching)
COPY apps/api/requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY apps/api/app ./app
COPY apps/api/alembic ./alembic
COPY apps/api/alembic.ini ./alembic.ini
COPY models ./models

# Expose port (documentation only)
EXPOSE 8000

# Start server
CMD ["sh", "-c", "alembic -c alembic.ini upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
