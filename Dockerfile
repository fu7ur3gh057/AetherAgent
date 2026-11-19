FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Локальный Whisper (основной распознаватель голосовых). Отключить: --build-arg WITH_WHISPER=0
# av закреплён: с новыми av (проверено на 19) faster-whisper не открывает аудио (нет параметра metadata_errors)
ARG WITH_WHISPER=1
RUN if [ "$WITH_WHISPER" = "1" ]; then pip install --no-cache-dir "faster-whisper>=1.0" "av>=12,<14"; fi

COPY . .

# миграции при старте, затем бот
CMD ["sh", "-c", "alembic upgrade head && python -m src.app.main"]
