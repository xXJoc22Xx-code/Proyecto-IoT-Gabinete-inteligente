# Proyecto IoT: gabinete inteligente

Sistema de control de acceso con dos ESP32, teclado, RFID, servo y tres sensores de presion Keyes FSR402. El servidor utiliza Node.js, Node-RED, Mosquitto con TLS y SQLite.

## Contenido

- `ESP32_1/`: acceso mediante teclado y RFID, autenticacion HTTPS y comunicacion MQTTS.
- `ESP32_2/`: control del servo, lecturas ADC y calibracion de presencia.
- `server/`: servidor, dashboard y configuracion inicial.
- `Iniciar-servidor.cmd`: inicio del servidor en Windows.

Se incluyen unicamente fuentes. No se distribuyen pruebas, simuladores, dependencias, binarios, certificados, credenciales, datos de usuarios ni registros de la instalacion.

## Instalacion nueva del servidor

Requisitos: Windows, Node.js 24 o posterior, npm, OpenSSL y Mosquitto (incluido mosquitto_passwd.exe).

Desde CMD, en la carpeta del proyecto:

```cmd
npm install
set "MOSQUITTO_PATH=C:\Program Files\mosquitto\mosquitto.exe"
set "OPENSSL_PATH=C:\Program Files\OpenSSL-Win64\bin\openssl.exe"
npm run setup
npm start
```

Ajustar las rutas a las instalaciones reales. OPENSSL_PATH puede omitirse si openssl esta en PATH. GABINETE_IP permite seleccionar la IP LAN del servidor cuando hay varias interfaces.

`npm run setup` es solo para una instalacion nueva: genera certificados y credenciales aleatorias en `runtime/`. No sustituir la configuracion de una instalacion existente. El script se niega a sobrescribir `runtime/local.json`.

Dashboard local: https://localhost:1881. Editor Node-RED: https://localhost:1881/editor. Las credenciales iniciales se guardan en `runtime/ACCESO-LOCAL.txt`; deben mantenerse privadas. La CA local debe configurarse como confiable en el equipo que abre el panel.

MQTTS usa el puerto 8883 y la autenticacion de la placa HTTPS usa 8443. El equipo servidor debe permitir esas conexiones desde las placas. Mantener la IP utilizada por la configuracion y los certificados.

## Carga de las placas

1. Instalar MicroPython compatible con el ESP32 utilizado.
2. Copiar a cada placa todos los archivos `.py` de su carpeta correspondiente, incluido `main.py`.
3. En `runtime/provision/esp32_1/config.json` y `runtime/provision/esp32_2/config.json`, completar localmente `ssid` y `wifi_password`. Conservar las credenciales MQTT propias de cada placa.
4. Copiar a la raiz de cada placa su `config.json` y su `ca.der` desde la carpeta de provision correspondiente. No publicar estos archivos.
5. Reiniciar las placas. Se requiere conectividad Wi-Fi y sincronizacion horaria para TLS.

En placas sin PSRAM, ejecutar los fuentes puede dejar memoria insuficiente para TLS. Puede ser necesario compilar los modulos con mpy-cross compatible con el firmware; esta publicacion no incluye paquetes precompilados. No mezclar modulos compilados de versiones distintas. El arranque de ESP32_2 reconoce `/app_mpy`; el arranque fuente de ESP32_1 requiere que sus modulos sean importables desde la raiz o `/lib`.

## Cableado principal

ESP32_1: filas del teclado GPIO12, GPIO13, GPIO14, GPIO27; columnas GPIO26, GPIO32, GPIO33, GPIO25. Consultar `hardware.py` y `rc522.py` para los demas perifericos.

ESP32_2:

- Servo: GPIO4.
- Sensor 1: salida analogica a GPIO34 (ADC1).
- Sensor 2: salida analogica a GPIO35 (ADC1).
- Sensor 3: salida analogica a GPIO32 (ADC1).
- Modulos analogicos a 3.3 V y GND comun. Alimentar el servo con una fuente adecuada y compartir GND.

## Calibracion y funcionamiento

Con el programa detenido en Thonny, ejecutar en ESP32_2:

```python
import calibrar
calibrar.run()
```

Seguir las indicaciones sin carga y con carga para los tres sensores. Reiniciar despues de guardar. Se publican lecturas ADC de 0 a 4095 y presencia calibrada, no peso en gramos. La falta de calibracion o estabilidad puede producir inventario indeterminado.

El acceso por teclado utiliza `ID#contrasena#`. Una sesion abierta se cierra pulsando nuevamente `#`. Los permisos deben estar sincronizados. La confirmacion del servo informa una orden de movimiento; no hay sensor de cierre fisico. Si se pierde la red con la sesion abierta, el cierre remoto depende de recuperar la conexion.

## Datos locales

Los archivos privados y datos de ejecucion estan excluidos mediante `.gitignore`. Cada instalacion genera sus propios certificados y credenciales. No subir `runtime/`, copias de bases de datos, configuraciones de las placas ni capturas con contrasenas.
