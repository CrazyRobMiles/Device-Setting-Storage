from device_configurator import DeviceConfigurator
import board
import neopixel
import time
import wifi
import socketpool
import mdns
import adafruit_requests
import os
import json

pixels = neopixel.NeoPixel(board.GP18, 64*3, brightness=0.2)

# Define color constants
GREY     = (30, 30, 30)
GREEN    = (0, 80, 0)
RED      = (100, 0, 0)
BLUE     = (0, 0, 60)
MAGENTA  = (150, 0, 150)

col = {
    "red":130,
    "green":100,
    "blue":50
}

network = {
    "ssid": "YourWiFiName",
    "password": "YourWiFiPassword",
    "hostname": "mylight"
}

settings = {
    "col":col,
    "network":network
}

# Create configurator instance
config = DeviceConfigurator(
    settings,
    use_obfuscation=True,
    on_settings_loaded=lambda s: pixels.fill(GREEN),
    on_file_error=lambda e: pixels.fill(RED),
    on_waiting_for_host=lambda: pixels.fill(BLUE),
    on_settings_received=lambda s: pixels.fill(MAGENTA)
)

# Try to load settings or prepare for fallback
result = config.setup()

# If setup failed (e.g., file error), wait for settings over USB
if result is None:
    settings = config.wait_for_settings()

# Leave the loading settings there for a while
time.sleep(2)


gamma_table = bytearray(256)
gamma = 2.2
for i in range(256):
    gamma_table[i] = int((i / 255.0) ** gamma * 255.0 + 0.5)

def correct_color(r,g,b):
    return (gamma_table[r], gamma_table[g], gamma_table[b])

# Use settings
cols=settings["col"]
network=settings["network"]

pixels.fill(correct_color(cols["red"], cols["green"], cols["blue"]))

# Connect Wi-Fi
print("Connecting to Wi-Fi...")
wifi.radio.connect(network["ssid"], network["password"])
print("Connected! IP:", wifi.radio.ipv4_address)

# mDNS
mdns_server = mdns.Server(wifi.radio)
mdns_server.hostname = network["hostname"]
mdns_server.advertise_service(service_type="_http", protocol="_tcp", port=80)
print(f"mDNS active: http://{mdns_server.hostname}.local/")

# Prepare Socket
pool = socketpool.SocketPool(wifi.radio)
server = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
server.bind(('0.0.0.0', 80))
server.listen(1)
print("Server listening...")

# Read the HTML page once at startup
try:
    with open("/index.html", "r") as f:
        html_content = f.read()
except Exception as e:
    print("Could not read index.html:", e)
    html_content = "<h1>Error loading page</h1>"

while True:
    conn, addr = server.accept()
    print("Client connected:", addr)

    buffer = bytearray(2048)  # 2KB buffer
    size = conn.recv_into(buffer)
    request_str = buffer[:size].decode('utf-8')
    print("Request:", request_str)

    if "POST /set" in request_str:
        # Handle color set request
        header_end = request_str.find("\r\n\r\n")
        if header_end != -1:
            body = request_str[header_end+4:]
            print("Body:", body)
            try:
                color_data = json.loads(body)
                r = int(color_data.get("r", 0))
                g = int(color_data.get("g", 0))
                b = int(color_data.get("b", 0))
                pixels.fill(correct_color(r, g, b))
                cols["red"]=r;
                cols["green"]=g;
                cols["blue"]=b;
                config.save()
            except Exception as e:
                print("JSON parse error:", e)
        
        # Acknowledge
        response = "HTTP/1.1 204 No Content\r\n\r\n"
        conn.send(response.encode('utf-8'))

    else:
        # Serve the index page
        response = "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + html_content
        conn.send(response.encode('utf-8'))

    conn.close()

