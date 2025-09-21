# Gunicorn configuration file
bind = "0.0.0.0:8000"
workers = 3
timeout = 600  # 10 minutes
keepalive = 65
worker_class = "sync"
