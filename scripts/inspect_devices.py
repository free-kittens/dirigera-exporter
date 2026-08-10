import os
import app.main as m
from dotenv import load_dotenv
load_dotenv()
client = m.build_client()
devices = m.DirigeraAdapter(client).list_devices()
print('list_devices returned', type(devices), len(devices))
outlets = m.find_outlets(devices)
print('find_outlets', len(outlets))
for dev, name in outlets:
    print('---')
    print('is dict', isinstance(dev, dict))
    if isinstance(dev, dict):
        print('id', dev.get('id'))
    else:
        print('id', getattr(dev, 'id', None))
    print('name label', name)
    print('dtype', m.safe_get(dev, 'type', 'device_type', 'deviceType'))
    if isinstance(dev, dict):
        attrs = dev.get('attributes') or {}
        for key in ['currentActivePower','current_active_power','currentAmps','current_amps','currentVoltage','current_voltage','totalEnergyConsumed','total_energy_consumed','batteryPercentage','battery_percentage','isOn','is_on','on','state']:
            print(' attr', key, attrs.get(key, '<MISSING>'))
    print('extract currentActivePower', m.extract_device_attribute(dev,'currentActivePower','current_active_power'))
    print('extract currentAmps', m.extract_device_attribute(dev,'currentAmps','current_amps'))
    print('extract currentVoltage', m.extract_device_attribute(dev,'currentVoltage','current_voltage'))
    print('extract totalEnergyConsumed', m.extract_device_attribute(dev,'totalEnergyConsumed','total_energy_consumed'))
    print('extract battery', m.extract_device_attribute(dev,'batteryPercentage','battery_percentage','battery'))
