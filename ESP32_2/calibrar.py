"""Con main.py detenido en Thonny: import calibrar; calibrar.run()."""
import time
from hardware import PressureSensors
from pressure import SENSOR_PINS, MAX_SPREAD, MIN_CHANGE
from storage import write_json


def average(sensors, index, count=40):
    values = []
    for _ in range(count):
        values.append(sensors.read()[index])
        time.sleep_ms(25)
    if max(values) - min(values) > MAX_SPREAD:
        raise ValueError('Lectura inestable en sensor %d: repetir con carga quieta' % (index + 1))
    return int(round(sum(values) / len(values)))


def run():
    sensors = PressureSensors()
    calibration = []
    print('Calibracion de PRESENCIA: no convierte a gramos. Se calibran los tres sensores.')
    for i, pin in enumerate(SENSOR_PINS):
        input('Sensor %d (GPIO%d): retira la carga y pulsa Enter: ' % (i + 1, pin))
        time.sleep(1)
        empty = average(sensors, i)
        input('Coloca el objeto/carga que debe detectar ese sensor y pulsa Enter: ')
        time.sleep(1)
        loaded = average(sensors, i)
        print('Sensor %d: sin carga=%d, con carga=%d ADC' % (i + 1, empty, loaded))
        if abs(loaded - empty) < MIN_CHANGE:
            raise ValueError('Cambio insuficiente: revisar salida analogica, montaje y conexiones')
        calibration.append({'pin': pin, 'empty_raw': empty, 'loaded_raw': loaded})
    write_json('pressure.json', {'version': 1, 'sensors': calibration})
    print('Guardado pressure.json. Reinicia la placa. No hay tara automatica al arrancar.')


if __name__ == '__main__':
    run()
