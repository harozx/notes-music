FROM python:3.12-slim

# ffmpeg: yt-dlp dùng để sửa container m4a (đường dự phòng)
# deno:   yt-dlp cần để giải JS challenge của YouTube
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=denoland/deno:bin-2.5.6 /deno /usr/local/bin/deno

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py cache.py ./
COPY static static

# /data chứa cache audio + token Google -> mount volume để không mất khi build lại
ENV CACHE_DIR=/data/cache \
    DATA_DIR=/data \
    HOST=0.0.0.0 \
    PORT=8000 \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
CMD ["python", "app.py"]
