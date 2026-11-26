"""Un contexto verificado compartido por MQTT y HTTPS; sockets independientes."""
import gc
import ssl

_context = None

def get_context():
    global _context
    if _context is None:
        gc.collect()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.verify_mode = ssl.CERT_REQUIRED
        with open('ca.der', 'rb') as f:
            certificate = f.read()
        context.load_verify_locations(cadata=certificate)
        certificate = None
        _context = context
    gc.collect()
    return _context

def memory_report():
    gc.collect()
    print('Python libre:', gc.mem_free())
    try:
        import esp32
        regions = esp32.idf_heap_info(esp32.HEAP_DATA)
        print('IDF libre:', sum(r[1] for r in regions),
              'mayor bloque:', max(r[2] for r in regions))
    except (ImportError, AttributeError):
        pass
