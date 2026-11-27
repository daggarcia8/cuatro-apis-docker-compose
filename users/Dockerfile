FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && mkdir -p /data
COPY app.py .
ENV DB_PATH=/data/users.db
EXPOSE 8000
CMD ["python", "app.py"]
