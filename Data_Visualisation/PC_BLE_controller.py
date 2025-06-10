import asyncio
import threading
import tkinter as tk
from bleak import BleakClient, BleakScanner

# UUIDs (match ESP32 sketch)
SERVICE_UUID = "12345678-1234-1234-1234-1234567890ab"
CHARACTERISTIC_UUID = "87654321-4321-4321-4321-ba0987654321"

esp32_address = None
client = None

# Discover ESP32 device
async def discover_esp32():
    global esp32_address
    devices = await BleakScanner.discover()
    for d in devices:
        if d.name == "ESP32_BLE_Server":
            esp32_address = d.address
            break

# Connect to ESP32
async def connect_esp32():
    global client
    if esp32_address is None:
        await discover_esp32()
    if esp32_address:
        client = BleakClient(esp32_address)
        await client.connect()
        print(f"Connected to {esp32_address}")
    else:
        print("ESP32 not found")

# Send ping command
async def send_ping():
    if client and client.is_connected:
        await client.write_gatt_char(CHARACTERISTIC_UUID, b"ping")
        response = await client.read_gatt_char(CHARACTERISTIC_UUID)
        return response.decode("utf-8")
    else:
        return "Not connected"

# Read INA228 data
async def read_ina():
    if client and client.is_connected:
        await client.write_gatt_char(CHARACTERISTIC_UUID, b"read_ina")
        response = await client.read_gatt_char(CHARACTERISTIC_UUID)
        csv_data = response.decode("utf-8")
        with open("ina228_data.csv", "a") as f:
            f.write(csv_data + "\n")
        return f"INA228 data saved: {csv_data}"
    else:
        return "Not connected"

# Thread wrapper for running async in Tkinter
def run_async_task(coro, callback=None):
    def _task():
        result = asyncio.run(coro())
        if callback:
            callback(result)
    threading.Thread(target=_task).start()

# GUI handlers
def on_connect():
    status_label.config(text="Connecting...")
    run_async_task(connect_esp32, lambda _: status_label.config(text="Connected!"))

def on_ping():
    run_async_task(send_ping, update_response)

def on_read_ina():
    run_async_task(read_ina, update_response)

def update_response(response):
    output_box.insert(tk.END, f"{response}\n")
    output_box.see(tk.END)

# Tkinter window
root = tk.Tk()
root.title("BLE Controller")

frame = tk.Frame(root, padx=20, pady=20)
frame.pack()

connect_button = tk.Button(frame, text="Connect", command=on_connect)
connect_button.grid(row=0, column=0, padx=5, pady=5)

ping_button = tk.Button(frame, text="Send Ping", command=on_ping)
ping_button.grid(row=0, column=1, padx=5, pady=5)

ina_button = tk.Button(frame, text="Read INA228", command=on_read_ina)
ina_button.grid(row=0, column=2, padx=5, pady=5)

status_label = tk.Label(frame, text="Disconnected")
status_label.grid(row=1, column=0, columnspan=3, pady=5)

output_box = tk.Text(frame, height=10, width=60)
output_box.grid(row=2, column=0, columnspan=3, pady=5)

root.mainloop()
