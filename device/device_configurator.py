# device_configurator.py

import board
import digitalio
import usb_cdc
import time
import json
import os

try:
    import microcontroller
    uid_bytes = microcontroller.cpu.uid
except ImportError:
    uid_bytes = b'\x01\x02\x03\x04\x05\x06\x07\x08'

MAGIC = b'\xDE\xAD\xBE\xEF'

class DeviceConfigurator:
    def __init__(
        self,
        settings: dict,
        settings_file="/settings.txt",
        safe_pin=board.GP6,
        use_obfuscation=False,
        on_settings_loaded=None,
        on_file_error=None,
        on_waiting_for_host=None,
        on_settings_received=None
    ):
        self.settings = settings
        self.settings_file = settings_file
        self.safe_pin = digitalio.DigitalInOut(safe_pin)
        self.safe_pin.switch_to_input(pull=digitalio.Pull.UP)
        self.use_obfuscation = use_obfuscation

        self.on_settings_loaded = on_settings_loaded
        self.on_file_error = on_file_error
        self.on_waiting_for_host = on_waiting_for_host
        self.on_settings_received = on_settings_received

    def file_exists(self):
        try:
            os.stat(self.settings_file)
            return True
        except OSError:
            return False

    def _prng(self, seed):
        state = seed
        while True:
            state = (state * 1103515245 + 12345) & 0x7FFFFFFF
            yield state & 0xFF

    def _xor_data(self, data, seed):
        rng = self._prng(seed)
        return bytes([b ^ next(rng) for b in data])

    def load(self):
        try:
            with open(self.settings_file, "rb" if self.use_obfuscation else "r") as f:
                data = f.read()

            if self.use_obfuscation:
                if data[:4] != MAGIC:
                    raise ValueError("Invalid magic header")
                obfuscated = data[4:]
                seed = sum(uid_bytes)
                json_bytes = self._xor_data(obfuscated, seed)
                loaded = json.loads(json_bytes.decode("utf-8"))
            else:
                loaded = json.loads(data)

            self.settings.clear()
            self.settings.update(loaded)
            return True
        except Exception as e:
            raise e

    def save(self):
        try:
            if self.use_obfuscation:
                json_bytes = json.dumps(self.settings).encode("utf-8")
                seed = sum(uid_bytes)
                obfuscated = self._xor_data(json_bytes, seed)
                with open(self.settings_file, "wb") as f:
                    f.write(MAGIC + obfuscated)
            else:
                with open(self.settings_file, "w") as f:
                    json.dump(self.settings, f)
            return True
        except Exception as e:
            raise e

    def wait_for_settings(self):
        if self.on_waiting_for_host:
            self.on_waiting_for_host()

        while True:
            if usb_cdc.data.connected:
                try:
                    line = usb_cdc.data.readline().decode("utf-8").strip()
                    if line == "GET":
                        usb_cdc.data.write((json.dumps(self.settings) + "\n").encode("utf-8"))
                        continue
                    if line.startswith("{"):
                        self.settings.clear()
                        self.settings.update(json.loads(line))
                        self.save()
                        if self.on_settings_received:
                            self.on_settings_received(self.settings)
                        return self.settings
                except Exception as e:
                    print("Serial error:", e)
            time.sleep(0.1)

    def setup(self):
        if not self.file_exists() or not self.safe_pin.value:
            print("Entering setup mode")
            if self.on_waiting_for_host:
                self.on_waiting_for_host()
            return self.wait_for_settings()

        try:
            if self.load():
                print("Settings loaded")
                if self.on_settings_loaded:
                    self.on_settings_loaded(self.settings)
                return self.settings
        except Exception as e:
            print("Error loading settings:", e)
            if self.on_file_error:
                self.on_file_error(e)

        return None
