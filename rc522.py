"""Lector de UID ISO14443A para una tarjeta a la vez; no escribe la tarjeta.
MicroPython ESP32. SPI: SCK18, MOSI23, MISO19, SS21, RST22.
"""
from machine import Pin, SPI
import time


def crc_a(data):
    crc = 0x6363
    for value in data:
        value ^= crc & 255
        value ^= (value << 4) & 255
        crc = ((crc >> 8) ^ (value << 8) ^ (value << 3) ^ (value >> 4)) & 65535
    return bytes((crc & 255, crc >> 8))


class RC522:
    def __init__(self):
        self.cs = Pin(21, Pin.OUT, value=1)
        self.rst = Pin(22, Pin.OUT, value=0)
        self.spi = SPI(2, baudrate=1000000, polarity=0, phase=0,
                       sck=Pin(18), mosi=Pin(23), miso=Pin(19))
        time.sleep_ms(10)
        self.rst.value(1)
        time.sleep_ms(50)
        self.write(0x01, 0x0F)
        time.sleep_ms(50)
        self.version = self.read(0x37)
        if self.version in (0x00, 0xFF):
            raise OSError('RC522 sin respuesta: revisar 3V3, GND y SPI')
        # Temporizador cercano a 25 ms y modulacion 100% ASK.
        for reg, value in ((0x2A, 0x80), (0x2B, 0xA9), (0x2C, 0x03),
                           (0x2D, 0xE8), (0x15, 0x40), (0x11, 0x3D),
                           (0x12, 0), (0x13, 0)):
            self.write(reg, value)
        self.write(0x14, self.read(0x14) | 3)
        time.sleep_ms(10)

    def write(self, reg, value):
        self.cs.value(0)
        try:
            self.spi.write(bytes(((reg << 1) & 0x7E, value & 255)))
        finally:
            self.cs.value(1)

    def read(self, reg):
        self.cs.value(0)
        try:
            self.spi.write(bytes((((reg << 1) & 0x7E) | 0x80,)))
            return self.spi.read(1)[0]
        finally:
            self.cs.value(1)

    def exchange(self, data, last_bits=0):
        self.write(0x01, 0)       # Idle
        self.write(0x04, 0x7F)    # Limpiar IRQ
        self.write(0x0A, 0x80)    # Vaciar FIFO
        for value in data:
            self.write(0x09, value)
        self.write(0x0D, last_bits)
        self.write(0x01, 0x0C)    # Transceive
        self.write(0x0D, 0x80 | last_bits)
        start = time.ticks_ms()
        try:
            while True:
                irq = self.read(0x04)
                if irq & 0x30:
                    break
                if irq & 1 or time.ticks_diff(time.ticks_ms(), start) > 60:
                    return None
            if self.read(0x06) & 0x1B:
                return None
            count = self.read(0x0A)
            if not 0 < count <= 64:
                return None
            data = bytes(self.read(0x09) for _ in range(count))
            tail = self.read(0x0C) & 7
            bits = (count - 1) * 8 + tail if tail else count * 8
            return data, bits
        finally:
            self.write(0x0D, last_bits)
            self.write(0x01, 0)

    def uid(self):
        # WUPA permite volver a consultar una tarjeta que permanece presente.
        self.write(0x08, self.read(0x08) & ~8)
        self.write(0x0E, self.read(0x0E) & ~0x80)
        response = self.exchange(b'\x52', 7)
        if response is None or response[1] != 16:
            return None
        uid = bytearray()
        for level in (0x93, 0x95, 0x97):
            response = self.exchange(bytes((level, 0x20)))
            if response is None or response[1] != 40:
                return None
            block = response[0]
            if block[0] ^ block[1] ^ block[2] ^ block[3] != block[4]:
                return None
            select = bytes((level, 0x70)) + block
            response = self.exchange(select + crc_a(select))
            if response is None or response[1] != 24:
                return None
            sak = response[0]
            if crc_a(sak[:1]) != sak[1:]:
                return None
            if sak[0] & 4:
                if block[0] != 0x88 or level == 0x97:
                    return None
                uid.extend(block[1:4])
            else:
                uid.extend(block[:4])
                halt = b'\x50\x00'
                self.exchange(halt + crc_a(halt))
                return ':'.join('%02X' % value for value in uid)
        return None
