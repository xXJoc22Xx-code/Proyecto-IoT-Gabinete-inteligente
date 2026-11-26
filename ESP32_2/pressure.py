"""Filtrado y presencia FSR402. Las lecturas ADC no son gramos ni pascales."""
SENSOR_PINS = (34, 35, 32)
WINDOW = 10
MAX_SPREAD = 150
MIN_CHANGE = 300


def valid_calibration(config):
    if not isinstance(config, dict) or config.get('version') != 1:
        return False
    sensors = config.get('sensors')
    if not isinstance(sensors, list) or len(sensors) != 3:
        return False
    for pin, sensor in zip(SENSOR_PINS, sensors):
        if not isinstance(sensor, dict) or sensor.get('pin') != pin:
            return False
        empty, loaded = sensor.get('empty_raw'), sensor.get('loaded_raw')
        if any(type(value) is not int or not 0 <= value <= 4095 for value in (empty, loaded)):
            return False
        if abs(loaded - empty) < MIN_CHANGE:
            return False
    return True


class PressureMonitor:
    def __init__(self, config=None):
        self.calibrated = valid_calibration(config)
        self.calibration = config['sensors'] if self.calibrated else None
        self.states = ['unknown'] * 3
        self.samples = []

    def clear(self):
        self.samples = []

    def add(self, raw):
        if (not isinstance(raw, (list, tuple)) or len(raw) != 3
                or any(type(value) is not int or not 0 <= value <= 4095 for value in raw)):
            self.clear()
            raise ValueError('Lectura ADC invalida')
        self.samples.append(list(raw))
        if len(self.samples) > WINDOW:
            self.samples.pop(0)

    def snapshot(self):
        if not self.samples:
            return None
        raw = []
        stable = len(self.samples) == WINDOW
        for i in range(3):
            total, low, high = 0, 4096, -1
            for row in self.samples:
                value = row[i]
                total += value
                low = min(low, value)
                high = max(high, value)
            raw.append(int(round(total / len(self.samples))))
            stable = stable and high - low <= MAX_SPREAD
        states = ['unknown'] * 3
        if stable and self.calibrated:
            for i, sensor in enumerate(self.calibration):
                # Tambien soporta modulos cuya salida disminuye con la presion.
                level = (raw[i] - sensor['empty_raw']) / (sensor['loaded_raw'] - sensor['empty_raw'])
                if level >= 0.65:
                    self.states[i] = 'present'
                elif level <= 0.35:
                    self.states[i] = 'absent'
            states = list(self.states)
        presence = ('present' if 'present' in states else
                    'unknown' if 'unknown' in states else 'absent')
        return {'pressure_raw': raw, 'sensor_presence': states, 'presence': presence,
                'pressure_calibrated': self.calibrated, 'pressure_stable': stable}


def inventory_change(before, after):
    """Compara contacto por sensor; no estima masa ni cantidad de objetos."""
    removed = any(a == 'present' and b == 'absent' for a, b in zip(before, after))
    returned = any(a == 'absent' and b == 'present' for a, b in zip(before, after))
    return ('cambio_mixto' if removed and returned else 'retiro' if removed else
            'devolucion' if returned else 'sin_cambio')
