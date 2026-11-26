import os
import json
import binascii


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

    def names(self):
        return sorted(n for n in os.listdir(self.directory) if n.endswith('.json'))

    def add(self, event):
        if len(self.names()) >= self.capacity:
            raise OSError('Cola llena: accesos suspendidos hasta sincronizar')
        write_json(self.directory + '/' + event['id'] + '.json', event)

    def batch(self, limit=5):
        result = []
        for name in self.names()[:limit]:
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
            os.sync()
        except OSError:
            pass
