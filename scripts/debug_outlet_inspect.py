import os
import dirigera
import app.main as main
from dotenv import load_dotenv

load_dotenv()

hub = dirigera.Hub(os.getenv("DIRIGERA_TOKEN"), os.getenv("DIRIGERA_HOST"))
try:
    devices = hub.get("/devices")
except Exception as exc:
    raise SystemExit(f"Failed to fetch /devices: {exc}")

print("device_count", len(devices))
outlets = []
for i, d in enumerate(devices):
    if not isinstance(d, dict):
        continue
    t = d.get("type")
    dt = d.get("deviceType")
    dt2 = d.get("device_type")
    name = d.get("name") or d.get("display_name") or d.get("label")
    if t == "outlet" or dt == "outlet" or dt2 == "outlet" or (name and "outlet" in name.lower()):
        outlets.append((i, d))

print("heuristic_outlets", len(outlets))
for index, d in outlets[:10]:
    print("---")
    print("index", index)
    print("keys", list(d.keys()))
    print("type", repr(d.get('type')))
    print("deviceType", repr(d.get('deviceType')))
    print("device_type", repr(d.get('device_type')))
    print("name", repr(d.get('name') or d.get('display_name') or d.get('label')))
    print("safe_get type", repr(main.safe_get(d, 'type', 'device_type', 'deviceType', default=None)))
    print("find_outlets", main.find_outlets([d]))
    print("read_state", main.read_state(d))
    print("battery", main.extract_device_attribute(d, 'batteryPercentage', 'battery_percentage', 'battery'))
    print("currentActivePower", main.extract_device_attribute(d, 'currentActivePower', 'current_active_power'))
    print("attrs", d.get('attributes'))
