import os
import time
import logging
from dotenv import load_dotenv
from prometheus_client import start_http_server, Gauge

load_dotenv()

LOGGER = logging.getLogger("dirigera_exporter")
logging.basicConfig(level=logging.DEBUG)
# Enable debug logs for requests/urllib3 so we can inspect API calls
logging.getLogger("requests").setLevel(logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.DEBUG)

DIRIGERA_HOST = (
    os.getenv("DIRIGERA_HOST")
    or os.getenv("DIRIGERA_HOST".upper())
    or os.getenv("IP")
    or os.getenv("ip")
    or os.getenv("HOST")
    or os.getenv("host")
)
DIRIGERA_TOKEN = (
    os.getenv("DIRIGERA_TOKEN")
    or os.getenv("DIRIGERA_TOKEN".upper())
    or os.getenv("TOKEN")
    or os.getenv("token")
)
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))

# Prometheus metrics
OUTLET_ON = Gauge(
    "dirigera_outlet_on",
    "Outlet on/off state (1=on)",
    ["device_id", "name"],
)
OUTLET_POWER_W = Gauge(
    "dirigera_outlet_power_watts",
    "Outlet current power (W)",
    ["device_id", "name"],
)
OUTLET_CURRENT_ACTIVE_POWER_W = Gauge(
    "dirigera_outlet_current_active_power_watts",
    "Outlet current active power in watts as reported by Dirigera",
    ["device_id", "name"],
)
OUTLET_CURRENT_AMPS = Gauge(
    "dirigera_outlet_current_amps",
    "Outlet current in amperes as reported by Dirigera",
    ["device_id", "name"],
)
OUTLET_CURRENT_VOLTAGE = Gauge(
    "dirigera_outlet_current_voltage_volts",
    "Outlet voltage in volts as reported by Dirigera",
    ["device_id", "name"],
)
OUTLET_TOTAL_ENERGY_CONSUMED = Gauge(
    "dirigera_outlet_total_energy_consumed",
    "Outlet total energy consumed as reported by Dirigera",
    ["device_id", "name"],
)

# Generic per-device metrics (labels: device_id, name, type)
DEVICE_PRESENT = Gauge(
    "dirigera_device_present",
    "Device presence (1 = present)",
    ["device_id", "name", "type"],
)
DEVICE_ON = Gauge(
    "dirigera_device_on",
    "Device on/off state (1=on)",
    ["device_id", "name", "type"],
)
DEVICE_POWER_W = Gauge(
    "dirigera_device_power_watts",
    "Device current power (W)",
    ["device_id", "name", "type"],
)
DEVICE_BATTERY_PCT = Gauge(
    "dirigera_device_battery_percent",
    "Device battery percentage",
    ["device_id", "name", "type"],
)
DEVICE_LAST_SEEN = Gauge(
    "dirigera_device_last_seen_timestamp",
    "Device last seen as unix timestamp",
    ["device_id", "name", "type"],
)
DEVICE_TEMPERATURE_C = Gauge(
    "dirigera_device_temperature_celsius",
    "Device reported temperature in degrees Celsius",
    ["device_id", "name", "type"],
)
DEVICE_HUMIDITY_PCT = Gauge(
    "dirigera_device_humidity_percent",
    "Device reported relative humidity in percent",
    ["device_id", "name", "type"],
)


def safe_get(obj, *keys, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        for k in keys:
            if k in obj:
                return obj[k]
        return default
    for k in keys:
        value = getattr(obj, k, default)
        if value is not default:
            return value
    return default


def extract_device_attribute(device, *keys, default=None):
    if isinstance(device, dict):
        for key in keys:
            if key in device:
                return device[key]
        attrs = device.get("attributes") or {}
        if isinstance(attrs, dict):
            for key in keys:
                if key in attrs:
                    return attrs[key]
        elif attrs is not None:
            for key in keys:
                if hasattr(attrs, key):
                    return getattr(attrs, key)
        return default
    for key in keys:
        if hasattr(device, key):
            return getattr(device, key)
    attrs = safe_get(device, "attributes", default={}) or {}
    if isinstance(attrs, dict):
        for key in keys:
            if key in attrs:
                return attrs[key]
    elif attrs is not None:
        for key in keys:
            if hasattr(attrs, key):
                return getattr(attrs, key)
    if isinstance(attrs, dict):
        for key in keys:
            if key in attrs:
                return attrs[key]
    return default


class DirigeraAdapter:
    def __init__(self, client):
        self.client = client

    def list_devices(self):
        # Prefer the raw API response from /devices when available. The Hub
        # client wrappers convert dicts to device wrapper objects which put
        # many useful fields on nested attribute objects; the raw dict form
        # preserves original keys and is easier to parse for metrics.
        if hasattr(self.client, "get"):
            try:
                raw = self.client.get("/devices")
                if isinstance(raw, list) and len(raw) > 0:
                    return raw
            except Exception:
                # fall back to other listing methods
                pass

        # Try common client methods to list devices
        for name in ("devices", "get_devices", "list_devices", "all_devices", "get_all_devices"):
            if hasattr(self.client, name):
                func = getattr(self.client, name)
                return func()
        # try attribute
        if hasattr(self.client, "hub") and hasattr(self.client.hub, "devices"):
            return self.client.hub.devices
        raise RuntimeError("Dirigera client does not expose a device listing method")


def find_outlets(devices):
    outlets = []
    for d in devices:
        # support dict-like and object-like devices
        dtype = safe_get(d, "type", "device_type", "deviceType", default=None)
        dtype = (dtype or "").lower() if isinstance(dtype, str) else ""
        name = (
            safe_get(d, "name", "display_name", "displayName", "label", default=None)
            or "unknown"
        )
        if "outlet" in dtype or "plug" in dtype or "smartplug" in dtype or ("outlet" in name.lower()):
            outlets.append((d, name))
    return outlets


def read_state(device):
    is_on = extract_device_attribute(device, "isOn", "is_on", "on", "state", default=False)
    power = extract_device_attribute(
        device,
        "currentActivePower",
        "current_active_power",
        "power",
        "power_w",
        "power_watts",
        "current_power",
    )
    try:
        power_val = float(power) if power is not None else 0.0
    except Exception:
        power_val = 0.0
    return bool(is_on), power_val


def collect_and_update_metrics(client):
    adapter = DirigeraAdapter(client)
    try:
        devices = adapter.list_devices()
    except Exception as e:
        LOGGER.exception("Failed to list devices: %s", e)
        return

    # Log raw device data for debugging (may contain nested objects)
    try:
        import json

        def _default(o):
            return getattr(o, "__dict__", repr(o))

        LOGGER.debug("Raw devices: %s", json.dumps(devices, default=_default)[:8000])
    except Exception:
        try:
            LOGGER.debug("Raw devices repr: %s", repr(devices)[:8000])
        except Exception:
            LOGGER.debug("Raw devices: (could not repr)")

    outlets = find_outlets(devices)
    LOGGER.info("Found %d outlets", len(outlets))

    # If we found no devices, try the raw /devices endpoint and log response
    if len(devices) == 0 and hasattr(client, "get"):
        try:
            raw = client.get("/devices")
            LOGGER.debug("Client /devices raw response: %s", str(raw)[:8000])
        except Exception:
            LOGGER.exception("Failed to fetch raw /devices from client")

    # Update generic per-device metrics for every device
    for d in devices:
        # robust id extraction
        dev_id = None
        if isinstance(d, dict):
            dev_id = d.get("id") or d.get("device_id") or d.get("uuid")
        else:
            dev_id = getattr(d, "id", None) or getattr(d, "device_id", None)
        if not dev_id:
            dev_id = str(id(d))

        # robust name extraction
        name = None
        if isinstance(d, dict):
            name = d.get("name") or d.get("display_name") or d.get("label")
            attrs = d.get("attributes") or {}
            if not name:
                name = attrs.get("custom_name") or attrs.get("customName") or attrs.get("custom_name")
        else:
            name = safe_get(d, "attributes", "custom_name") or safe_get(d, "attributes", "customName")
            if not name:
                name = safe_get(d, "name", default=None) or safe_get(d, "display_name", default=None) or safe_get(d, "label", default=None)
        if not name:
            name = "unknown"

        # type extraction
        if isinstance(d, dict):
            dtype = (d.get("type") or d.get("device_type") or d.get("deviceType") or "").lower()
        else:
            dtype = (safe_get(d, "type", "device_type", "deviceType", default="") or "").lower()

        try:
            on, power = read_state(d)
        except Exception:
            LOGGER.exception("Failed to read state for device %s", dev_id)
            on, power = False, 0.0

        # battery
        battery = extract_device_attribute(d, "batteryPercentage", "battery_percentage", "battery")
        try:
            battery_val = float(battery) if battery is not None else None
        except Exception:
            battery_val = None

        # environment sensors (e.g. TIMMERFLOTTE report currentTemperature/currentRH)
        temperature = extract_device_attribute(
            d, "currentTemperature", "current_temperature", "temperature"
        )
        try:
            temperature_val = float(temperature) if temperature is not None else None
        except Exception:
            temperature_val = None

        humidity = extract_device_attribute(
            d, "currentRH", "current_r_h", "currentHumidity", "humidity"
        )
        try:
            humidity_val = float(humidity) if humidity is not None else None
        except Exception:
            humidity_val = None

        # last seen
        last_seen = extract_device_attribute(d, "lastSeen", "last_seen", "last_seen_at")
        ts = None
        try:
            if hasattr(last_seen, "timestamp"):
                ts = float(last_seen.timestamp())
            elif isinstance(last_seen, (int, float)):
                ts = float(last_seen)
            elif isinstance(last_seen, str):
                import datetime

                try:
                    dt = datetime.datetime.fromisoformat(last_seen)
                    ts = float(dt.timestamp())
                except Exception:
                    ts = None
        except Exception:
            ts = None

        DEVICE_PRESENT.labels(device_id=str(dev_id), name=name, type=dtype).set(1)
        DEVICE_ON.labels(device_id=str(dev_id), name=name, type=dtype).set(1 if on else 0)
        DEVICE_POWER_W.labels(device_id=str(dev_id), name=name, type=dtype).set(power)
        if battery_val is not None:
            DEVICE_BATTERY_PCT.labels(device_id=str(dev_id), name=name, type=dtype).set(battery_val)
        if temperature_val is not None:
            DEVICE_TEMPERATURE_C.labels(device_id=str(dev_id), name=name, type=dtype).set(temperature_val)
        if humidity_val is not None:
            DEVICE_HUMIDITY_PCT.labels(device_id=str(dev_id), name=name, type=dtype).set(humidity_val)
        if ts is not None:
            DEVICE_LAST_SEEN.labels(device_id=str(dev_id), name=name, type=dtype).set(ts)

    # Update outlet-specific metrics for backward compatibility and expose outlet-specific measurements
    for dev, name in outlets:
        dev_id = safe_get(dev, "id", "device_id", default=str(id(dev)))
        try:
            on, power = read_state(dev)
            current_active_power = extract_device_attribute(dev, "currentActivePower", "current_active_power")
            current_amps = extract_device_attribute(dev, "currentAmps", "current_amps")
            current_voltage = extract_device_attribute(dev, "currentVoltage", "current_voltage")
            total_energy_consumed = extract_device_attribute(dev, "totalEnergyConsumed", "total_energy_consumed")

            OUTLET_ON.labels(device_id=str(dev_id), name=name).set(1 if on else 0)
            OUTLET_POWER_W.labels(device_id=str(dev_id), name=name).set(power)
            if current_active_power is not None:
                OUTLET_CURRENT_ACTIVE_POWER_W.labels(device_id=str(dev_id), name=name).set(float(current_active_power))
            if current_amps is not None:
                OUTLET_CURRENT_AMPS.labels(device_id=str(dev_id), name=name).set(float(current_amps))
            if current_voltage is not None:
                OUTLET_CURRENT_VOLTAGE.labels(device_id=str(dev_id), name=name).set(float(current_voltage))
            if total_energy_consumed is not None:
                OUTLET_TOTAL_ENERGY_CONSUMED.labels(device_id=str(dev_id), name=name).set(float(total_energy_consumed))
        except Exception:
            LOGGER.exception("Failed to update metrics for device %s", dev_id)


def build_client():
    # Best-effort attempt to construct a Dirigera client using common constructor patterns.
    try:
        import dirigera as dirigera_pkg
    except Exception as e:
        LOGGER.error("Could not import dirigera client: %s", e)
        raise
    # Try constructors and helper functions that accept host/token
    constructors = []
    if hasattr(dirigera_pkg, "Dirigera"):
        constructors.append(lambda: dirigera_pkg.Dirigera(host=DIRIGERA_HOST, token=DIRIGERA_TOKEN))
    if hasattr(dirigera_pkg, "DirigeraClient"):
        constructors.append(lambda: dirigera_pkg.DirigeraClient(DIRIGERA_HOST, DIRIGERA_TOKEN))
    if hasattr(dirigera_pkg, "Client"):
        constructors.append(lambda: dirigera_pkg.Client(DIRIGERA_HOST, DIRIGERA_TOKEN))
    # Leggin/dirigera provides a Hub class with signature Hub(token, ip_address)
    if hasattr(dirigera_pkg, "Hub"):
        constructors.insert(0, lambda: dirigera_pkg.Hub(DIRIGERA_TOKEN, DIRIGERA_HOST))

    for ctor in constructors:
        try:
            client = ctor()
            LOGGER.info("Constructed Dirigera client using %s", getattr(client, "__class__", type(client)))
            return client
        except Exception:
            LOGGER.debug("Constructor %s failed", ctor)

    # If the package exposes a helper like `connect` or `login_with_token`, try those
    for fn in ("connect", "login", "login_with_token", "from_host_token"):
        if hasattr(dirigera_pkg, fn):
            try:
                func = getattr(dirigera_pkg, fn)
                return func(DIRIGERA_HOST, DIRIGERA_TOKEN)
            except Exception:
                LOGGER.debug("Function %s failed", fn)

    raise RuntimeError("Unable to instantiate a Dirigera client - check the client library API and update build_client()")


def main():
    if not DIRIGERA_HOST or not DIRIGERA_TOKEN:
        LOGGER.error(
            "DIRIGERA_HOST and DIRIGERA_TOKEN (or `ip`/`token`) must be set in environment (see .env.example)"
        )
        return

    try:
        client = build_client()
    except Exception as e:
        LOGGER.exception("Failed to build Dirigera client: %s", e)
        return

    # Start Prometheus metrics server
    LOGGER.info("Starting metrics HTTP server on port %d", METRICS_PORT)
    start_http_server(METRICS_PORT)

    # Main poll loop
    while True:
        try:
            collect_and_update_metrics(client)
        except Exception:
            LOGGER.exception("Error during collection loop")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
