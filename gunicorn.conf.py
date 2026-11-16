"""One process keeps existing in-memory caches shared between request threads."""
bind = '0.0.0.0:8000'
workers = 1
worker_class = 'gthread'
threads = 4
timeout = 120
graceful_timeout = 30
max_requests = 500
max_requests_jitter = 50
accesslog = '-'
errorlog = '-'
# Omit query strings, cookies, authorization headers and response bodies.
access_log_format = '%(m)s %(U)s %(s)s %(D)s'
# Port 8000 is unpublished; only the private Compose networks can reach it.
forwarded_allow_ips = '*'
