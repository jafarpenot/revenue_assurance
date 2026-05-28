FROM python:3.12-slim

WORKDIR /app

# Install Python deps first so they stay cached when only code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code + branding assets.
COPY generate_data.py tools.py agents.py app.py run_demo.py ./
COPY assets/ ./assets/

# Generate the synthetic data inside the image (seed=42, so reproducible).
RUN python generate_data.py

# Gradio needs to listen on all interfaces inside the container.
ENV GRADIO_SERVER_NAME=0.0.0.0 \
    GRADIO_SERVER_PORT=7860 \
    PYTHONUNBUFFERED=1

EXPOSE 7860

CMD ["python", "app.py"]
