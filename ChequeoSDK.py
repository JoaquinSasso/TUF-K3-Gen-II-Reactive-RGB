import openrgb

def diagnostico_completo():
    print("Conectando al servidor SDK...")
    client = openrgb.OpenRGBClient()
    
    print("\n--- DISPOSITIVOS DETECTADOS POR OPENRGB ---")
    if not client.devices:
        print("No se detectó absolutamente ningún dispositivo (Revisa permisos de Administrador o conflictos con ASUS).")
        return

    for i, dev in enumerate(client.devices):
        # dev.type.name nos dirá si lo ve como KEYBOARD, MOTHERBOARD, etc.
        print(f"\n[{i}] Nombre: {dev.name}")
        print(f"    Tipo:   {dev.type.name}")
        print(f"    Zonas:  {len(dev.zones)}")
        print(f"    LEDs:   {len(dev.leds)}")
        
        if len(dev.leds) > 0:
            print(f"    Primeros 3 LEDs: {[led.name for led in dev.leds[:3]]}")
        else:
            print("    [!] ADVERTENCIA: Este dispositivo reporta 0 LEDs controlables.")

if __name__ == '__main__':
    diagnostico_completo()