"""MQTT 3.1.1 sobre TLS verificado. Publicaciones QoS0 + acuses persistentes de aplicación.
Cliente reducido a los paquetes usados por el proyecto; no sustituye una biblioteca general.
"""
import asyncio
import gc
from tls_context import get_context, memory_report
import struct
import json


def string(value):
    data = value.encode() if isinstance(value, str) else value
    return struct.pack('!H', len(data)) + data


def packet(header, body):
    n = len(body)
    prefix = bytearray([header])
    while True:
        digit = n % 128
        n //= 128
        prefix.append(digit | (128 if n else 0))
        if not n:
            return bytes(prefix) + body


class MQTT:
    def __init__(self, config):
        self.config = config
        self.reader = None
        self.writer = None
        self.lock = asyncio.Lock()
        self.last_tx = 0
        self.last_rx = 0
        self.pings_sent = 0
        self.pings_received = 0

    async def send(self, header, body=b''):
        async with self.lock:
            self.writer.write(packet(header, body))
            try:
                await asyncio.wait_for(self.writer.drain(), 5)
            except asyncio.TimeoutError:
                raise OSError('MQTT TX agotado (5s), paquete=0x%02x; %s' % (header, self.diagnostic()))
            self.last_tx = header
            if header == 0xC0:
                self.pings_sent += 1

    def diagnostic(self):
        return 'ultimo TX=0x%02x RX=0x%02x; PING enviados=%d respuestas=%d' % (
            self.last_tx, self.last_rx, self.pings_sent, self.pings_received)

    async def receive(self):
        header = (await self.reader.readexactly(1))[0]
        length = 0
        multiplier = 1
        for _ in range(4):
            digit = (await self.reader.readexactly(1))[0]
            length += (digit & 127) * multiplier
            if not digit & 128:
                break
            multiplier *= 128
        else:
            raise OSError('Longitud MQTT invalida')
        if length > 65536:
            raise OSError('Paquete demasiado grande')
        body = await self.reader.readexactly(length)
        self.last_rx = header
        if header == 0xD0 and not body:
            self.pings_received += 1
        return header, body

    async def connect(self):
        c = self.config
        context = get_context()
        memory_report('CA cargada')
        # open_connection usa host como nombre del servidor para comprobar SAN.
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(c['mqtt_host'], c['mqtt_port'], ssl=context), 15)
        memory_report('Socket TLS creado, antes del handshake')
        body = string('MQTT') + bytes([4, 0xC6]) + struct.pack('!H', 30)
        body += string(c['device_id']) + string('gabinete/estado/' + c['device_id'])
        body += string('{"online":false}') + string(c['mqtt_user']) + string(c['mqtt_password'])
        await self.send(0x10, body)
        header, reply = await asyncio.wait_for(self.receive(), 5)
        if header != 0x20 or reply != b'\x00\x00':
            raise OSError('Broker rechazo conexion')
        topics = ['acceso/solicitud', 'inventario/acuse']
        body = b'\x00\x01' + b''.join(string('gabinete/' + t) + b'\x00' for t in topics)
        await self.send(0x82, body)
        while True:
            header, reply = await asyncio.wait_for(self.receive(), 5)
            if header == 0x90:
                if reply[:2] != b'\x00\x01' or len(reply) != 2 + len(topics) or any(x != 0 for x in reply[2:]):
                    raise OSError('Suscripcion rechazada')
                break

    async def publish(self, topic, data):
        try:
            await self.send(0x30, string('gabinete/' + topic) + json.dumps(data).encode())
        except OSError as error:
            raise OSError('Publicacion %s: %s' % (topic, error))

    async def listen(self, callback):
        while True:
            try:
                header, body = await asyncio.wait_for(self.receive(), 40)
            except asyncio.TimeoutError:
                raise OSError('MQTT RX agotado (40s); %s' % self.diagnostic())
            if header >> 4 == 3:
                size = struct.unpack('!H', body[:2])[0]
                if size + 2 > len(body):
                    raise OSError('Tema invalido')
                topic = body[2:2+size].decode()
                qos = (header >> 1) & 3
                if qos != 0:
                    raise OSError('QoS recibido no solicitado')
                try:
                    data = json.loads(body[2+size:])
                except ValueError:
                    continue
                await callback(topic, data, bool(header & 1))

    async def close(self):
        writer = self.writer
        self.reader = None
        self.writer = None
        try:
            if writer:
                try:
                    writer.close()
                    await asyncio.wait_for(writer.wait_closed(), 1)
                except Exception:
                    pass
        finally:
            writer = None
            gc.collect()
