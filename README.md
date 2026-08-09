# TUF K3 Gen II — Driver RGB Custom (Python + HID)

Driver liviano en Python para el teclado ASUS TUF K3 Gen II, construido por ingeniería inversa del protocolo USB propio del hardware. Reemplaza a Armoury Crate / SignalRGB para un único propósito: iluminación reactiva por tecla (fade-to-white), sin instalar software pesado ni depender de librerías con acceso privilegiado al sistema operativo.

## Características

- **Efecto reactivo inverso**: cada tecla se apaga al presionarla y vuelve a blanco con una curva de fundido exponencial (ease-in cúbico), no lineal.
- **Detección de teclas 100% pasiva por HID**: sin hooks de teclado del sistema operativo. Lee directamente una interfaz HID propietaria del teclado (ver *Arquitectura de Datos*).
- **Mapa de teclas inmune al idioma del sistema**: cada tecla física tiene una coordenada de hardware única, no depende de nombres de tecla que Windows traduce según el idioma configurado.
- **Sin colisiones entre numérico y Flechas/Insertar/Suprimir/Re Pág/Av Pág**: pese a que estas teclas comparten *scan code* a nivel de SO, el protocolo propietario del teclado las distingue sin ambigüedad.
- **Detección de combos con Fn**: Fn se lee como una tecla más del mapa, así que un combo físico como Fn + Numpad 9 ilumina ambas teclas reales en simultáneo, no la función que el combo simula.
- **Sin interfaz gráfica**: pensado para correr como proceso de fondo silencioso.

## Instalación

### Requisitos
- Python 3.x
- Windows (el driver usa `hidapi` sobre las interfaces HID de Windows; no probado en Linux/macOS)
- Teclado ASUS TUF K3 Gen II conectado por USB
- **Cerrar Armoury Crate y SignalRGB antes de correr el driver** — ambos reclaman las mismas interfaces HID en exclusiva e impiden la conexión.

### Dependencias

```bash
pip install hidapi
```

### Ejecución

```bash
python tuf_k3_driver.py
```

Para correrlo en segundo plano sin consola visible:

```bash
pythonw.exe tuf_k3_driver.py
```

## Arquitectura de Datos

El teclado expone varias interfaces HID bajo el mismo VID (`0x0B05`, ASUS). Dos son relevantes para este driver:

| Interfaz | usage_page | Propósito |
|---|---|---|
| `interface_number = 1` | `0xFF00` | Escritura de color RGB (streaming de la matriz completa) |
| — | `0xFFC0` | Lectura pasiva del estado de todas las teclas (propietaria de ASUS) |

### Escritura de color

Cada frame se manda como una serie de paquetes de 64 bytes por transferencia de Interrupción, con esta estructura:

```
[0xC0, 0x81, N, 0x00]       <- cabecera: fija + cantidad real de LEDs de este paquete (N, hasta 15)
[ID_LED, R, G, B]           <- por cada LED, repetido hasta 15 veces por paquete
[0xFF, 0x00, 0x00, 0x00]    <- relleno para completar 64 bytes exactos
```

La matriz completa (99 LEDs) se trocea en bloques de 15 porque no entra en un único paquete de 64 bytes. El relleno usa `0xFF` como ID de LED — cualquier otro valor de relleno (incluido `0x00`, que corresponde a la tecla Esc) termina sobreescribiendo un LED real.

### Lectura de teclas

Cada reporte de esta interfaz llega con `Report ID = 3` y una estructura tipo bitmap: a partir del byte de índice 2, cada byte del reporte representa hasta 8 teclas distintas, una por bit. `KEY_MATRIX` es el diccionario `(byte, bit) -> ID_LED`, construido tecla por tecla mediante captura manual (ver *Ingeniería Inversa*), y cubre 98 de las 99 posiciones físicas del teclado — la única sin cubrir corresponde a `iso_#`, una tecla de layouts ISO europeos que esta unidad ANSI/Latinoamericana no tiene físicamente.

## Cómo Funciona

1. **Conexión**: se abren dos handles HID independientes — uno de solo escritura (colores) y uno de solo lectura (teclas) — vía `hidapi`, sin necesidad de ningún driver adicional.
2. **Hilo de lectura de teclas**: en un hilo aparte, se lee continuamente el reporte de la interfaz `0xFFC0`. Por cada bit que pasa de 0 a 1 (flanco de subida), se busca la coordenada en `KEY_MATRIX` y se dispara el apagado del LED correspondiente.
3. **Bucle de renderizado** (30 FPS, hilo principal): para cada LED con un fundido activo, se calcula el brillo con una curva ease-in cúbica (`brillo = 255 · progreso³`) y se reconstruye el paquete completo de la matriz para enviarlo por la interfaz de escritura.
4. **Sin estado persistente entre teclas**: cada apagado reinicia el timer de fundido de ese LED puntual; el resto de la matriz sigue su propio curso de forma independiente.

## Ingeniería Inversa del Protocolo

### Fase 1 — Protocolo de escritura de color

Se interceptó el tráfico USB entre SignalRGB y el teclado con **USBPcap + Wireshark**, filtrando por transferencias de Interrupción (`URB_INTERRUPT`). Ahí se identificó la cabecera `[0xC0, 0x81, N, 0x00]` que precede a cada bloque de color (donde `N` es la cantidad de LEDs de ese paquete puntual — ver Fase 4), y la estructura `[ID_LED, R, G, B]` por cada LED dentro del payload de 64 bytes.

Para resolver a qué posición física correspondía cada `ID_LED` sin ambigüedad, se usó la táctica del "número mágico": asignarle a una tecla puntual un color RGB imposible de confundir con cualquier otro (`17, 34, 51`) y buscar ese patrón en el stream hexadecimal capturado. Así se confirmó, por ejemplo, que la tecla "A" corresponde al ID de hardware `0x0B` (11 en decimal).

El mapa completo de LEDs por posición se terminó de extraer cruzando esos hallazgos contra el archivo de configuración interno de SignalRGB para este modelo (`ASUS_Keyboard.js`), que ya traía el mapeo de fábrica para el hardware `TUF K3 Gen 2`, incluida la especificación del endpoint (`interface: 1`, `usage_page: 0xFF00`).

### Fase 2 — Del hook de teclado al scan code

La primera versión usable del driver detectaba las pulsaciones con la librería `keyboard`, que engancha un hook global de teclado a nivel de Windows por nombre lógico de tecla. Esto trajo dos bugs distintos y consecutivos:

- **Bug del nombre compartido**: el driver original solo consideraba el nombre de la tecla, sin distinguir si pertenecía o no al numérico. Con NumLock activo, `keyboard` reportaba el mismo nombre lógico para una tecla del numérico y su equivalente de la fila superior (por ejemplo, Numpad 1 se identificaba igual que la tecla "1"), así que al tocar un número del numérico se apagaba el LED del mismo número, pero de la fila que no pertenece al numérico. Se resolvió priorizando el `scan_code` físico de bajo nivel sobre el nombre lógico de la tecla.
- **Bug de colisión con teclas de navegación**: al pasar a detectar por `scan_code`, apareció un problema nuevo — varias teclas de navegación (Insertar, Suprimir, Flechas, Re Pág, Av Pág) comparten el mismo scan code que ciertas teclas del numérico por diseño histórico del estándar PC/AT, y el driver no distinguía el origen, así que cualquier coincidencia de scan code se enrutaba como si viniera del numérico. Se resolvió agregando el flag `is_keypad` de la librería, que confirma si el evento vino físicamente del bloque numérico antes de confiar en el scan code compartido.
- **Nombres localizados por idioma**: con Windows en español, muchas teclas especiales devuelven su nombre traducido (`"bloq mayus"` en vez de `"caps lock"`, `"flecha arriba"` en vez de `"up"`), lo que rompía cualquier búsqueda por nombre en inglés. Se resolvió migrando esas teclas también a detección por `scan_code`, inmune al idioma del sistema.

### Fase 3 — Migración completa a lectura pasiva por HID

El uso de un hook global de teclado (`keyboard`, vía `SetWindowsHookEx(WH_KEYBOARD_LL)`) es la misma técnica de bajo nivel que usan keyloggers e inyectores de input, y por eso es una señal que los anti-cheat de nivel kernel (Vanguard, Easy Anti-Cheat) buscan activamente. Para eliminar esa dependencia, se investigaron las demás interfaces HID que expone el teclado bajo el mismo VID, probando lectura directa con `hidapi` en cada una.

La interfaz con `usage_page = 0xFFC0` (propietaria de ASUS) resultó reportar el estado de **todas** las teclas del teclado como un bitmap bajo un único Report ID — no solo las teclas especiales, como se esperaba en un primer momento. A partir de ahí se construyó `KEY_MATRIX` capturando manualmente, tecla por tecla, la coordenada `(byte, bit)` de cada una de las 98 posiciones físicas del teclado, cruzando cada captura contra el mapa de LEDs ya validado en la Fase 1.

Este cambio de arquitectura resolvió, como efecto colateral, todos los problemas de la Fase 2: cada tecla física tiene su propia coordenada única en este protocolo, así que no hay colisiones de scan code que resolver ni nombres localizados que traducir.

### Fase 4 — Validación cruzada contra OpenRGB

El proyecto [OpenRGB](https://gitlab.com/CalcProgrammer1/OpenRGB) incluye un driver propio para esta misma familia de teclados (`AsusAuraTUFKeyboardController`, PID `0x1B30` para la TUF K3 Gen II), publicado bajo GPL-2.0-or-later. Se usó como referencia para validar el protocolo de escritura de color reconstruido en la Fase 1, sin copiar código — cruzando estructura de paquete contra estructura de paquete.

El resultado confirmó la cabecera (`0xC0, 0x81`), el troceo en bloques de 15 LEDs y el formato `[ID, R, G, B]` de 4 bytes, pero reveló una discrepancia real: el tercer byte de la cabecera, que en la implementación de OpenRGB lleva la cantidad real de LEDs de ese paquete puntual, en este driver iba fijo en `0x36` (54) sin importar cuántos LEDs trajera cada paquete — probablemente un artefacto de haber fijado el valor de una única captura de Wireshark en vez de calcularlo por paquete. No causaba ningún problema visible (el relleno con `0xFF` como ID inexistente hace que el firmware ignore las entradas de más de todos modos), pero se corrigió para que ese byte refleje la cantidad real en cada paquete, alineado con la implementación verificada.

De paso, esta revisión reveló que OpenRGB nunca lee el estado de las teclas para su modo `REACTIVE` (`AURA_KEYBOARD_MODE_REACTIVE`) — lo maneja enteramente el firmware del teclado a partir de un único comando de configuración. No se exploró si ese modo nativo replica el efecto inverso específico de este proyecto (reposo en blanco, tecla se apaga y funde de vuelta), ya que la mayoría de los modos "Reactive" de fábrica funcionan al revés (reposo oscuro, tecla se enciende y decae) — queda como posible simplificación a futuro, sujeta a probarse contra el hardware real.

## Resolución de Bugs Notables

| Problema | Causa | Solución |
|---|---|---|
| La tecla Esc parpadeaba sola | El relleno de ceros al final del paquete de 64 bytes sobreescribía el LED `0x00` (Esc) | Rellenar con un ID de LED inexistente (`0xFF`) en vez de ceros |
| El encendido se sentía "de golpe" | Interpolación lineal de brillo, poco perceptible a bajos niveles de luz para el ojo humano | Curva ease-in cúbica (`brillo = 255 · progreso³`) en vez de lineal |
| Numpad apagaba el LED del mismo número en la fila superior | El driver original matcheaba por nombre de tecla; con NumLock activo, `keyboard` reportaba el mismo nombre para Numpad 1 y la tecla "1" superior, sin distinguir el origen físico | Priorizar `scan_code` (identificador físico de bajo nivel) sobre el nombre lógico de la tecla |
| Numpad apagaba LEDs de Insertar/Suprimir/Flechas/Re Pág/Av Pág | Al pasar a detectar por `scan_code`, estas teclas resultaron compartir el mismo código que el numérico por diseño histórico del PC/AT; el driver no distinguía el origen | Filtrar por el flag `is_keypad` antes de confiar en el scan code |
| Enter numérico apagaba el Enter normal | Ambos comparten el mismo `scan_code` (28); solo `is_keypad` los distingue | Mover el Enter numérico a la rama que exige `is_keypad = True` |
| Bloq Mayús, flechas y varias teclas de símbolo no hacían nada | Windows en español devuelve nombres de tecla traducidos que no matcheaban el mapa en inglés | Migrar esas teclas a detección por `scan_code`, inmune al idioma |
| Re Pág / Av Pág apagaban LEDs del numérico | Comparten `scan_code` con Numpad 9 y 3 por el mismo motivo histórico que Insertar/Suprimir, pero son teclas dedicadas en este modelo, con LED propio | Enrutarlas a su propio LED en vez de reusar el del numérico |
| Fn no generaba ningún evento detectable | Fn se resuelve enteramente dentro del firmware del teclado; no llega como evento de teclado estándar a ningún sistema operativo | Detectarla leyendo la interfaz HID propietaria (`0xFFC0`) en paralelo |
| El tercer byte de la cabecera de color no reflejaba la cantidad real de LEDs por paquete | Quedó fijo en `0x36` desde la captura original en vez de calcularse por paquete | Corregido a `len(chunk)` — cantidad real de LEDs de cada paquete puntual, validado contra la implementación de OpenRGB |

## Seguridad frente a Anti-Cheat

La versión final de este driver no usa ningún hook de teclado del sistema operativo ni instala ningún driver de kernel — toda la comunicación es lectura/escritura HID en espacio de usuario, el mismo nivel de acceso que tiene cualquier utilidad estándar de mouse o joystick para leer sus propios botones. Esto reduce de forma real el perfil de riesgo frente a anti-cheat de nivel kernel (Vanguard, Easy Anti-Cheat) respecto a la primera versión, que sí usaba un hook global.

Dicho esto, **ningún método por software puede garantizar riesgo cero frente a un anti-cheat de kernel**. Sus heurísticas de detección no son públicas y cambian con frecuencia, y por diseño explícito de estos sistemas — Riot lo documenta en sus propios canales oficiales — las sanciones suelen aplicarse con demora deliberada, justamente para que una prueba manual sin incidentes no sea garantía de nada. Usalo bajo tu propio criterio de riesgo, y considerá cerrarlo mientras corren juegos protegidos por anti-cheat de kernel si tu tolerancia al riesgo es baja.

### Un dato adicional, con matiz: OpenRGB y Vanguard

OpenRGB es ampliamente considerado seguro frente a Vanguard, pero no sin historial: el propio [wiki de OpenRGB](https://openrgb-wiki.readthedocs.io/en/latest/Frequently-Asked-Questions/) reconoce que Vanguard bloqueó activamente su driver original de acceso a bajo nivel, `InpOut32`, al punto de que el proyecto tuvo que migrar a otro driver (`WinRing0`) para evitar el conflicto. Ese problema es específico del subsistema de SMBus/I2C que OpenRGB usa para controlar RGB de placa madre y RAM — un mecanismo completamente distinto al que usa el driver de teclado (`AsusAuraTUFKeyboardController`), que solo habla `hidapi` puro, sin ningún driver adicional. No hay reportes conocidos de conflicto entre Vanguard y ese camino específico, y es el mismo camino que sigue este proyecto.

## Limitaciones conocidas

- Depende de `hidapi` y de las interfaces HID de Windows — no probado en Linux ni macOS.
- El VID está hardcodeado (`0x0B05`, ASUS) y `KEY_MATRIX` es específico de esta unidad; otro modelo de teclado, incluso otro ASUS, va a tener un mapa de bytes/bits distinto.
- La tecla `iso_#` (layouts ISO europeos) no está mapeada — esta unidad ANSI/Latinoamericana no la tiene físicamente.
- Si Armoury Crate o SignalRGB están corriendo, van a competir por las mismas interfaces HID y el driver va a fallar al conectar.

## Créditos

- [OpenRGB](https://gitlab.com/CalcProgrammer1/OpenRGB) (GPL-2.0-or-later) — su driver `AsusAuraTUFKeyboardController` se usó como referencia para validar el protocolo de escritura de color reconstruido por ingeniería inversa (ver Fase 4). No se copió código de OpenRGB en este proyecto.

## Licencia

Este proyecto está bajo la licencia MIT. Ver [LICENSE](LICENSE) para el texto completo.