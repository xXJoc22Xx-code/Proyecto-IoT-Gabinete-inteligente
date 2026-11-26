"""Un solo contexto TLS verificado; diagnostico sin revelar credenciales."""
import gc
import ssl

_context=None

def get_context():
    global _context
    if _context is None:
        gc.collect()
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.verify_mode=ssl.CERT_REQUIRED
        with open('ca.der','rb') as f:
            certificate=f.read()
        context.load_verify_locations(cadata=certificate)
        certificate=None
        _context=context
    gc.collect()
    return _context

def memory_report(label):
    gc.collect()
    allocated=gc.mem_alloc()
    free=gc.mem_free()
    print(label,'- Python usado:',allocated,'libre:',free,'total:',allocated+free)
    try:
        import esp32
        regions=esp32.idf_heap_info(esp32.HEAP_DATA)
        print('IDF libre:',sum(r[1] for r in regions),'mayor bloque:',max(r[2] for r in regions))
    except (ImportError,AttributeError,ValueError):
        pass

def sync_clock(config):
    import ntptime
    ntptime.host=config.get('ntp_host','pool.ntp.org')
    ntptime.timeout=3
    # Una fecha posterior a 2023 puede seguir estando atrasada para el certificado.
    # Se sincroniza una vez por arranque, aun cuando el RTC parezca razonable.
    ntptime.settime()
