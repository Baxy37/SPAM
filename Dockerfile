FROM python:3.10-slim

# Установка системных зависимостей
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копирование файлов с зависимостями
COPY requirements.txt .

# Установка Python-зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копирование остальных файлов
COPY . .

# Порт для веб-сервера
EXPOSE 8080

# Переменные окружения
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Запуск бота
CMD ["python", "bot.py"]
