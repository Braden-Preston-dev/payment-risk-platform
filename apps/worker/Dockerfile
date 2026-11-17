FROM python:3.12-slim

WORKDIR /app

COPY apps/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/api/app ./app

CMD ["python", "-m", "app.worker"]
