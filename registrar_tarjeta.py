"""Ejecutar manualmente en Thonny para autorizar UNA tarjeta de prueba.
Reemplaza la tarjeta autorizada anterior. No modifica la memoria de la tarjeta.
"""
import time
import json
from rc522 import RC522

lector = RC522()
print('Registro manual: acerca SOLO la tarjeta que deseas autorizar.')
print('Tienes 30 segundos. Ctrl+C cancela.')
inicio = time.ticks_ms()
while time.ticks_diff(time.ticks_ms(), inicio) < 30000:
    uid = lector.uid()
    if uid:
        with open('tarjeta.json', 'w') as archivo:
            json.dump({'uid': uid}, archivo)
        print('Tarjeta guardada en la ESP32:', uid)
        print('Retirala y ejecuta main.py para probar el acceso.')
        break
    time.sleep_ms(100)
else:
    print('No se detecto tarjeta. No se cambio el registro.')
