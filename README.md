Dirigera Prometheus Exporter

This container polls a Dirigera hub (using a Python client) for outlet metrics and exposes them for Prometheus.

Quick start

1. Copy `.env.example` to `.env` and fill in your credentials.

2. Build and run with Docker Compose (on a Raspberry Pi aarch64):

```bash
docker compose up --build -d
```

3. Verify metrics at `http://<host>:8000/metrics` (the exporter exposes Prometheus metrics on `/metrics`).

Prometheus scrape config example

Add this to your Prometheus `scrape_configs`:

```yaml
scrape_configs:
  - job_name: 'dirigera-exporter'
    static_configs:
      - targets: ['<exporter-host>:8000']
```

Files

- [docker-compose.yml](docker-compose.yml)
- [Dockerfile](Dockerfile)
- [app/main.py](app/main.py)
- [.env.example](.env.example)

Notes

- The code attempts to use a few common Dirigera client APIs. If the installed client exposes a different interface, update `build_client()` and `DirigeraAdapter.list_devices()` in `app/main.py`.
- The exporter looks for devices with type or name containing "outlet" or "plug". Adjust `find_outlets()` if your device types differ.
