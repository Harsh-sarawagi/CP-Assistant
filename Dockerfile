FROM python:3.11-slim-bookworm

# Prevent Python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1

WORKDIR /app

# Debian-based ARM64 images can use the published scientific-package wheels.
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . /app/

# Collect static files for WhiteNoise to serve
RUN STATICFILES_STORAGE_BACKEND=whitenoise.storage.CompressedManifestStaticFilesStorage python manage.py collectstatic --noinput

RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app
USER app
ENV DJANGO_SETTINGS_MODULE=config.production

EXPOSE 8000

# Migrations are an explicit deployment step, never run by image build/startup.
CMD ["gunicorn", "--config", "gunicorn.conf.py", "config.wsgi:application"]
