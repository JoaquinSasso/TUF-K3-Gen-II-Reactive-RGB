"""
Herramienta de mapeo completo: escucha la interfaz propietaria de ASUS y
muestra SOLO lo que cambió respecto a la lectura anterior (no el array
completo), para poder ir tecla por tecla sin ruido.

Importante: cerrá el driver principal antes de correr esto.
"""
import hid
import time

VENDOR_ID = 0x0B05
TARGET_USAGE_PAGE = 0xFFC0
TARGET_USAGE = 0x1

devices_info = hid.enumerate(VENDOR_ID)
target = None
for d in devices_info:
    if d.get('usage_page') == TARGET_USAGE_PAGE and d.get('usage') == TARGET_USAGE:
        target = d
        break

if target is None:
    print("No se encontró la interfaz 0xFFC0.")
else:
    dev = hid.device()
    dev.open_path(target['path'])
    dev.set_nonblocking(1)
    print("Listo. Presioná UNA tecla a la vez, esperá a ver la línea "
          "'ACTIVADA', soltá, y pasá a la siguiente. Ctrl+C al final para "
          "cortar (esa pulsación también va a aparecer, ignorala al copiar "
          "el resultado).\n")

    prev = [0] * 21
    try:
        while True:
            data = dev.read(64)
            if data:
                data = list(data)
                for i in range(2, min(len(data), len(prev))):
                    if data[i] != prev[i]:
                        if data[i] == 0:
                            print(f"  liberada -> byte={i}")
                        elif data[i] & (data[i] - 1) == 0:
                            # Es una potencia de 2: un solo bit prendido.
                            bit = data[i].bit_length() - 1
                            print(f"ACTIVADA -> byte={i} valor={data[i]} (bit {bit})")
                        else:
                            print(f"  byte={i} valor={data[i]} "
                                  f"(varios bits juntos, ¿dos teclas a la vez?)")
                prev = data
            time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        dev.close()
        print("\nListo, cerrado.")