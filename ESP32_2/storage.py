import os
import json
import binascii
from errno import ENOENT


def unique():
    return binascii.hexlify(os.urandom(16)).decode()


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    with open(path + '.tmp', 'w') as f:
        json.dump(data, f)
    os.sync()
    os.rename(path + '.tmp', path)
    os.sync()


class Queue:
    # Un archivo por evento: no se reescribe toda la cola al agregar o confirmar.
    def __init__(self, directory='events', capacity=500):
        self.directory = directory
        self.capacity = capacity
        try:
            os.mkdir(directory)
        except OSError:
            pass
        # Un solo recorrido al arrancar, antes de abrir la conexion TLS.
        # Queue es el unico escritor de events durante la ejecucion.
        self._count = None
        self.count()

    def names(self):
        # Iterar evita cargar cientos de nombres en el heap de Python.
        for entry in os.ilistdir(self.directory):
            if entry[1] == 0x8000 and entry[0].endswith('.json'):
                yield entry[0]

    def count(self, limit=None):
        if self._count is None:
            self._count = sum(1 for _ in self.names())
        return self._count if limit is None else min(self._count, max(0, limit))

    def first_names(self, limit):
        # Los ID son aleatorios: ordenarlos no daba orden cronologico.
        # Tomar solo el lote necesario, sin recorrer toda la cola.
        if limit <= 0:
            return []
        selected = []
        for name in self.names():
            selected.append(name)
            if len(selected) >= limit:
                break
        return selected

    def add(self, event):
        if self.count(self.capacity) >= self.capacity:
            raise OSError('Cola llena: accesos suspendidos hasta sincronizar')
        path = self.directory + '/' + event['id'] + '.json'
        try:
            os.stat(path)
            exists = True
        except OSError as error:
            if error.args[0] != ENOENT:
                raise
            exists = False
        try:
            write_json(path, event)
        except OSError:
            # rename pudo completarse antes de un fallo en sync.
            self._count = None
            raise
        if not exists:
            self._count += 1

    def batch(self, limit=5):
        result = []
        for name in self.first_names(limit):
            data = read_json(self.directory + '/' + name)
            if data:
                result.append(data)
            else:
                raise OSError('Evento ilegible; conservar para diagnostico')
        return result

    def ack(self, event_id):
        if not isinstance(event_id, str) or len(event_id) != 32:
            return
        if any(c not in '0123456789abcdef' for c in event_id):
            return
        try:
            os.remove(self.directory + '/' + event_id + '.json')
        except OSError as error:
            if error.args[0] == ENOENT:
                return  # Un acuse repetido no vuelve a descontar.
            raise
        if self._count is not None:
            self._count = max(0, self._count - 1)
        try:
            os.sync()
        except OSError:
            self._count = None
            raise
