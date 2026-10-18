FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bastion.py /app/bastion.py
COPY envparse.py /app/envparse.py
VOLUME ["/keys", "/captures"]
EXPOSE 22
CMD ["sh", "-c", "if [ ! -f /keys/host_rsa_key ]; then ssh-keygen -t rsa -b 2048 -f /keys/host_rsa_key -N '' -q; fi && python /app/bastion.py"]
