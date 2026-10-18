FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        openssh-client && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py /app/server.py
COPY envparse.py /app/envparse.py
COPY watcher.py /app/watcher.py

VOLUME ["/shared/host_keys", "/fixtures", "/work"]
EXPOSE 22 8889
ENV SSH_HOST_KEY=/shared/host_keys/host_rsa_key
CMD ["sh", "-c", "until [ -f \"$SSH_HOST_KEY\" ]; do echo waiting for host key at $SSH_HOST_KEY; sleep 1; done; python /app/watcher.py & python /app/server.py"]
