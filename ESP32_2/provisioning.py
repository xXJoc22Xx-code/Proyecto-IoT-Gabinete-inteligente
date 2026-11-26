"""Configuración local por consola en el primer arranque; no contiene secretos."""
import os
from storage import read_json, write_json


def valid(config):
    if not isinstance(config, dict):
        return False
    for name in ('ssid', 'mqtt_host', 'mqtt_user', 'mqtt_password'):
        if not isinstance(config.get(name), str) or not config[name]:
            return False
    return (isinstance(config.get('wifi_password'), str)
            and isinstance(config.get('mqtt_port'), int)
            and 1 <= config['mqtt_port'] <= 65535
            and config.get('device_id') == 'esp32_2')


def required(prompt):
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print('Este campo no puede quedar vacío.')


def configure():
    print('\nCONFIGURACIÓN INICIAL ESP32 2')
    print('Escribe en la consola de Thonny, no en el keypad.')
    print('La consola puede mostrar lo escrito. No compartas capturas con contraseñas.')
    ssid = required('SSID Wi-Fi (2.4 GHz): ')
    wifi_password = input('Contraseña Wi-Fi (vacía si la red es abierta): ')
    host = required('IP o nombre del servidor MQTTS: ')
    while True:
        value = input('Puerto MQTTS [8883]: ').strip() or '8883'
        try:
            port = int(value)
            if 1 <= port <= 65535:
                break
        except ValueError:
            pass
        print('Escribe un puerto entre 1 y 65535.')
    user = required('Usuario MQTTS de esta placa: ')
    while True:
        password = input('Contraseña MQTTS: ')
        if password:
            break
        print('La contraseña del broker es obligatoria.')
    config = {'device_id': 'esp32_2', 'ssid': ssid, 'wifi_password': wifi_password,
              'mqtt_host': host, 'mqtt_port': port, 'mqtt_user': user,
              'mqtt_password': password, 'ntp_host': 'pool.ntp.org'}
    write_json('config.json', config)
    print('Configuración guardada en la placa. Continuando con la conexión...')
    return config


def load_or_setup():
    try:
        os.stat('ca.der')
    except OSError:
        raise ValueError('Falta ca.der: copia el certificado junto a main.py.')
    config = read_json('config.json')
    if valid(config):
        return config
    return configure()
