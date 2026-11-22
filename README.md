# Proyecto IoT Gabinete inteligente

## Pruebas de componentes de la ESP32 1

Esta rama conserva la primera prueba local en MicroPython: teclado matricial 4x4, lector RC522, dos LEDs y buzzer activo en nivel bajo. No es el firmware final de seguridad y no controla una puerta.

## Archivos

- `main.py`: prueba integrada con PIN de demostración `1234`.
- `rc522.py`: lectura del UID de una tarjeta ISO14443A a la vez.
- `registrar_tarjeta.py`: registro manual de una tarjeta en la memoria de la placa.

## Conexiones para ESP32 WROOM 32

| Componente | Pines GPIO |
|---|---|
| Teclado R1, R2, R3, R4 | 13, 12, 14, 27 |
| Teclado C1, C2, C3, C4 | 26, 25, 33, 32 |
| RC522 SS, SCK, MOSI, MISO, RST | 21, 18, 23, 19, 22 |
| LED verde | 16 |
| LED rojo | 17 |
| Señal del buzzer | 4 |

RC522: alimentación de 3.3 V, tierra común e IRQ sin conexión. Cada LED lleva una resistencia de 330 ohmios en serie hacia GND. El módulo de buzzer comprobado se activa en LOW y se apaga en HIGH. Verificar alimentación y etiquetas del módulo antes de conectar. GPIO 12 es un pin de arranque: evitar mantener teclas presionadas al encender.

## Uso con Thonny

1. Instalar MicroPython para la placa y seleccionar el intérprete MicroPython ESP32 y el puerto correcto en Thonny.
2. Guardar los tres archivos Python en la raíz de la ESP32, primero `rc522.py` y al final `main.py`.
3. Detener el programa con Ctrl+C antes de ejecutar otra prueba.
4. Ejecutar `registrar_tarjeta.py` y acercar una sola tarjeta durante los siguientes 30 segundos. El UID se guarda en `tarjeta.json`, no se escribe una contraseña en la tarjeta. Registrar otra tarjeta reemplaza la anterior.
5. Retirar la tarjeta y ejecutar `main.py`.

| Acción | Resultado esperado |
|---|---|
| A | Prueba LED verde |
| B | Prueba LED rojo |
| C | Pitido corto |
| D | Prueba secuencial de LEDs y buzzer |
| 1234# | Autorización de prueba |
| Otro código seguido de # | Denegación |
| * | Borrar entrada |
| Tarjeta registrada | Autorización de prueba |

Retirar la tarjeta al menos un segundo antes de repetir. La consola muestra las teclas para diagnosticar el cableado; este comportamiento debe retirarse en la versión final.

## Estado y límites

Teclado, LEDs y buzzer verificados por el equipo en la placa. Se incluye el lector y el registro de tarjeta para pruebas. Se revisó la sintaxis y se verificó por simulación el CRC y la selección de UID de 4 y 7 bytes; esto no sustituye la validación física del lector.

Esta versión no incluye MQTT/TLS, Node-RED, SQLite, usuarios individuales, buffering offline, sensor de peso ni servo. El tercer LED del GPIO 5 y el flujo ID/contraseña pertenecen a la siguiente etapa y todavía no están implementados.

El PIN `1234` es únicamente un dato público de demostración. La validación por UID no protege contra clonación. No usar este firmware para proteger bienes reales. La versión final deberá aprovisionar credenciales fuera del código e implementar los controles de seguridad del proyecto.

Los UID registrados, claves privadas, credenciales e historiales locales no deben subirse al repositorio.
