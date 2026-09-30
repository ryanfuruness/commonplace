FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY commonplace ./commonplace
RUN pip install --no-cache-dir .
ENV COMMONPLACE_DB=/data/commonplace.db PORT=8080
VOLUME ["/data"]
EXPOSE 8080
CMD ["python", "-m", "commonplace"]
