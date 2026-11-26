"""Servo GPIO4; tres Keyes FSR402 analogicos en ADC1 del ESP32 clasico."""
from machine import Pin, PWM, ADC
from pressure import SENSOR_PINS

class Servo:
    def __init__(self):
        self.pwm = PWM(Pin(4), freq=50, duty_u16=0)
    def angle(self, degrees):
        if not 0 <= degrees <= 180:
            raise ValueError('Angulo fuera de rango')
        # Pulsos configurables en codigo: 500..2500 us, periodo de 20 ms.
        pulse_us = 500 + int(degrees * 2000 / 180)
        self.pwm.duty_u16(pulse_us * 65535 // 20000)
    def stop(self):
        self.pwm.deinit()

class PressureSensors:
    def __init__(self):
        self.adcs = []
        for pin in SENSOR_PINS:
            adc = ADC(Pin(pin))
            adc.atten(ADC.ATTN_11DB)
            adc.width(ADC.WIDTH_12BIT)
            self.adcs.append(adc)

    def read(self):
        # Orden fijo: sensor 1 GPIO34, sensor 2 GPIO35, sensor 3 GPIO32.
        return [adc.read() for adc in self.adcs]
