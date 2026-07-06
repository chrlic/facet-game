FROM python:3.12-slim
WORKDIR /app
COPY facet_engine.py server.py ./
COPY docs/ docs/
EXPOSE 8080
CMD ["python3", "server.py"]
