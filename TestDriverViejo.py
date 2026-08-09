import hid
import keyboard
import time
import threading

### IMPORTANTE: Implementacion realizada con la libreria keyboard, puede generar conflictos con Anticheats a nivel de kernel como Battleye, EAC, Vanguard, etc. Se recomienda usar con precaucion y solo para fines educativos.

# 1. El mapa extraído de la ingeniería inversa (Hardware IDs)
ASUS_VLEDS = [
    0, 16, 24, 32, 40, 48, 56, 64, 72, 88, 96, 104, 112, 128, 120, 136, 144,
    1, 9, 17, 25, 33, 41, 49, 57, 65, 73, 81, 89, 97, 113, 121, 129, 137, 145,
    2, 10, 18, 26, 34, 42, 50, 58, 66, 74, 82, 90, 98, 114, 122, 130, 138, 146,
    3, 11, 19, 27, 35, 43, 51, 59, 67, 75, 83, 91, 99, 115, 123, 131, 139,
    4, 12, 20, 28, 36, 44, 52, 60, 68, 76, 84, 92, 108, 116, 124, 132, 140, 148,
    5, 13, 21, 53, 85, 93, 109, 117, 125, 133, 141
]

# Nombres mapeados y normalizados para coincidir con los eventos del OS
ASUS_VNAMES = [
    "esc", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12", "delete", "insert", "page up", "page down",
    "`", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "=", "backspace", "num lock", "/", "*", "num -",
    "tab", "q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "[", "]", "\\", "num 7", "num 8", "num 9", "+",
    "caps lock", "a", "s", "d", "f", "g", "h", "j", "k", "l", "ñ", "'", "iso_#", "enter", "num 4", "num 5", "num 6",
    "shift", "<", "z", "x", "c", "v", "b", "n", "m", ",", ".", "-", "right shift", "up", "num 1", "num 2", "num 3", "num enter",
    "ctrl", "windows", "alt", "space", "fn", "right ctrl", "left", "down", "right", "num 0", "num ."
]

# Diccionario de acceso O(1) para el evento de tipeo
KEY_MAP = dict(zip(ASUS_VNAMES, ASUS_VLEDS))

# Mapeo de Hardware por Scan Code para el Numpad (Inmune al estado de NumLock)
# --- FIX (Bug 2) ---
# Num Lock, "/", "*" y "-" apuntaban al LED de la tecla física ANTERIOR en la
# fila superior del numérico (ej: Num Lock apagaba Backspace). Se corrigieron
# los 4 valores contra el mapa maestro ASUS_VLEDS/ASUS_VNAMES. El resto de la
# tabla (7,8,9,4,5,6,1,2,3,0,.,+,Enter) ya coincidía y no se tocó.
NUMPAD_SCANCODES = {
    69:  121, # Num Lock
    309: 129, # Numpad /
    55:  137, # Numpad *
    74:  145, # Numpad -

    # Fila superior del Numpad (7, 8, 9)
    71:  122, # Numpad 7
    72:  130, # Numpad 8
    73:  138, # Numpad 9

    # Fila del medio del Numpad (4, 5, 6)
    75:  123, # Numpad 4
    76:  131, # Numpad 5
    77:  139, # Numpad 6

    # Fila inferior del Numpad (1, 2, 3)
    79:  124, # Numpad 1
    80:  132, # Numpad 2
    81:  140, # Numpad 3

    # Teclas de la base y Enter del Numpad
    82:  133, # Numpad 0
    83:  141, # Numpad .
    78:  146, # Numpad +
    # Enter numérico: comparte scan_code (28) con el Enter normal — se
    # confirmó con captura real. La diferencia está en is_keypad (True acá,
    # False para el Enter normal), por eso esta entrada solo se usa en la
    # rama que exige is_keypad=True.
    28:  148, # Numpad Enter
}

# Scan codes EXCLUSIVOS del numérico: ninguna otra tecla del teclado los
# genera, así que no hace falta comprobar is_keypad para confiar en ellos.
NUMPAD_SCANCODES_UNAMBIGUOUS = {69, 309, 55, 74, 78}

# Teclas especiales FUERA del numérico, ubicadas por Scan Code en vez de por
# nombre. event.name depende del idioma de Windows (ej: en español devuelve
# "bloq mayus" en vez de "caps lock"), así que cualquier tecla especial
# mapeada por nombre en KEY_MAP es frágil si el sistema no está en inglés.
# Acá vamos sumando, con captura real, las que confirmamos rotas por este motivo.
EXTRA_SCANCODES = {
    58: 3,    # Caps Lock / "Bloq Mayús" — confirmado: scan_code=58, is_keypad=False
    91: 13,   # Windows / "windows izquierda" — confirmado: scan_code=91, is_keypad=False
    42: 4,    # Shift izq. / "mayusculas" — confirmado: scan_code=42, is_keypad=False

    # Teclas de símbolo: el layout en español les cambia el carácter que
    # producen, pero el scan code identifica la posición física sin
    # depender del idioma. Cada una ya tenía un LED asignado bajo su
    # nombre "US" en ASUS_VNAMES; acá solo la enganchamos por posición.
    41: 1,    # "`" física → aparece como "|" en este layout
    40: 91,   # "'" física → aparece como "{"
    43: 114,  # "\" física → aparece como "}"
    26: 90,   # "[" física → aparece como "´"
    27: 98,   # "]" física → aparece como "+"
    12: 89,   # "-" física → aparece como "'"
    13: 97,   # "=" física → aparece como "¿"
}

# Scan codes que SÍ colisionan con el numérico (comparten número con
# Numpad 7/8/9/4/6/1/3/0/. — ver comentario de is_keypad más arriba), pero
# corresponden a teclas de navegación normales. Solo se usan cuando
# is_keypad=False, así nunca pisan al numérico real.
NAV_SCANCODES = {
    # Flechas (confirmado por captura: is_keypad=False)
    72: 116,  # Flecha Arriba   (LED de "up")
    80: 117,  # Flecha Abajo    (LED de "down")
    75: 109,  # Flecha Izquierda (LED de "left")
    77: 125,  # Flecha Derecha  (LED de "right")

    # Insertar / Suprimir: teclas dedicadas, separadas del numérico
    82: 120,  # Insertar (LED de "insert")
    83: 128,  # Suprimir (LED de "delete")

    # Re Pág / Av Pág: TAMBIÉN son teclas dedicadas (confirmado), no combos
    # Fn+numérico como se había asumido antes. Colisionan en scan code con
    # Numpad 9 y Numpad 3 por la misma razón de siempre (par extendido/no
    # extendido), pero tienen su LED propio — ya estaba en el mapa original
    # ("page up"/"page down" de ASUS_VNAMES) y no se estaba usando.
    73: 136,  # Re Pág (LED de "page up")
    81: 144,  # Av Pág (LED de "page down")
}

# LED de la tecla Fn, ya presente en el mapa original (ASUS_VNAMES/ASUS_VLEDS)
# pero nunca usado porque Fn no genera evento de teclado estándar — se
# detecta por una interfaz HID propietaria aparte (ver _fn_watcher_loop).
FN_LED_ID = KEY_MAP["fn"]

class TUFK3Driver:
    def __init__(self):
        self.vendor_id = 0x0B05  # ASUS VID
        self.fps = 30
        self.fade_duration = 1.0 # Segundos que tarda en volver a blanco
        
        # Estado en memoria de la matriz (Base: Blanco 255, 255, 255)
        self.colors = {led_id: [255, 255, 255] for led_id in ASUS_VLEDS}
        self.active_fades = {} # Diccionario para rastrear animaciones {led_id: start_timestamp}
        self.fn_held = False # Estado actual de Fn, actualizado por _fn_watcher_loop
        
        self.device, self.fn_device = self._connect_device()
        self.running = True

        # Fn no genera un evento de teclado estándar (ningún hook de OS la
        # ve — se resuelve enteramente dentro del firmware del teclado).
        # Se lee por una interfaz HID propietaria aparte (usage_page=0xFFC0),
        # detectada por prueba y error con hidapi, en su propio hilo.
        self.fn_thread = threading.Thread(target=self._fn_watcher_loop, daemon=True)
        self.fn_thread.start()

    def _connect_device(self):
        print("Buscando teclado TUF K3 Gen II...")
        rgb_dev = None
        fn_dev = None
        for d in hid.enumerate(self.vendor_id):
            # Interfaz 1: la del control de RGB, igual que el Endpoint
            # reportado en el JSON.
            if d['interface_number'] == 1:
                dev = hid.device()
                dev.open_path(d['path'])
                dev.set_nonblocking(1)
                print(f"Hardware conectado exitosamente: {d['product_string']}")
                rgb_dev = dev
            # Interfaz propietaria de ASUS (usage_page 0xFFC0) que reporta
            # el estado de Fn — confirmado por captura real con hidapi.
            elif d.get('usage_page') == 0xFFC0 and d.get('usage') == 0x1:
                fdev = hid.device()
                fdev.open_path(d['path'])
                fdev.set_nonblocking(1)
                fn_dev = fdev

        if rgb_dev is None:
            raise Exception("No se encontró el teclado. Asegúrate de cerrar SignalRGB/Armoury Crate.")
        if fn_dev is None:
            print("Aviso: no se encontró la interfaz de Fn (usage_page 0xFFC0). "
                  "Esa tecla no se va a detectar, pero el resto del driver funciona igual.")
        return rgb_dev, fn_dev

    def _light_led(self, led_id):
        """Apaga un LED y arranca su fundido a blanco. Centralizado acá para
        no repetir las mismas dos líneas en hook_keypress y _fn_watcher_loop."""
        self.colors[led_id] = [0, 0, 0]
        self.active_fades[led_id] = time.time()

    def _fn_watcher_loop(self):
        """Hilo aparte: lee la interfaz propietaria de Fn en paralelo al hook
        de teclado normal. Mantiene self.fn_held actualizado en todo momento
        (no solo en el flanco) para que hook_keypress pueda consultarlo, y
        dispara el apagado+fundido propio de Fn en el flanco de subida (0→1)."""
        if self.fn_device is None:
            return

        while self.running:
            try:
                data = self.fn_device.read(64)
            except OSError:
                # La interfaz dejó de responder (desconexión, etc). Cortamos
                # el hilo en vez de spamear errores en loop.
                break

            if data and len(data) >= 4:
                state = data[3]
                if state == 1 and not self.fn_held:
                    self._light_led(FN_LED_ID)
                self.fn_held = (state == 1)

            time.sleep(0.005)

    def hook_keypress(self, event):
        led_id = None

        # --- FIX (Bug 1) ---
        # event.scan_code existe en TODOS los eventos, no solo en el numérico.
        # Home/End/Insert/Supr/Flechas comparten el mismo scan_code base que
        # Numpad 7/1/0/./9/3/8/2/4/6 (la única diferencia es el prefijo E0
        # "extendido", que scan_code no refleja). is_keypad es lo que permite
        # separar ambos casos de forma confiable (ver NAV_SCANCODES abajo).
        is_keypad = getattr(event, 'is_keypad', False)
        scan_code = getattr(event, 'scan_code', None)

        # 1. Prioridad absoluta: Scan Code.
        #    - Los scan codes "exclusivos" (Num Lock, /, *, -, +) no los
        #      comparte ninguna otra tecla: se usan directo.
        #    - EXTRA_SCANCODES: teclas especiales fuera del numérico que ya
        #      confirmamos rotas por nombres localizados (Bloq Mayús, Windows).
        #    - Los que colisionan con el numérico (7,8,9,4,5,6,1,2,3,0,.,Enter)
        #      solo se aceptan si is_keypad=True (vienen del bloque numérico).
        #    - NAV_SCANCODES: los mismos códigos colisionados, pero para
        #      cuando is_keypad=False (flechas, insertar, suprimir, o Re Pág/
        #      Av Pág dedicados). Si en ese momento Fn está sostenida
        #      (self.fn_held, vía _fn_watcher_loop), el evento en realidad
        #      viene de un combo Fn+numérico, no de la tecla dedicada — ahí
        #      iluminamos Fn + la tecla física real del numérico en vez de
        #      la función que el combo simula.
        if scan_code in NUMPAD_SCANCODES_UNAMBIGUOUS:
            led_id = NUMPAD_SCANCODES[scan_code]
        elif scan_code in EXTRA_SCANCODES:
            led_id = EXTRA_SCANCODES[scan_code]
        elif is_keypad and scan_code in NUMPAD_SCANCODES:
            led_id = NUMPAD_SCANCODES[scan_code]
        elif (not is_keypad) and scan_code in NAV_SCANCODES:
            if self.fn_held and scan_code in NUMPAD_SCANCODES:
                self._light_led(FN_LED_ID)
                led_id = NUMPAD_SCANCODES[scan_code]
            else:
                led_id = NAV_SCANCODES[scan_code]
        else:
            # 2. Búsqueda secundaria por nombre (Lógica del Sistema Operativo)
            key_name = (event.name or "").lower()
            if key_name in KEY_MAP:
                led_id = KEY_MAP[key_name]
                
        # Si identificamos correctamente la tecla, disparamos el evento inverso
        if led_id is not None:
            self._light_led(led_id)

    def _send_frames(self):
        led_items = list(self.colors.items())
        
        # Trocear la matriz completa en bloques de 15 LEDs para respetar el límite USB
        for i in range(0, len(led_items), 15):
            chunk = led_items[i:i+15]
            
            # La cabecera exacta de escritura que capturaste en Wireshark
            packet = [0xC0, 0x81, 0x36, 0x00] 
            
            for led_id, rgb in chunk:
                packet.extend([led_id, int(rgb[0]), int(rgb[1]), int(rgb[2])])

            # Rellenar con un ID de LED falso (0xFF) y colores en cero 
            # para evitar sobreescribir la tecla ESC (ID 0x00)
            while len(packet) < 64:
                packet.extend([0xFF, 0x00, 0x00, 0x00])

            # Truncar por seguridad para asegurar exactamente los 64 bytes
            packet = packet[:64]

            # Inyección en Windows mediante hidapi
            self.device.write([0x00] + packet)

    def render_loop(self):
        print("Driver iniciado. Matriz en ejecución (Presiona ESC para salir).")
        while self.running:
            current_time = time.time()
            to_remove = []

            # Calcular la interpolación solo para las teclas que están animándose
            for led_id, start_time in self.active_fades.items():
                elapsed = current_time - start_time
                
                if elapsed >= self.fade_duration:
                    self.colors[led_id] = [255, 255, 255] # Volver a Blanco absoluto
                    to_remove.append(led_id)
                else:
                    # Progreso base de 0.0 a 1.0
                    progress = elapsed / self.fade_duration
                    
                    # Aplicamos una curva exponencial (cuadrática o cúbica)
                    # Al elevar progress al cubo, el valor sube muy lento al principio y rápido al final.
                    ease_in_progress = progress ** 3 
                    
                    val = int(255 * ease_in_progress)
                    self.colors[led_id] = [val, val, val]

            # Limpiar memoria de los hilos terminados
            for led_id in to_remove:
                del self.active_fades[led_id]

            # Enviar la matriz actual al hardware
            self._send_frames()
            
            # Controlar el framerate para no saturar el bus USB
            time.sleep(1.0 / self.fps)

    def stop(self):
        self.running = False
        self.device.close()
        if self.fn_device is not None:
            self.fn_device.close()

if __name__ == '__main__':
    driver = TUFK3Driver()
    
    # Enganchar el listener del teclado a nivel de sistema operativo
    keyboard.on_press(driver.hook_keypress)
    
    # Ejecutar el bucle de renderizado en el hilo principal
    try:
        driver.render_loop()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nDesconectando driver...")
        driver.stop()