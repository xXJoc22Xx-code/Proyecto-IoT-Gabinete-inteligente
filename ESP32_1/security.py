import hashlib
import binascii
import asyncio


def hmac256(key, data):
    if len(key) > 64:
        key = hashlib.sha256(key).digest()
    key = key + b'\x00' * (64 - len(key))
    inner = bytes(x ^ 0x36 for x in key)
    outer = bytes(x ^ 0x5c for x in key)
    return hashlib.sha256(outer + hashlib.sha256(inner + data).digest()).digest()


async def derive(pin, salt_hex, rounds):
    if rounds != 20000:
        raise ValueError('Iteraciones no admitidas')
    key = pin.encode()
    salt = binascii.unhexlify(salt_hex)
    if len(salt) != 16:
        raise ValueError('Sal invalida')
    u = hmac256(key, salt + b'\x00\x00\x00\x01')
    result = bytearray(u)
    for i in range(1, rounds):
        u = hmac256(key, u)
        for j in range(32):
            result[j] ^= u[j]
        if i % 50 == 0:
            await asyncio.sleep_ms(0)
    return binascii.hexlify(result).decode()


def equal(a, b):
    if len(a) != len(b):
        return False
    difference = 0
    for x, y in zip(a.encode(), b.encode()):
        difference |= x ^ y
    return difference == 0
