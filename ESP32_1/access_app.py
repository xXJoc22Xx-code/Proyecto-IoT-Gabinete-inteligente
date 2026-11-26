"""ESP32 1: PIN por HTTPS, RFID local, cola durable y MQTTS. No mueve el servo.
En el primer arranque solicita configuración por la consola de Thonny.
"""
import asyncio
import gc
import time
import network
import ntptime
from machine import Pin
from hardware import Teclado, Avisos
from rc522 import RC522
from mqtt_tls import MQTT
from storage import Queue, read_json, write_json, unique
from tls_context import memory_report
from provisioning import load_or_setup


def epoch():
    # MicroPython puede usar época 2000 o 1970 según plataforma.
    offset = 946684800 if time.gmtime(0)[0] == 2000 else 0
    value = int(time.time()) + offset
    return value if value > 1700000000 else None


class Access:
    def __init__(self):
        self.notice = Avisos()
        self.keypad = Teclado()
        self.input_led = Pin(5, Pin.OUT, value=0)
        self.config = load_or_setup()
        self.queue = Queue()
        self.permissions = read_json('users.json', {'revision': 0, 'users': []})
        self.lock = read_json('lock.json', {'failures': 0, 'until': 0})
        self.stage = 'id'
        self.entry = ''
        self.user_id = ''
        self.blink_start = None
        self.key_flash = None
        self.last_key = time.ticks_ms()
        self.busy = False
        self.connected = False
        self.synced_at = None
        self.nonce = None
        self.lease = 0
        self.pending = None
        self.enrollment = None
        self.door_seen = None
        self.door_online = False
        self.door_session = None
        self.mqtt = None
        self.storage_fault = False
        try:
            self.reader = RC522()
        except OSError:
            self.reader = None
            print('RC522 no responde: teclado disponible; revisar cableado.')

    def event(self, kind, **data):
        event = dict(id=unique(), at=epoch(), kind=kind)
        event.update(data)
        try:
            self.queue.add(event)
            return True
        except OSError:
            self.storage_fault = True
            self.notice.resultado(False)
            print('Error de almacenamiento: no se autorizan aperturas.')
            return False

    def reset_input(self):
        self.stage = 'id'
        self.entry = ''
        self.user_id = ''
        self.blink_start = None
        self.input_led.value(0)

    def ready(self):
        return (self.connected and epoch() is not None and not self.storage_fault
                and self.synced_at is not None
                and time.ticks_diff(time.ticks_ms(), self.synced_at) < self.lease * 1000)

    def blocked(self):
        return self.lock.get('until', 0) > (epoch() or 0)

    def persist_lock(self):
        try:
            write_json('lock.json', self.lock)
        except OSError:
            self.storage_fault = True

    async def handle_key(self, key):
        if self.busy or self.pending or self.enrollment:
            return
        if self.door_session:
            if key == '#':
                await self.request_close()
            return
        self.last_key = time.ticks_ms()
        self.key_flash = self.last_key
        self.notice.tecla()
        if key == '*':
            if self.entry:
                self.entry = ''
            else:
                self.reset_input()
            self.blink_start = None
            return
        if key == '#':
            if self.stage == 'id':
                if not self.entry or self.entry[0] == '0':
                    self.notice.resultado(False)
                    self.reset_input()
                    return
                self.user_id = self.entry
                self.entry = ''
                self.stage = 'password'
                self.blink_start = time.ticks_ms()
            else:
                user_id, pin = self.user_id, self.entry
                self.reset_input()
                self.busy = True
                asyncio.create_task(self.check_pin(user_id, pin))
            return
        allowed = '0123456789' if self.stage == 'id' else '0123456789ABCD'
        limit = 6 if self.stage == 'id' else 12
        if key in allowed:
            self.blink_start = None
            if len(self.entry) < limit:
                self.entry += key
            else:
                self.notice.resultado(False)
                self.reset_input()

    async def check_pin(self, user_id, pin):
        try:
            if self.blocked():
                self.notice.resultado(False)
                return
            if not self.ready():
                self.event('acceso_no_disponible', method='keypad', reason='sin_sincronizacion')
                self.notice.resultado(False)
                return
            self.notice.patron([(80, 0, 0, 1), (420, 0, 0, 0)] * 10)
            from auth_https import authenticate
            result = await authenticate(self.config, user_id, pin)
            if result['result'] in ('blocked', 'retry'):
                if result['result'] == 'blocked':
                    self.lock['until'] = (epoch() or 0) + min(30, max(1, int(result.get('retry_after', 30))))
                    self.persist_lock()
                self.event('acceso_no_disponible', method='keypad', reason=result['result'])
                self.notice.resultado(False)
                return
            valid = result['result'] == 'authorized'
            if valid and result.get('revision') != self.permissions['revision']:
                self.event('acceso_no_disponible', method='keypad', reason='permisos_cambiaron')
                self.notice.resultado(False)
                return
            if valid:
                self.lock = {'failures': 0, 'until': 0}
                self.persist_lock()
                await self.request_open(user_id, 'keypad')
            else:
                self.lock['failures'] = self.lock.get('failures', 0) + 1
                if self.lock['failures'] >= 5:
                    self.lock = {'failures': 0, 'until': (epoch() or 0) + 30}
                self.persist_lock()
                self.event('acceso_denegado', method='keypad', reason='credencial_invalida')
                self.notice.resultado(False)
        except Exception as error:
            self.event('acceso_no_disponible', method='keypad', reason='autenticacion_sin_respuesta_valida')
            print('Fallo al validar PIN en servidor:', type(error).__name__)
            self.notice.resultado(False)
        finally:
            self.busy = False

    async def request_open(self, user_id, method):
        door_fresh = self.door_online and self.door_seen is not None and time.ticks_diff(time.ticks_ms(), self.door_seen) < 20000
        if not self.ready() or not door_fresh or self.pending or self.enrollment or self.door_session:
            self.event('apertura_no_disponible', user_id=user_id, method=method, reason='sin_conexion_o_operacion_ocupada')
            self.notice.resultado(False)
            return
        operation = unique()
        request = {'operation_id': operation, 'action': 'open', 'user_id': user_id, 'method': method,
                   'issued_at': epoch(), 'expires': epoch() + 5, 'revision': self.permissions['revision']}
        if not self.event('apertura_solicitada', user_id=user_id, method=method, operation_id=operation):
            return
        self.pending = {'operation_id': operation, 'user_id': user_id, 'action': 'open', 'started': time.ticks_ms(), 'request': request, 'last_send': time.ticks_ms()}
        self.notice.espera()
        try:
            # No se guarda ni reintenta esta orden: sólo el evento de auditoría.
            await self.mqtt.publish('acceso/solicitud', request)
        except Exception:
            self.pending = None
            self.notice.resultado(False)

    async def request_close(self):
        session = self.door_session
        if not session or not self.connected or not self.door_online or self.door_seen is None or time.ticks_diff(time.ticks_ms(), self.door_seen) >= 20000:
            self.notice.resultado(False)
            return
        now = epoch()
        if now is None:
            self.notice.resultado(False)
            return
        operation = unique()
        request = {'operation_id': operation, 'action': 'close', 'session_id': session['operation_id'],
                   'user_id': session['user_id'], 'issued_at': now, 'expires': now + 5}
        # El fallo de auditoria no impide intentar cerrar una puerta ya abierta.
        self.event('cierre_solicitado', user_id=session['user_id'], operation_id=operation)
        self.pending = {'operation_id': operation, 'user_id': session['user_id'], 'action': 'close',
                        'started': time.ticks_ms(), 'request': request, 'last_send': time.ticks_ms()}
        self.notice.espera()
        try:
            await self.mqtt.publish('acceso/solicitud', request)
        except Exception:
            self.pending = None
            self.notice.resultado(False)

    async def incoming(self, topic, data, retained):
        if not isinstance(data, dict):
            return
        if topic == 'gabinete/acceso/config':
            if retained or not self.nonce or data.get('nonce') != self.nonce:
                return
            users = data.get('users')
            if not isinstance(users, list) or len(users) > 50 or not isinstance(data.get('revision'), int):
                return
            for u in users:
                if (not isinstance(u, dict) or not isinstance(u.get('id'), str)
                        or not isinstance(u.get('cards'), list)):
                    return
            new = {'revision': data['revision'], 'users': users}
            if new != self.permissions:
                write_json('users.json', new)
                self.permissions = new
            self.nonce = None
            self.synced_at = time.ticks_ms()
            self.lease = min(25, max(0, int(data.get('lease', 0))))
        elif topic == 'gabinete/acceso/acuse':
            self.queue.ack(data.get('id'))
            if len(self.queue.names()) < 490:
                self.storage_fault = False
        elif topic == 'gabinete/estado/esp32_2':
            if not retained:
                self.door_seen = time.ticks_ms()
                self.door_online = data.get('online') is True
                if self.door_online and data.get('simulated') is not True:
                    if data.get('door_open') is True and isinstance(data.get('session_id'), str) and isinstance(data.get('user_id'), str):
                        self.door_session = {'operation_id': data['session_id'], 'user_id': data['user_id']}
                    elif data.get('door_open') is False:
                        self.door_session = None
                    # Recuperar confirmacion si se perdio la publicacion QoS0.
                    if isinstance(data.get('last_response'), dict):
                        await self.incoming('gabinete/puerta/respuesta', data['last_response'], False)
        elif topic == 'gabinete/acceso/enroll':
            if (not retained and data.get('cancel') is True and self.enrollment
                    and data.get('token') == self.enrollment['token']):
                self.enrollment = None
                self.notice.resultado(True)
                return
            if (not retained and epoch() and epoch() < data.get('expires', 0) <= epoch() + 35
                    and isinstance(data.get('token'), str) and not self.pending and not self.busy and not self.door_session):
                if not self.enrollment or self.enrollment['token'] != data['token']:
                    self.enrollment = dict(data)
                    self.reset_input()
                    self.notice.patron([(200, 1, 1, 1), (200, 0, 0, 0)] * 3)
                await self.mqtt.publish('acceso/enrollment', {'token': data['token'], 'ready': True,
                                                            'reader_available': self.reader is not None})
        elif topic == 'gabinete/puerta/respuesta':
            if retained or not self.pending or data.get('operation_id') != self.pending['operation_id']:
                return
            if time.ticks_diff(time.ticks_ms(), self.pending['started']) > 6000:
                return
            # Simulaciones nunca se presentan como accionamiento físico confirmado.
            simulated = data.get('simulated') is True
            action = self.pending.get('action', 'open')
            expected = 'servo_cerrado' if action == 'close' else 'servo_accionado'
            success = data.get('result') == expected and not simulated
            self.event('resultado_cierre' if action == 'close' else 'resultado_apertura',
                       user_id=self.pending['user_id'], operation_id=self.pending['operation_id'],
                       result=data.get('result', 'error'), simulated=simulated)
            if success:
                self.door_session = None if action == 'close' else {'operation_id': self.pending['operation_id'], 'user_id': self.pending['user_id']}
                self.reset_input()
            self.pending = None
            if success and action == 'close':
                self.notice.patron([(150, 1, 0, 1), (200, 0, 0, 0)] * 2)
            else:
                self.notice.resultado(success)

    async def ui(self):
        while True:
            self.notice.actualizar()
            key = self.keypad.leer()
            if key:
                await self.handle_key(key)
            now = time.ticks_ms()
            if time.ticks_diff(now, self.last_key) >= 15000 and not self.busy:
                self.reset_input()
            if self.blink_start is not None:
                elapsed = time.ticks_diff(now, self.blink_start)
                if elapsed < 900:
                    self.input_led.value((elapsed // 150) % 2 == 0)
                else:
                    self.blink_start = None
                    self.input_led.value(bool(self.entry))
            else:
                self.input_led.value(bool(self.entry))
            # Destello por tecla, aun cuando ya habia texto y el LED estaba fijo.
            if self.key_flash is not None:
                elapsed = time.ticks_diff(now, self.key_flash)
                if elapsed < 200:
                    self.input_led.value(30 <= elapsed < 150)
                else:
                    self.key_flash = None
            if self.pending and time.ticks_diff(now, self.pending['started']) >= 6000:
                self.event('cierre_sin_confirmar' if self.pending.get('action') == 'close' else 'apertura_sin_confirmar', operation_id=self.pending['operation_id'], user_id=self.pending['user_id'])
                self.pending = None
                self.notice.resultado(False)
            if self.enrollment and (epoch() or 0) >= self.enrollment['expires']:
                self.enrollment = None
            if not self.notice.cola:
                self.notice.verde.value(bool(self.door_session) and (now // 1000) % 2 == 0)
                if self.blocked():
                    self.notice.rojo.value((now // 700) % 2)
                elif not self.ready():
                    self.notice.rojo.value((now % 3000) < 150)
                else:
                    self.notice.rojo.value(0)
            await asyncio.sleep_ms(10)

    async def rfid(self):
        present = None
        last_seen = time.ticks_ms()
        while True:
            if self.reader and not self.busy and not self.pending and not self.door_session:
                uid = self.reader.uid()
                if uid:
                    last_seen = time.ticks_ms()
                    if self.enrollment:
                        # Tambien captura tarjetas presentes antes de iniciar el registro.
                        present = uid
                        await self.enroll_card(uid)
                    elif uid != present:
                        present = uid
                        if self.ready():
                            user = next((u for u in self.permissions['users'] if u['active'] and uid in u['cards']), None)
                            if user:
                                await self.request_open(user['id'], 'card')
                            else:
                                self.event('acceso_denegado', method='card', reason='tarjeta_no_autorizada')
                                self.notice.resultado(False)
                        else:
                            self.event('acceso_no_disponible', method='card', reason='sin_sincronizacion')
                            self.notice.resultado(False)
                elif time.ticks_diff(time.ticks_ms(), last_seen) > 700:
                    present = None
            await asyncio.sleep_ms(150)

    async def enroll_card(self, uid):
        e = self.enrollment
        if not e or not self.connected or not epoch() or epoch() >= e['expires']:
            return
        if 'uid' not in e:
            e['uid'] = uid
            self.notice.patron([(100, 1, 1, 1), (300, 1, 1, 0)])
        # Primera tarjeta fija durante esta sesion. Reintento si se pierde QoS0.
        now = time.ticks_ms()
        if 'sent_at' in e and time.ticks_diff(now, e['sent_at']) < 1000:
            return
        try:
            await self.mqtt.publish('acceso/enrollment', {'token': e['token'], 'uid': e['uid']})
            e['sent_at'] = now
        except Exception:
            print('Registro RFID pendiente de envio; se reintentara.')

    async def publisher(self):
        count = 0
        while True:
            if self.pending and self.pending.get('request'):
                request = self.pending['request']
                if epoch() and epoch() < request['expires'] and time.ticks_diff(time.ticks_ms(), self.pending['last_send']) >= 2000:
                    self.pending['last_send'] = time.ticks_ms()
                    await self.mqtt.publish('acceso/solicitud', request)
            if self.enrollment and self.enrollment.get('uid'):
                await self.enroll_card(self.enrollment['uid'])
            if count % 5 == 0:
                self.nonce = unique()
                await self.mqtt.publish('acceso/hello', {'nonce': self.nonce, 'revision': self.permissions['revision'], 'online': True,
                                                      'reader_available': self.reader is not None,
                                                      'enrollment_token': self.enrollment['token'] if self.enrollment else None})
                await self.mqtt.publish('estado/esp32_1', {'online': True, 'revision': self.permissions['revision'], 'queue': len(self.queue.names())})
            try:
                events = self.queue.batch()
            except OSError:
                self.storage_fault = True
                events = []
            for event in events:
                await self.mqtt.publish('acceso/eventos', event)
            await self.mqtt.send(0xC0)
            count += 1
            await asyncio.sleep(2)

    async def networking(self):
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        while True:
            tasks = []
            try:
                if not wlan.isconnected():
                    wlan.connect(self.config['ssid'], self.config['wifi_password'])
                    for _ in range(100):
                        if wlan.isconnected():
                            break
                        await asyncio.sleep_ms(200)
                    if not wlan.isconnected():
                        raise OSError('Wi-Fi no disponible')
                if epoch() is None:
                    ntptime.host = self.config.get('ntp_host', 'pool.ntp.org')
                    ntptime.settime()
                if epoch() is None:
                    raise OSError('Se requiere hora valida para TLS')
                gc.collect()
                self.mqtt = MQTT(self.config)
                await self.mqtt.connect()
                self.connected = True
                tasks = [asyncio.create_task(self.mqtt.listen(self.incoming)), asyncio.create_task(self.publisher())]
                await asyncio.gather(*tasks)
            except Exception as error:
                print('Conexion pendiente:', type(error).__name__, str(error))
                memory_report()
            finally:
                self.connected = False
                self.synced_at = None
                self.door_online = False
                for task in tasks:
                    task.cancel()
                if self.mqtt:
                    await self.mqtt.close()
                # Cancelar no basta: esperar a que cada tarea libere sus referencias.
                for task in tasks:
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
                tasks.clear()
                task = None
                self.mqtt = None
                gc.collect()
            await asyncio.sleep(5)

    async def run(self):
        self.event('arranque')
        print('Gabinete: ID# y contraseña#. No se imprimen credenciales.')
        await asyncio.gather(self.ui(), self.rfid(), self.networking())


def start():
    access = None
    try:
        access = Access()
        asyncio.run(access.run())
    except KeyboardInterrupt:
        print('Programa detenido')
    finally:
        if access:
            access.notice.cerrar()
            access.input_led.value(0)
        Pin(4, Pin.OUT, value=1)
