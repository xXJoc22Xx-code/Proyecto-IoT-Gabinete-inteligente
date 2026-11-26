from machine import Pin, PWM
import time
TIPO_BUZZER = 'activo'
NIVEL_ACTIVO_BUZZER = 0
# Orden fisico inferido de la prueba 1234567890ABCD (26/11/2026).
FILAS = (12, 13, 14, 27)
COLUMNAS = (26, 32, 33, 25)
TECLAS = ('123A', '456B', '789C', '*0#D')

class Teclado:
    def __init__(self):
        self.filas = [Pin(n, Pin.IN, Pin.PULL_UP) for n in FILAS]
        # Columnas inactivas en alta impedancia: evita enfrentar salidas
        # HIGH/LOW cuando se presionan varias teclas simultaneamente.
        self.columnas = [Pin(n, Pin.IN) for n in COLUMNAS]
        self.candidato = None
        self.estable = None
        self.desde = time.ticks_ms()
        self.armado = True

    def scan(self):
        pulsadas = []
        for c, pin in enumerate(self.columnas):
            pin.init(Pin.OUT, value=0)
            try:
                time.sleep_us(50)
                for r, fila in enumerate(self.filas):
                    if fila.value() == 0:
                        pulsadas.append(TECLAS[r][c])
            finally:
                pin.init(Pin.IN, pull=None)
        if len(pulsadas) > 1:
            return 'MULTIPLE'
        return pulsadas[0] if pulsadas else None

    def leer(self):
        actual = self.scan()
        ahora = time.ticks_ms()
        if actual != self.candidato:
            self.candidato = actual
            self.desde = ahora
        if time.ticks_diff(ahora, self.desde) < 35:
            return None
        if actual == self.estable:
            return None
        self.estable = actual
        if actual is None:
            self.armado = True
        elif self.armado:
            self.armado = False
            if actual != 'MULTIPLE':
                return actual
        return None


class Avisos:
    def __init__(self):
        self.verde = Pin(16, Pin.OUT, value=0)
        self.rojo = Pin(17, Pin.OUT, value=0)
        self.pwm = None
        self.buzzer = None
        if TIPO_BUZZER == 'pasivo':
            self.buzzer = Pin(4, Pin.OUT, value=0)
            self.pwm = PWM(self.buzzer, freq=2000, duty_u16=0)
        elif TIPO_BUZZER == 'activo':
            self.buzzer = Pin(4, Pin.OUT, value=1-NIVEL_ACTIVO_BUZZER)
        elif TIPO_BUZZER != 'ninguno':
            raise ValueError('TIPO_BUZZER invalido')
        self.cola = []
        self.inicio = time.ticks_ms()

    def salidas(self, verde, rojo, sonido):
        self.verde.value(verde)
        self.rojo.value(rojo)
        if self.pwm:
            self.pwm.duty_u16(32768 if sonido else 0)
        elif self.buzzer:
            self.buzzer.value(NIVEL_ACTIVO_BUZZER if sonido else 1-NIVEL_ACTIVO_BUZZER)

    def patron(self, pasos):
        # Cada paso: duracion_ms, verde, rojo, sonido.
        self.cola = list(pasos)
        self.inicio = time.ticks_ms()
        self.salidas(*self.cola[0][1:])

    def actualizar(self):
        if self.cola and time.ticks_diff(time.ticks_ms(), self.inicio) >= self.cola[0][0]:
            self.cola.pop(0)
            self.inicio = time.ticks_ms()
            if self.cola:
                self.salidas(*self.cola[0][1:])
            else:
                self.salidas(0, 0, 0)

    def tecla(self):
        self.patron([(45, 0, 0, 1)])

    def espera(self):
        # Ciclo de dos segundos: luz un segundo, pausa un segundo, pitido corto.
        self.patron([(100, 1, 0, 1), (900, 1, 0, 0), (1000, 0, 0, 0)] * 3)

    def resultado(self, autorizado):
        if autorizado:
            self.patron([(150, 1, 0, 1), (1000, 1, 0, 0)])
        else:
            self.patron([(150, 0, 1, 1), (150, 0, 0, 0)] * 3)

    def cerrar(self):
        self.salidas(0, 0, 0)
        if self.pwm:
            self.pwm.deinit()
            self.buzzer.init(Pin.OUT, value=0)

