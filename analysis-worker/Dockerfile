FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODEL_ID=PekingU/rtdetr_r50vd \
    VLM_MODEL_ID=Qwen/Qwen3-VL-2B-Instruct \
    ENABLE_VIDEO_LLM=true \
    ALLOWED_ORIGINS=https://g-p-6a5b7d751cf48191a652db596eaa1dc.vercel.app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libglib2.0-0 libgl1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
