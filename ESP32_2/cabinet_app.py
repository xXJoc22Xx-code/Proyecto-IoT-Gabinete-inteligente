"""ESP32 2: servo, tres FSR402 y auditoria durable. Cierra con # desde ESP32 1.
Las confirmaciones describen PWM enviado; no hay sensor fisico de puerta.
"""
import asyncio
import gc
import time
import network
from hardware import Servo, PressureSensors
from pressure import PressureMonitor, inventory_change
from storage import Queue, read_json, write_json, unique
from mqtt_tls import MQTT
from tls_context import memory_report, sync_clock
from provisioning import load_or_setup

def epoch():
    offset=946684800 if time.gmtime(0)[0]==2000 else 0
    value=int(time.time())+offset
    return value if value>1700000000 else None

def valid_id(value):
    return isinstance(value,str) and len(value)==32 and all(c in '0123456789abcdef' for c in value)

class Cabinet:
    def __init__(self):
        self.servo=Servo()
        self.servo.angle(90)
        self.config=load_or_setup()
        self.sensors=PressureSensors()
        self.pressure=PressureMonitor(read_json('pressure.json',{}))
        self.queue=Queue()
        self.state=read_json('door.json',{'seen':[],'session':None,'last_reply':None})
        interrupted=self.state.get('session')
        self.state['session']=None
        # No reproducir una confirmacion de abierto despues de un reinicio.
        self.state['last_reply']=None
        self.storage_fault=False
        self.persist()
        self.event('arranque',reason='cierre_al_arrancar')
        if interrupted:
            self.event('sesion_interrumpida',operation_id=interrupted['operation_id'],user_id=interrupted['user_id'])
        self.mqtt=None
        self.connected=False
        self.busy=False
        self.sample_at=None
        self.last_pressure_event=time.ticks_ms()
        print('Gabinete: servo cerrado 90 grados; apertura 0 grados; cierre con #.')
        if not self.pressure.calibrated:
            print('FSR402: se envian lecturas ADC; ejecuta calibrar.run() para detectar presencia.')

    def persist(self):
        try:
            write_json('door.json',self.state)
            return True
        except OSError:
            self.storage_fault=True
            return False

    def event(self,kind,**data):
        event={'id':unique(),'at':epoch(),'kind':kind}
        event.update(data)
        try:
            self.queue.add(event)
            return True
        except OSError:
            self.storage_fault=True
            print('Auditoria pendiente: almacenamiento no disponible.')
            return False

    def pressure_reading(self):
        if self.sample_at is None or time.ticks_diff(time.ticks_ms(),self.sample_at)>2000:
            return None
        return self.pressure.snapshot()

    def stable_pressure(self):
        reading=self.pressure_reading()
        if (reading and reading['pressure_stable'] and reading['pressure_calibrated']
                and 'unknown' not in reading['sensor_presence']):
            return reading
        return None

    def status(self):
        session=self.state['session']
        return {'online':True,'door_open':bool(session),'session_id':session['operation_id'] if session else None,
                'user_id':session['user_id'] if session else None,'busy':self.busy,
                'pressure_calibrated':self.pressure.calibrated,'pressure_ready':self.stable_pressure() is not None,
                'last_response':self.state['last_reply'],'storage_fault':self.storage_fault}

    async def emit_status(self):
        if self.connected:
            try:
                await self.mqtt.publish('estado/esp32_2',self.status())
            except Exception:
                pass

    async def respond(self,reply):
        if self.connected:
            try:
                await self.mqtt.publish('puerta/respuesta',reply)
            except Exception:
                pass

    async def incoming(self,topic,data,retained):
        if not isinstance(data,dict) or retained:
            return
        if topic=='gabinete/inventario/acuse':
            started=time.ticks_ms()
            self.queue.ack(data.get('id'))
            # No recorrer cientos de archivos ni reescribir door.json por cada
            # acuse normal: estas operaciones bloquean todas las tareas asyncio.
            if self.storage_fault and self.queue.count(490)<490 and self.persist():
                self.storage_fault=False
            elapsed=time.ticks_diff(time.ticks_ms(),started)
            if elapsed>500:
                print('Acuse lento (flash):',elapsed,'ms')
            return
        if topic!='gabinete/acceso/solicitud':
            return
        now=epoch()
        if (not now or not valid_id(data.get('operation_id'))
            or not isinstance(data.get('issued_at'),int) or not isinstance(data.get('expires'),int)
            or not now<data['expires']<=now+6 or not now-6<=data['issued_at']<=now+2
            or data['expires']<=data['issued_at']):
            return
        operation=data['operation_id']
        if operation in self.state['seen']:
            reply=self.state.get('last_reply')
            if reply and reply['operation_id']==operation:
                await self.respond(reply)
            return
        action=data.get('action','open')
        session=self.state['session']
        user=data.get('user_id')
        if (action not in ('open','close') or not isinstance(user,str)
                or not user.isdigit() or not 1<=len(user)<=6 or user[0]=='0'):
            return
        if self.busy:
            await self.respond({'operation_id':operation,'result':'ocupado','action':action})
            return
        if action=='open' and (session or self.storage_fault):
            await self.respond({'operation_id':operation,'result':'no_disponible','action':action})
            return
        if action=='close' and (not session or data.get('session_id')!=session['operation_id'] or user!=session['user_id']):
            await self.respond({'operation_id':operation,'result':'sesion_invalida','action':action})
            return
        # Reservar antes de ceder control al movimiento para evitar doble accionamiento.
        self.busy=True
        asyncio.create_task(self.actuate(data,action))

    async def actuate(self,data,action):
        operation=data['operation_id']
        user=data['user_id']
        previous=self.state['session']
        try:
            self.state['seen']=(self.state['seen']+[operation])[-64:]
            if action=='open':
                self.state['session']={'operation_id':operation,'user_id':user,'before_pressure':self.stable_pressure()}
                if not self.persist() or not self.event('apertura_iniciada',operation_id=operation,user_id=user):
                    self.state['session']=None
                    self.persist()
                    await self.respond({'operation_id':operation,'result':'error_almacenamiento','action':action})
                    return
            # El cierre sigue permitido aunque el almacenamiento se haya llenado.
            self.servo.angle(0 if action=='open' else 90)
            await asyncio.sleep_ms(700)
            if action=='close':
                self.state['session']=None
            reply={'operation_id':operation,'action':action,'result':'servo_accionado' if action=='open' else 'servo_cerrado',
                   'session_id':operation if action=='open' else previous['operation_id'],'user_id':user,'simulated':False}
            self.state['last_reply']=reply
            self.persist()
            self.event('servo_abierto' if action=='open' else 'servo_cerrado',operation_id=operation,user_id=user)
            await self.respond(reply)
            await self.emit_status()
            if action=='close':
                if not self.pressure.calibrated:
                    self.event('inventario_indeterminado',operation_id=previous['operation_id'],
                               user_id=user,reason='presion_sin_calibrar')
                    return
                self.pressure.clear()
                await asyncio.sleep_ms(2000)
                for _ in range(16):
                    if self.stable_pressure() is not None:
                        break
                    await asyncio.sleep_ms(500)
                before=previous.get('before_pressure')
                after=self.stable_pressure()
                if before is None or after is None:
                    self.event('inventario_indeterminado',operation_id=previous['operation_id'],
                               user_id=user,reason='presion_no_estable_o_presencia_indeterminada')
                else:
                    kind=inventory_change(before['sensor_presence'],after['sensor_presence'])
                    self.event(kind,operation_id=previous['operation_id'],user_id=user,
                               before_raw=before['pressure_raw'],after_raw=after['pressure_raw'],
                               before_presence=before['sensor_presence'],after_presence=after['sensor_presence'],
                               **after)
        except Exception as error:
            self.storage_fault=True
            self.event('error_actuador',operation_id=operation,user_id=user,reason=type(error).__name__)
            await self.respond({'operation_id':operation,'action':action,'result':'error_actuador'})
        finally:
            self.busy=False
            await self.emit_status()

    async def sensing(self):
        while True:
            try:
                self.pressure.add(self.sensors.read())
                self.sample_at=time.ticks_ms()
                # Actualiza la histeresis continuamente, no solo al publicar.
                self.pressure.snapshot()
            except (OSError, ValueError):
                self.pressure.clear()
                self.sample_at=None
            now=time.ticks_ms()
            if time.ticks_diff(now,self.last_pressure_event)>=10000:
                self.last_pressure_event=now
                # Reservar espacio para acceso/cierre durante desconexiones largas.
                if self.queue.count(450)<450:
                    value=self.pressure_reading()
                    if value is not None:
                        self.event('lectura_presion',**value)
                    else:
                        self.event('sensores_no_disponibles',reason='sin_lectura_adc')
            await asyncio.sleep_ms(50)

    async def publisher(self):
        while True:
            # No dejar el primer keepalive detras de la cola pendiente.
            await self.mqtt.send(0xC0)
            await self.mqtt.publish('estado/esp32_2',self.status())
            started=time.ticks_ms()
            batch=self.queue.batch()
            elapsed=time.ticks_diff(time.ticks_ms(),started)
            if elapsed>1000:
                print('Lectura lenta de cola:',elapsed,'ms')
            for event in batch:
                await self.mqtt.publish('inventario/eventos',event)
                # Permitir procesar el acuse antes de enviar el siguiente evento.
                await asyncio.sleep_ms(100)
            await asyncio.sleep(2)

    async def networking(self):
        wlan=network.WLAN(network.STA_IF)
        wlan.active(True)
        clock_synced=False
        while True:
            tasks=[]
            stage='Wi-Fi'
            failed=False
            try:
                if not wlan.isconnected():
                    wlan.connect(self.config['ssid'],self.config['wifi_password'])
                    for _ in range(100):
                        if wlan.isconnected():
                            break
                        await asyncio.sleep_ms(200)
                    if not wlan.isconnected():
                        raise OSError('Wi-Fi no disponible')
                stage='NTP'
                if not clock_synced or epoch() is None:
                    sync_clock(self.config)
                    clock_synced=True
                if epoch() is None:
                    raise OSError('Hora no valida para TLS')
                print('UTC:',time.gmtime()[:6])
                stage='TLS/MQTT'
                memory_report('Antes de TLS')
                self.mqtt=MQTT(self.config)
                await self.mqtt.connect()
                self.connected=True
                print('ESP32 2 conectada por MQTTS.')
                tasks=[asyncio.create_task(self.mqtt.listen(self.incoming)),asyncio.create_task(self.publisher())]
                await asyncio.gather(*tasks)
            except Exception as error:
                failed=True
                print('Conexion pendiente [%s]:'%stage,type(error).__name__,str(error))
            finally:
                self.connected=False
                for task in tasks:
                    task.cancel()
                if self.mqtt:
                    await self.mqtt.close()
                # Cancelar no libera las referencias hasta que termina cada tarea.
                for task in tasks:
                    try:
                        await task
                    except (asyncio.CancelledError,Exception):
                        pass
                tasks.clear()
                task=None
                self.mqtt=None
                gc.collect()
                if failed:
                    memory_report('Tras liberar conexion')
            await asyncio.sleep(5)

    async def run(self):
        await asyncio.gather(self.sensing(),self.networking())

def start():
    cabinet=None
    try:
        cabinet=Cabinet()
        print('Eventos pendientes:',cabinet.queue.count())
        memory_report('Gabinete inicializado')
        asyncio.run(cabinet.run())
    except KeyboardInterrupt:
        print('Programa detenido. Reinicia para ordenar cierre a 90 grados.')
    finally:
        if cabinet:
            cabinet.servo.stop()


if __name__=='__main__':
    start()
