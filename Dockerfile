FROM python:3.12-slim
WORKDIR /app
# all server modules (server.py imports service, storage, backbone_engine)
COPY facet_engine.py backbone_engine.py server.py service.py storage.py manage.py ./
COPY docs/ docs/
# unbuffered stdout so request/rate-limit/error logs are visible live
ENV PYTHONUNBUFFERED=1
# behind nginx: trust its forwarded client IP for per-IP rate limiting
ENV FACET_TRUST_PROXY=1
# NOTE: mount a writable volume for the SQLite DB and set FACET_DB to a path
# on it (e.g. FACET_DB=/data/facet.db) — otherwise game/account data is lost
# when the container is replaced.
EXPOSE 8080
CMD ["python3", "server.py"]
