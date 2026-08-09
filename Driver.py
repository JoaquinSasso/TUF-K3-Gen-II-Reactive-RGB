"""
Driver TUF K3 Gen II — v2, sin hook de OS.

Cambio de arquitectura respecto a la versión anterior: ya NO se usa la
librería `keyboard` (SetWindowsHookEx a nivel de sistema, la misma técnica
que usan los keyloggers, y por eso señalada por anti-cheats de kernel como
Vanguard/EAC). En su lugar, se lee directamente y en exclusiva la interfaz
HID propietaria de ASUS (usage_page=0xFFC0) que ya usamos para detectar Fn
— resultó que esa misma interfaz reporta TODO el teclado como un bitmap
(cada tecla física es un bit único dentro de un byte de un reporte con
Report ID 3), no solo Fn.

Esto es lectura pasiva pura por HID: sin hooks, sin RawInput, sin ninguna
API de Windows relacionada a captura de input. Solo hidapi hablando
directo con el dispositivo, igual que ya hacíamos para mandar los colores.

El mapa KEY_MATRIX de abajo se construyó a mano, tecla por tecla, con
capturas reales (ver conversación de desarrollo) — no es una tabla de
scan codes estándar, es específica de este teclado y este firmware.
"""
import hid
import time
import threading

# 1. El mapa de hardware original (LEDs), reverse-engineered por Wireshark.
#    Sigue haciendo falta para inicializar la matriz de colores y para
#    _send_frames, que recorre TODOS los LEDs sin importar cómo se detectó
#    la tecla.
ASUS_VLEDS = [
    0, 16, 24, 32, 40, 48, 56, 64, 72, 88, 96, 104, 112, 128, 120, 136, 144,
    1, 9, 17, 25, 33, 41, 49, 57, 65, 73, 81, 89, 97, 113, 121, 129, 137, 145,
    2, 10, 18, 26, 34, 42, 50, 58, 66, 74, 82, 90, 98, 114, 122, 130, 138, 146,
    3, 11, 19, 27, 35, 43, 51, 59, 67, 75, 83, 91, 99, 115, 123, 131, 139,
    4, 12, 20, 28, 36, 44, 52, 60, 68, 76, 84, 92, 108, 116, 124, 132, 140, 148,
    5, 13, 21, 53, 85, 93, 109, 117, 125, 133, 141
]

# 2. Mapa de teclas: (byte, bit) del reporte HID propietario -> LED ID.
#    Reemplaza por completo a KEY_MAP, NUMPAD_SCANCODES, NAV_SCANCODES,
#    EXTRA_SCANCODES y toda la lógica de is_keypad de la versión anterior.
#    Cada tecla física tiene una coordenada propia y única: no hay
#    colisiones que resolver ni nombres localizados que matchear.
KEY_MATRIX = {
    # --- fila Esc / F1-F12 ---
    (2, 0): 0,     # esc
    (3, 1): 16,    # f1
    (4, 2): 24,    # f2
    (5, 3): 32,    # f3
    (6, 4): 40,    # f4
    (7, 5): 48,    # f5
    (8, 6): 56,    # f6
    (9, 7): 64,    # f7
    (11, 0): 72,   # f8
    (12, 1): 88,   # f9
    (13, 2): 96,   # f10
    (14, 3): 104,  # f11
    (15, 4): 112,  # f12
    (18, 0): 120,  # insertar
    (18, 1): 128,  # suprimir
    (6, 1): 136,   # re pág
    (12, 7): 144,  # av pág

    # --- fila numérica ---
    (2, 1): 1,     # `
    (3, 2): 9,     # 1
    (4, 3): 17,    # 2
    (5, 4): 25,    # 3
    (6, 5): 33,    # 4
    (7, 6): 41,    # 5
    (8, 7): 49,    # 6
    (10, 0): 57,   # 7
    (11, 1): 65,   # 8
    (12, 2): 73,   # 9
    (13, 3): 81,   # 0
    (14, 4): 89,   # ' (aparece como "-" en layout US)
    (15, 5): 97,   # ¿ (aparece como "=" en layout US)
    (17, 7): 113,  # retroceso

    # --- fila QWERTY ---
    (2, 2): 2,     # tab
    (3, 3): 10,    # q
    (4, 4): 18,    # w
    (5, 5): 26,    # e
    (6, 6): 34,    # r
    (7, 7): 42,    # t
    (9, 0): 50,    # y
    (10, 1): 58,   # u
    (11, 2): 66,   # i
    (12, 3): 74,   # o
    (13, 4): 82,   # p
    (14, 5): 90,   # ´ (aparece como "[" en layout US)
    (15, 6): 98,   # + (aparece como "]" en layout US)
    (15, 7): 114,  # } (aparece como "\" en layout US)
    (17, 0): 115,  # enter

    # --- fila ASDF ---
    (2, 3): 3,     # bloq mayús / caps lock
    (3, 4): 11,    # a
    (4, 5): 19,    # s
    (5, 6): 27,    # d
    (6, 7): 35,    # f
    (8, 0): 43,    # g
    (9, 1): 51,    # h
    (10, 2): 59,   # j
    (11, 3): 67,   # k
    (12, 4): 75,   # l
    (13, 5): 83,   # ñ
    (14, 6): 91,   # { (aparece como "'" en layout US)

    # --- fila ZXCV ---
    (2, 4): 4,     # shift izq
    (3, 5): 12,    # <
    (4, 6): 20,    # z
    (5, 7): 28,    # x
    (7, 0): 36,    # c
    (8, 1): 44,    # v
    (9, 2): 52,    # b
    (10, 3): 60,   # n
    (11, 4): 68,   # m
    (12, 5): 76,   # ,
    (13, 6): 84,   # .
    (14, 7): 92,   # - (segunda, aparece como "'" en layout US)
    (17, 1): 108,  # shift derecho
    (18, 2): 116,  # flecha arriba

    # --- fila inferior ---
    (2, 5): 5,     # ctrl
    (3, 6): 13,    # windows
    (4, 7): 21,    # alt
    (8, 2): 53,    # espacio
    (3, 0): 85,    # fn
    (16, 1): 93,   # ctrl derecho
    (17, 2): 109,  # flecha izquierda
    (18, 3): 117,  # flecha abajo
    (18, 4): 125,  # flecha derecha

    # --- numérico ---
    (7, 2): 121,   # num lock
    (8, 3): 129,   # numpad /
    (9, 4): 137,   # numpad *
    (10, 5): 145,  # numpad -
    (14, 0): 122,  # numpad 7
    (15, 1): 130,  # numpad 8
    (4, 0): 138,   # numpad 9
    (5, 1): 146,   # numpad +
    (6, 2): 123,   # numpad 4
    (7, 3): 131,   # numpad 5
    (8, 4): 139,   # numpad 6
    (10, 6): 124,  # numpad 1
    (11, 7): 132,  # numpad 2
    (13, 0): 140,  # numpad 3
    (18, 5): 133,  # numpad 0
    (14, 1): 141,  # numpad .
    (15, 2): 148,  # numpad enter
}


class TUFK3Driver:
    def __init__(self):
        self.vendor_id = 0x0B05  # ASUS VID
        self.fps = 30
        self.fade_duration = 1.0  # Segundos que tarda en volver a blanco

        # Estado en memoria de la matriz (Base: Blanco 255, 255, 255)
        self.colors = {led_id: [255, 255, 255] for led_id in ASUS_VLEDS}
        self.active_fades = {}  # {led_id: start_timestamp}

        self.rgb_device, self.key_device = self._connect_device()
        self.running = True

        self.key_thread = threading.Thread(target=self._key_watcher_loop, daemon=True)
        self.key_thread.start()

    def _connect_device(self):
        print("Buscando teclado TUF K3 Gen II...")
        rgb_dev = None
        key_dev = None
        for d in hid.enumerate(self.vendor_id):
            # Interfaz 1: control de RGB (igual que siempre).
            if d['interface_number'] == 1:
                dev = hid.device()
                dev.open_path(d['path'])
                dev.set_nonblocking(1)
                print(f"RGB conectado: {d['product_string']}")
                rgb_dev = dev
            # Interfaz propietaria de ASUS: reporta el estado de TODAS las
            # teclas como bitmap (Report ID 3). Reemplaza por completo al
            # hook de teclado del sistema operativo.
            elif d.get('usage_page') == 0xFFC0 and d.get('usage') == 0x1:
                dev = hid.device()
                dev.open_path(d['path'])
                dev.set_nonblocking(1)
                key_dev = dev

        if rgb_dev is None:
            raise Exception("No se encontró el teclado. Asegúrate de cerrar SignalRGB/Armoury Crate.")
        if key_dev is None:
            print("AVISO: no se encontró la interfaz de teclas (0xFFC0). "
                  "La matriz va a quedar en blanco fijo, sin reaccionar a "
                  "ninguna tecla, pero el driver sigue corriendo.")
        return rgb_dev, key_dev

    def _light_led(self, led_id):
        """Apaga un LED y arranca su fundido a blanco."""
        self.colors[led_id] = [0, 0, 0]
        self.active_fades[led_id] = time.time()

    def _key_watcher_loop(self):
        """Único hilo de detección de teclas: lee el reporte bitmap de la
        interfaz propietaria y dispara _light_led en el flanco de subida
        (0->1) de cada bit. Reemplaza a hook_keypress + keyboard.on_press
        de la versión anterior por completo — no hay hook de OS en ningún
        lado del proceso."""
        if self.key_device is None:
            return

        prev = [0] * 21
        while self.running:
            try:
                data = self.key_device.read(64)
            except OSError:
                print("Se perdió la conexión con la interfaz de teclas.")
                break

            if data:
                data = list(data)
                for i in range(2, min(len(data), len(prev))):
                    if data[i] != prev[i]:
                        for bit in range(8):
                            mask = 1 << bit
                            if (data[i] & mask) and not (prev[i] & mask):
                                led_id = KEY_MATRIX.get((i, bit))
                                if led_id is not None:
                                    self._light_led(led_id)
                prev = data

            time.sleep(0.005)

    def _send_frames(self):
        led_items = list(self.colors.items())

        # Trocear la matriz completa en bloques de 15 LEDs para respetar el límite USB
        for i in range(0, len(led_items), 15):
            chunk = led_items[i:i + 15]

            # Cabecera: 0xC0, 0x81 fijos + cantidad REAL de LEDs de este
            # paquete puntual (hasta 15) — confirmado contra la implementación
            # real de OpenRGB (AsusAuraTUFKeyboardController.cpp, UpdateLeds).
            # Antes iba un valor fijo (0x36) que no reflejaba la cantidad
            # real por paquete.
            packet = [0xC0, 0x81, len(chunk), 0x00]

            for led_id, rgb in chunk:
                packet.extend([led_id, int(rgb[0]), int(rgb[1]), int(rgb[2])])

            # Rellenar con un ID de LED falso (0xFF) y colores en cero
            # para evitar sobreescribir la tecla ESC (ID 0x00)
            while len(packet) < 64:
                packet.extend([0xFF, 0x00, 0x00, 0x00])

            # Truncar por seguridad para asegurar exactamente los 64 bytes
            packet = packet[:64]

            self.rgb_device.write([0x00] + packet)

    def render_loop(self):
        print("Driver iniciado. Matriz en ejecución (Ctrl+C para salir).")
        while self.running:
            current_time = time.time()
            to_remove = []

            for led_id, start_time in self.active_fades.items():
                elapsed = current_time - start_time

                if elapsed >= self.fade_duration:
                    self.colors[led_id] = [255, 255, 255]
                    to_remove.append(led_id)
                else:
                    progress = elapsed / self.fade_duration
                    ease_in_progress = progress ** 3
                    val = int(255 * ease_in_progress)
                    self.colors[led_id] = [val, val, val]

            for led_id in to_remove:
                del self.active_fades[led_id]

            self._send_frames()
            time.sleep(1.0 / self.fps)

    def stop(self):
        self.running = False
        self.rgb_device.close()
        if self.key_device is not None:
            self.key_device.close()


if __name__ == '__main__':
    driver = TUFK3Driver()
    try:
        driver.render_loop()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nDesconectando driver...")
        driver.stop()