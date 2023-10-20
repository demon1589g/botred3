# Используем базовый образ Ubuntu
#FROM python:3.8-slim-buster
FROM python

# Устанавливаем необходимые пакеты и Python
RUN apt-get update && apt-get install -y \
    python3-pip

# Создаем рабочую директорию в контейнере
WORKDIR /app

# Копируем файлы вашего проекта в контейнер
COPY rrr.py /app/
COPY configs.py /app/
COPY requirements.txt /app/

# Устанавливаем зависимости Python
RUN pip3 install --no-cache-dir -r requirements.txt

# Запуск вашего бота при старте контейнера
CMD ["python3", "rrr.py"]
