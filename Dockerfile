FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/js-development

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY js-development ./js-development
COPY scripts ./scripts
COPY .agent ./.agent
COPY js-learning ./js-learning
COPY knowledge ./knowledge
COPY README.md NERVOUS_SYSTEM.md AGENTS.md ./

RUN useradd --create-home --uid 10001 jarvis && chown -R jarvis:jarvis /app

RUN chmod +x scripts/init_data_volume.sh

# Install gosu so init_data_volume.sh can drop from root to the jarvis user
# after fixing ownership of the mounted /data volume.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

# Stay as root so the entrypoint can fix /data ownership before dropping
# privileges to jarvis via gosu.
ENTRYPOINT ["scripts/init_data_volume.sh"]
CMD ["python", "scripts/hosted_entrypoint.py"]
