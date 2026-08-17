FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MEDIA_ROOT=/media \
    DATA_ROOT=/data \
    APP_RUNTIME_ROOT=/data/app_runtime \
    NMM_RUNTIME_MANAGED=1 \
    NMM_RUNTIME_API=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/bootstrap
COPY requirements.txt /opt/bootstrap/requirements.txt
RUN pip install --no-cache-dir -r /opt/bootstrap/requirements.txt

# Bootstrap application: used only on first run or when the persistent app runtime
# does not have a current version yet. Future normal upgrades replace only /data/app_runtime/current.
COPY app /opt/bootstrap/app
COPY VERSION /opt/bootstrap/VERSION
COPY RUNTIME_API /opt/bootstrap/RUNTIME_API
COPY runtime /opt/runtime

EXPOSE 8000
CMD ["python", "/opt/runtime/launcher.py"]
