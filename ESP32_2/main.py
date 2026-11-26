"""Arranque ESP32 2. Prioriza los modulos compilados cuando estan instalados."""
import gc
gc.threshold(4096)
gc.collect()
import sys
import os

def start():
    try:
        os.stat('/app_mpy/cabinet_app.mpy')
    except OSError:
        print('Arranque fuente ESP32 2; usar paquete MPY si falta memoria TLS.')
    else:
        if '/app_mpy' in sys.path:
            sys.path.remove('/app_mpy')
        sys.path.insert(0,'/app_mpy')
        print('Arranque precompilado ESP32 2 - TLS v2')
    # Reservar buffers Wi-Fi antes de que crezca el heap de la aplicacion.
    import network
    network.WLAN(network.STA_IF).active(True)
    from tls_context import memory_report
    memory_report('Wi-Fi iniciado, antes de la aplicacion')
    import cabinet_app
    memory_report('Modulos cargados')
    cabinet_app.start()

if __name__=='__main__':
    start()
