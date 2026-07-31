FROM python:3.11-slim

# Устанавливаем утилиту для синхронизации времени (новая версия)
RUN apt-get update && apt-get install -y ntpsec-ntpdate && apt-get clean

# Синхронизируем время при сборке
RUN ntpdate pool.ntp.org

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY bot.py .

# Синхронизируем время перед запуском бота
CMD ntpdate pool.ntp.org && python bot.py
