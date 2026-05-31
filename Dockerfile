FROM python:3.11-slim
WORKDIR /app
COPY bot/requirements.txt .
RUN pip install -r requirements.txt
COPY bot/ ./bot/
CMD ["python", "bot/bot.py"]
