"""Credenciales solo por HTTPS verificado; nunca se publican ni encolan en MQTT."""
import asyncio
import gc
from tls_context import get_context
import json
from storage import unique

async def authenticate(config, user_id, password):
    request_id = unique()
    async def exchange():
        writer = None
        reader = None
        try:
            context = get_context()
            host = config['mqtt_host']
            port = config.get('auth_port', 8443)
            reader, writer = await asyncio.open_connection(host, port, ssl=context)
            body = json.dumps({'request_id': request_id, 'user_id': user_id, 'password': password}).encode()
            secret = config['mqtt_password']
            if '\r' in secret or '\n' in secret or '\r' in host or '\n' in host:
                raise ValueError('Configuracion HTTPS invalida')
            headers = ('POST /device/auth HTTP/1.1\r\nHost: %s:%s\r\n'
                       'X-Device-Key: %s\r\nContent-Type: application/json\r\n'
                       'Content-Length: %s\r\nConnection: close\r\n\r\n') % (host, port, secret, len(body))
            writer.write(headers.encode() + body)
            await writer.drain()
            # Respuesta pequena y limitada; no se registra contenido sensible.
            data = b''
            while True:
                chunk = await reader.read(512)
                if not chunk:
                    break
                data += chunk
                if len(data) > 4096:
                    raise ValueError('Respuesta HTTPS demasiado grande')
            head, payload = data.split(b'\r\n\r\n', 1)
            if head.split(b'\r\n', 1)[0].split()[1] != b'200':
                raise OSError('Servidor de autenticacion no disponible')
            result = json.loads(payload)
            if result.get('request_id') != request_id:
                raise ValueError('Respuesta de autenticacion no corresponde')
            if result.get('result') not in ('authorized', 'denied', 'blocked', 'retry'):
                raise ValueError('Respuesta de autenticacion invalida')
            return result
        finally:
            if writer:
                try:
                    writer.close()
                    await asyncio.wait_for(writer.wait_closed(), 1)
                except Exception:
                    pass
            reader = None
            writer = None
            gc.collect()
    return await asyncio.wait_for(exchange(), 5)
