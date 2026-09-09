FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY codeflux ./codeflux
COPY config ./config
COPY streamlit_app.py ./streamlit_app.py
COPY .streamlit ./.streamlit
RUN pip install --no-cache-dir .
RUN mkdir -p /app/data

EXPOSE 8000
CMD ["python", "-m", "codeflux"]
