import asyncio
import tkinter as tk
from tkinter import filedialog, scrolledtext
from bleak import BleakClient
import os
import datetime
from collections import deque

# UUID for BLE characteristic (same as your Arduino)
CHARACTERISTIC_UUID = "87654321-4321-4321-4321-ba0987654321"

class BLEApp:
    def __init__(self, master):
        self.master = master
        self.loop = asyncio.new_event_loop()

        # State
        self.device_address = tk.StringVar(value="XX:XX:XX:XX:XX:XX")
        self.save_location = tk.StringVar(value=os.getcwd())
        self.sample_rate = tk.StringVar(value="10")
        self.duration = tk.StringVar(value="10")

        # Diagnostic log FIFO buffer (limit 100 messages)
        self.log_fifo = deque(maxlen=100)

        # BLE client handle
        self.client = None

        # --- GUI Setup ---

        # Device Address
        tk.Label(master, text="BLE Device Address:").pack(anchor='w', padx=10, pady=(10,0))
        self.address_entry = tk.Entry(master, textvariable=self.device_address, width=30)
        self.address_entry.pack(anchor='w', padx=10)

        # Save Location with Browse button
        tk.Label(master, text="Save Location:").pack(anchor='w', padx=10, pady=(10,0))
        frame_save = tk.Frame(master)
        frame_save.pack(fill='x', padx=10)
        self.location_label = tk.Label(frame_save, textvariable=self.save_location, relief="sunken", anchor="w", width=40)
        self.location_label.pack(side='left', fill='x', expand=True)
        self.browse_button = tk.Button(frame_save, text="Browse...", command=self.choose_save_location)
        self.browse_button.pack(side='left', padx=5)

        # Sample Rate and Duration controls on the same line
        frame_params = tk.Frame(master)
        frame_params.pack(padx=10, pady=(10,5), anchor='w')

        tk.Label(frame_params, text="Sample Rate (Hz):").pack(side='left')
        self.sample_rate_entry = tk.Entry(frame_params, textvariable=self.sample_rate, width=5)
        self.sample_rate_entry.pack(side='left', padx=(2,10))

        tk.Label(frame_params, text="Duration (s):").pack(side='left')
        self.duration_entry = tk.Entry(frame_params, textvariable=self.duration, width=5)
        self.duration_entry.pack(side='left', padx=(2,10))

        # Buttons: Connect / Dump Logs / Sync Time / Start CSV on one line
        frame_buttons1 = tk.Frame(master)
        frame_buttons1.pack(padx=10, pady=5, anchor='w')

        self.connect_button = tk.Button(frame_buttons1, text="Connect to Device", command=self.connect_to_device)
        self.connect_button.pack(side='left', padx=5)

        self.dump_logs_button = tk.Button(frame_buttons1, text="Dump Logs", command=self.dump_logs)
        self.dump_logs_button.pack(side='left', padx=5)

        self.sync_time_button = tk.Button(frame_buttons1, text="Sync Time", command=self.sync_time)
        self.sync_time_button.pack(side='left', padx=5)

        self.start_csv_button = tk.Button(frame_buttons1, text="Start CSV", command=self.start_csv)
        self.start_csv_button.pack(side='left', padx=5)

        # Buttons: Ping and Read INA228 on next line
        frame_buttons2 = tk.Frame(master)
        frame_buttons2.pack(padx=10, pady=5, anchor='w')

        self.ping_button = tk.Button(frame_buttons2, text="Ping", command=self.ping_device)
        self.ping_button.pack(side='left', padx=5)

        self.read_ina_button = tk.Button(frame_buttons2, text="Read INA228", command=self.read_ina228)
        self.read_ina_button.pack(side='left', padx=5)

        # Diagnostic Log Text Box
        tk.Label(master, text="Diagnostics:").pack(anchor='w', padx=10)
        self.log_text = scrolledtext.ScrolledText(master, height=15, width=70, state='disabled')
        self.log_text.pack(padx=10, pady=(0,10), fill='both', expand=True)

        # Start asyncio event loop on background thread
        import threading
        threading.Thread(target=self.start_loop, daemon=True).start()

        # Periodically update log text widget from FIFO buffer
        self.master.after(100, self.update_log_text)

    # --- Methods ---

    def start_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def choose_save_location(self):
        folder_selected = filedialog.askdirectory()
        if folder_selected:
            self.save_location.set(folder_selected)
            self.log_message(f"📂 Save location set to: {folder_selected}")

    def log_message(self, message):
        # Add to FIFO buffer and print to console
        self.log_fifo.append(message)
        print(message)

    def update_log_text(self):
        self.log_text.config(state='normal')
        self.log_text.delete(1.0, tk.END)
        for msg in self.log_fifo:
            self.log_text.insert(tk.END, msg + "\n")
        self.log_text.yview(tk.END)
        self.log_text.config(state='disabled')
        self.master.after(100, self.update_log_text)

    def connect_to_device(self):
        address = self.device_address.get().strip()
        if not address:
            self.log_message("⚠️ Please enter a valid BLE device address.")
            return
        self.log_message(f"🔌 Connecting to {address} ...")
        self.loop.call_soon_threadsafe(asyncio.create_task, self.connect_ble(address))

    async def connect_ble(self, address):
        try:
            if self.client and self.client.is_connected:
                await self.client.disconnect()
                self.log_message("ℹ️ Disconnected previous connection.")

            self.client = BleakClient(address)
            await self.client.connect()
            if self.client.is_connected:
                self.log_message(f"✅ Connected to {address}!")
            else:
                self.log_message(f"❌ Failed to connect to {address}.")
        except Exception as e:
            self.log_message(f"⚠️ Connection error: {e}")

    def dump_logs(self):
        self.log_message("📝 Requesting logs...")
        self.loop.call_soon_threadsafe(asyncio.create_task, self.send_command("dump_logs"))

    def sync_time(self):
        time_str = datetime.datetime.now().isoformat()
        self.log_message(f"⏰ Syncing time: {time_str}")
        self.loop.call_soon_threadsafe(asyncio.create_task, self.send_command(f"set_time,{time_str}"))

    def start_csv(self):
        try:
            sample_rate = int(self.sample_rate.get())
            duration = int(self.duration.get())
        except ValueError:
            self.log_message("⚠️ Invalid sample rate or duration. Please enter integers.")
            return

        save_path = self.save_location.get()
        self.log_message(f"📈 Starting CSV stream at {sample_rate} Hz for {duration}s, saving to {save_path}...")
        # Send sample rate and duration commands separately or combined
        self.loop.call_soon_threadsafe(asyncio.create_task, self.send_command(f"set_sample_rate,{sample_rate}"))
        self.loop.call_soon_threadsafe(asyncio.create_task, self.send_command(f"set_duration,{duration}"))
        self.loop.call_soon_threadsafe(asyncio.create_task, self.send_command("start_csv"))

    def ping_device(self):
        self.log_message("📡 Sending ping...")
        self.loop.call_soon_threadsafe(asyncio.create_task, self.send_command("ping"))

    def read_ina228(self):
        self.log_message("🔋 Requesting INA228 readings...")
        self.loop.call_soon_threadsafe(asyncio.create_task, self.send_command("read_ina"))

    async def send_command(self, command):
        if self.client and self.client.is_connected:
            try:
                await self.client.write_gatt_char(CHARACTERISTIC_UUID, command.encode())
                self.log_message(f"➡️ Sent command: {command}")
            except Exception as e:
                self.log_message(f"⚠️ Error sending command: {e}")
        else:
            self.log_message("⚠️ Not connected to any BLE device.")

def main():
    root = tk.Tk()
    root.title("BLE Controller GUI")
    app = BLEApp(root)
    root.geometry("600x600")
    root.mainloop()

if __name__ == "__main__":
    main()
