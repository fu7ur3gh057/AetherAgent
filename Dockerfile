FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# миграции при старте, затем бот
CMD ["sh", "-c", "alembic upgrade head && python -m src.app.main"]
