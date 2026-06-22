FROM python:3.12-slim

# ffmpeg 用于抽帧/编码;libgl1、libglib2.0-0 是 OpenCV 运行所需的系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render 会把端口放到 $PORT 环境变量
ENV PORT=8000
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
