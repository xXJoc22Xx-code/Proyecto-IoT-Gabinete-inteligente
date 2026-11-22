"""PRUEBA LOCAL de hardware, no firmware final de seguridad.
PIN de demostracion 1234. Sin Wi-Fi, MQTT, servo ni segundo ESP32.
"""
from machine import Pin, PWM
import time
import json
from rc522 import RC522

PIN_PRUEBA = '1234'  # Solo demostracion: retirar del codigo final entregado.
TIPO_BUZZER = 'activo'  # 'pasivo', 'activo' o 'ninguno'
NIVEL_ACTIVO_BUZZER = 0  # Modulo comprobado: LOW enciende, HIGH apaga.

FILAS = (13, 12, 14, 27)
COLUMNAS = (26, 25, 33, 32)
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


def ejecutar():
    teclado = Teclado()
    avisos = Avisos()
    try:
        autorizada = None
        try:
            with open('tarjeta.json') as archivo:
                registro = json.load(archivo)
            autorizada = registro['uid']
            if not isinstance(autorizada, str) or not autorizada:
                raise ValueError('UID invalido')
            print('Tarjeta autorizada cargada:', autorizada)
        except (OSError, ValueError, KeyError, TypeError):
            autorizada = None
            print('Sin tarjeta registrada: ejecuta registrar_tarjeta.py.')

        lector = None
        try:
            lector = RC522()
            print('RC522 responde. Version: 0x%02X' % lector.version)
        except OSError as error:
            print('ERROR RFID:', error)
            print('Puedes probar teclado, LEDs y buzzer. Corrige RFID y reinicia.')

        print('\nPRUEBA LOCAL: no abre ninguna puerta.')
        print('Escribe 1234 y # para validar. * borra todo.')
        print('A prueba verde; B rojo; C buzzer; D prueba conjunta.')
        print('Acerca una tarjeta. Retirala antes de volver a probar.')
        print('Buzzer configurado como:', TIPO_BUZZER)
        print('Ctrl+C detiene y apaga los indicadores.\n')
        entrada = ''
        ultima_tecla = time.ticks_ms()
        ultimo_rfid = time.ticks_ms()
        ultima_presencia = time.ticks_ms()
        tarjeta_presente = None
        while True:
            avisos.actualizar()
            tecla = teclado.leer()
            ahora = time.ticks_ms()
            if tecla is not None:
                # Mostrar teclas SOLO para verificar cableado durante esta prueba.
                print('Tecla:', tecla)
                ultima_tecla = ahora
                if tecla in '0123456789':
                    if len(entrada) < 8:
                        entrada += tecla
                        print('Entrada:', '*' * len(entrada))
                    else:
                        entrada = ''
                        print('Entrada demasiado larga: borrada.')
                        avisos.resultado(False)
                elif tecla == '*':
                    entrada = ''
                    print('Entrada borrada.')
                elif tecla == '#':
                    valido = entrada == PIN_PRUEBA
                    entrada = ''
                    print('PIN: ACCESO AUTORIZADO' if valido else 'PIN: ACCESO DENEGADO')
                    avisos.resultado(valido)
                else:
                    entrada = ''
                    if tecla == 'A':
                        avisos.patron([(1000, 1, 0, 0)])
                    elif tecla == 'B':
                        avisos.patron([(1000, 0, 1, 0)])
                    elif tecla == 'C':
                        avisos.patron([(200, 0, 0, 1)])
                    elif tecla == 'D':
                        avisos.patron([(500, 1, 0, 0), (500, 0, 1, 0), (200, 0, 0, 1)])

            if entrada and time.ticks_diff(ahora, ultima_tecla) > 15000:
                entrada = ''
                print('Entrada borrada por inactividad.')

            if lector and time.ticks_diff(ahora, ultimo_rfid) >= 150:
                ultimo_rfid = ahora
                uid = lector.uid()
                if uid:
                    ultima_presencia = time.ticks_ms()
                    if uid != tarjeta_presente:
                        tarjeta_presente = uid
                        entrada = ''
                        print('UID detectado:', uid)
                        valido = autorizada is not None and uid == autorizada
                        print('TARJETA: ACCESO AUTORIZADO' if valido else 'TARJETA: ACCESO DENEGADO')
                        avisos.resultado(valido)
                elif time.ticks_diff(time.ticks_ms(), ultima_presencia) > 700:
                    tarjeta_presente = None
            time.sleep_ms(5)
    except KeyboardInterrupt:
        print('\nPrueba detenida.')
    finally:
        avisos.cerrar()


if __name__ == '__main__':
    ejecutar()
