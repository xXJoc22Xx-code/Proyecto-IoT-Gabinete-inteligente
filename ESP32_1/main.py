"""Arranque pequeno. Guardar todos los modulos en la ESP32 y reiniciar."""
import gc
gc.collect()
import access_app
gc.collect()
access_app.start()
