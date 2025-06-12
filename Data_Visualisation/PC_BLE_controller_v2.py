import tkinter as tk
from tkinter import ttk, messagebox
import asyncio
import bleak
import threading
import queue
import pandas as pd
from datetime import datetime
import os
import time
import socket
import configparser

class ESP32GUI:
    def __init__(self, root):
        self.root = root
        self.root.title("ESP32 PPG Compression Monitor")
        
        self.s3_client = None
        self.power_client = None
        self.running = [False, False]  # [S3, Power]
        self.data_queues = [queue.Queue(), queue.Queue()]
        self.compressed_files = {}
        self.power_logs = []
        self.waveform_data = []
        self.current_waveform = []
        self.tcp_server_thread = None
        self.tcp_data_queue = queue.Queue()
        
        # Initialize status_text early to avoid AttributeError
        self.status_text = tk.Text(self.root, height=10, width=50)
        
        # Configuration defaults
        self.config = {
            's3_device_name': 'ESP32_S3_PPG',
            'power_device_name': 'ESP32_PPG_POWER',
            'wifi_ssid': '',
            'wifi_password': '',
            'tcp_server_ip': '192.168.1.100',
            'tcp_server_port': '5000',
            'ppg_files': ['ppg_1.csv', 'ppg_2.csv', 'ppg_3.csv', 'ppg_4.csv',
                          'ppg_5.csv', 'ppg_6.csv', 'ppg_7.csv', 'ppg_8.csv']
        }
        
        self.load_config()
        self.setup_gui()
        self.start_tcp_server()
        
    def load_config(self):
        """Load configuration from config.txt."""
        config_file = 'config.txt'
        if not os.path.exists(config_file):
            self.status_text.insert(tk.END, f"Config file {config_file} not found. Using defaults.\n")
            self.status_text.see(tk.END)
            return
        
        parser = configparser.ConfigParser()
        try:
            with open(config_file, 'r') as f:
                content = '[DEFAULT]\n' + f.read()
            parser.read_string(content)
            
            self.config['s3_device_name'] = parser.get('DEFAULT', 's3_device_name', fallback=self.config['s3_device_name'])
            self.config['power_device_name'] = parser.get('DEFAULT', 'power_device_name', fallback=self.config['power_device_name'])
            self.config['wifi_ssid'] = parser.get('DEFAULT', 'wifi_ssid', fallback=self.config['wifi_ssid'])
            self.config['wifi_password'] = parser.get('DEFAULT', 'wifi_password', fallback=self.config['wifi_password'])
            self.config['tcp_server_ip'] = parser.get('DEFAULT', 'tcp_server_ip', fallback=self.config['tcp_server_ip'])
            self.config['tcp_server_port'] = parser.get('DEFAULT', 'tcp_server_port', fallback=self.config['tcp_server_port'])
            ppg_files = parser.get('DEFAULT', 'ppg_files', fallback=','.join(self.config['ppg_files']))
            self.config['ppg_files'] = [f.strip() for f in ppg_files.split(',') if f.strip()]
            
        except Exception as e:
            self.root.after(0, lambda: (
                self.status_text.insert(tk.END, f"Error reading config file: {e}. Using defaults.\n"),
                self.status_text.see(tk.END)
            ))
        
    def setup_gui(self):
        tk.Label(self.root, text="ESP32-S3 Device Name:").grid(row=0, column=0, padx=5, pady=5)
        self.s3_entry = tk.Entry(self.root)
        self.s3_entry.insert(0, self.config['s3_device_name'])
        self.s3_entry.grid(row=0, column=1, padx=5, pady=5)
        
        tk.Label(self.root, text="CP2102 ESP32 Device Name:").grid(row=1, column=0, padx=5, pady=5)
        self.power_entry = tk.Entry(self.root)
        self.power_entry.insert(0, self.config['power_device_name'])
        self.power_entry.grid(row=1, column=1, padx=5, pady=5)
        
        tk.Label(self.root, text="PPG File:").grid(row=2, column=0, padx=5, pady=5)
        self.file_var = tk.StringVar(value=self.config['ppg_files'][0] if self.config['ppg_files'] else "ppg_1.csv")
        self.file_menu = ttk.Combobox(self.root, textvariable=self.file_var, 
                                      values=self.config['ppg_files'], state="readonly")
        self.file_menu.grid(row=2, column=1, padx=5, pady=5)
        
        tk.Label(self.root, text="Compression Mode:").grid(row=3, column=0, padx=5, pady=5)
        self.mode_var = tk.StringVar(value="SINGLE")
        self.mode_menu = ttk.Combobox(self.root, textvariable=self.mode_var, values=["SINGLE", "REPEAT"], state="readonly")
        self.mode_menu.grid(row=3, column=1, padx=5, pady=5)
        self.mode_menu.bind("<<ComboboxSelected>>", self.toggle_repeats)
        
        tk.Label(self.root, text="Number of Repeats:").grid(row=4, column=0, padx=5, pady=5)
        self.repeats_entry = tk.Entry(self.root, state="disabled")
        self.repeats_entry.insert(0, "1")
        self.repeats_entry.grid(row=4, column=1, padx=5, pady=5)
        
        tk.Label(self.root, text="Compression Algorithm:").grid(row=5, column=0, padx=5, pady=5)
        self.algo_var = tk.StringVar(value="AUTOENCODER")
        self.algo_menu = ttk.Combobox(self.root, textvariable=self.algo_var, 
                                      values=["AUTOENCODER", "PCA", "RLE", "HUFFMAN"], state="readonly")
        self.algo_menu.grid(row=5, column=1, padx=5, pady=5)
        
        tk.Label(self.root, text="Transmission Protocol:").grid(row=6, column=0, padx=5, pady=5)
        self.protocol_var = tk.StringVar(value="BLE")
        self.protocol_menu = ttk.Combobox(self.root, textvariable=self.protocol_var, 
                                          values=["BLE", "WIFI"], state="readonly")
        self.protocol_menu.grid(row=6, column=1, padx=5, pady=5)
        
        self.connect_btn = tk.Button(self.root, text="Connect Both", command=self.connect_both)
        self.connect_btn.grid(row=7, column=0, columnspan=2, pady=10)
        
        self.disconnect_btn = tk.Button(self.root, text="Disconnect Both", command=self.disconnect_both, state="disabled")
        self.disconnect_btn.grid(row=8, column=0, columnspan=2, pady=10)
        
        self.start_btn = tk.Button(self.root, text="Start Process", command=self.start_process, state="disabled")
        self.start_btn.grid(row=9, column=0, columnspan=2, pady=10)
        
        tk.Label(self.root, text="Status:").grid(row=10, column=0, padx=5, pady=5)
        self.status_text.grid(row=11, column=0, columnspan=2, padx=5, pady=5)
        
        tk.Label(self.root, text="Power Logs:").grid(row=12, column=0, padx=5, pady=5)
        self.power_text = tk.Text(self.root, height=12, width=50)
        self.power_text.grid(row=13, column=0, columnspan=2, padx=5, pady=5)
        
    def start_tcp_server(self):
        def tcp_server():
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                server_socket.bind(('0.0.0.0', int(self.config['tcp_server_port'])))
                server_socket.listen(1)
                
                while True:
                    client_socket, addr = server_socket.accept()
                    current_file = None
                    file_data = bytearray()
                    file_id = None
                    
                    while True:
                        data = client_socket.recv(1024)
                        if not data:
                            break
                        try:
                            message = data.decode('utf-8').strip()
                            if message.startswith("FILE_START:"):
                                _, id_, filename, size = message.split(':')
                                file_id = int(id_)
                                current_file = filename
                                file_data = bytearray()
                                self.root.after(0, lambda: (
                                    self.status_text.insert(tk.END, f"Receiving file {id_}: {filename} via WiFi\n"),
                                    self.status_text.see(tk.END)
                                ))
                            elif message == "FILE_END":
                                self.compressed_files[file_id] = bytes(file_data)
                                self.save_and_decompress(file_id)
                                current_file = None
                                break
                            elif current_file:
                                file_data.extend(data)
                        except UnicodeDecodeError:
                            if current_file:
                                file_data.extend(data)
                    client_socket.close()
            except Exception as e:
                self.root.after(0, lambda: (
                    self.status_text.insert(tk.END, f"TCP server error: {e}\n"),
                    self.status_text.see(tk.END)
                ))
            finally:
                server_socket.close()
        
        self.tcp_server_thread = threading.Thread(target=tcp_server, daemon=True)
        self.tcp_server_thread.start()
        
    def toggle_repeats(self, event=None):
        self.repeats_entry.config(state="normal" if self.mode_var.get() == "REPEAT" else "disabled")
        
    def connect_both(self):
        threading.Thread(target=lambda: asyncio.run(self.connect_ble()), daemon=True).start()
        
    async def connect_ble(self):
        try:
            s3_name = self.s3_entry.get()
            power_name = self.power_entry.get()
            
            s3_device = await bleak.BleakScanner.find_device_by_name(s3_name)
            power_device = await bleak.BleakScanner.find_device_by_name(power_name)
            
            if not s3_device or not power_device:
                self.root.after(0, lambda: messagebox.showerror("Error", "One or both devices not found"))
                return
            
            self.s3_client = bleak.BleakClient(s3_device)
            self.power_client = bleak.BleakClient(power_device)
            
            await self.s3_client.connect()
            await self.power_client.connect()
            
            self.running = [True, True]
            self.root.after(0, lambda: (
                self.status_text.insert(tk.END, "Connected to both devices\n"),
                self.status_text.see(tk.END),
                self.connect_btn.config(state="disabled"),
                self.disconnect_btn.config(state="normal"),
                self.start_btn.config(state="normal")
            ))
            
            await self.s3_client.start_notify("6e400002-b5a3-f393-e0a9-e50e24dcca9e", self.s3_data_handler)
            await self.power_client.start_notify("7e400002-b5a3-f393-e0a9-e50e24dcca9e", self.power_data_handler)
            
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", f"Connection failed: {e}"))
            await self.disconnect_ble()
            
    def s3_data_handler(self, sender, data):
        try:
            message = data.decode('utf-8').strip()
            self.data_queues[0].put(('text', message))
        except UnicodeDecodeError:
            self.data_queues[0].put(('binary', data))
            
    def power_data_handler(self, sender, data):
        try:
            message = data.decode('utf-8').strip()
            self.data_queues[1].put(('text', message))
        except UnicodeDecodeError:
            self.data_queues[1].put(('binary', data))
        
    async def disconnect_ble(self):
        self.running = [False, False]
        try:
            if self.s3_client and self.s3_client.is_connected:
                await self.s3_client.disconnect()
            if self.power_client and self.power_client.is_connected:
                await self.power_client.disconnect()
        except Exception as e:
            self.root.after(0, lambda: self.status_text.insert(tk.END, f"Disconnect error: {e}\n"))
        self.s3_client = None
        self.power_client = None
        self.root.after(0, lambda: (
            self.status_text.insert(tk.END, "Disconnected both devices\n"),
            self.status_text.see(tk.END),
            self.connect_btn.config(state="normal"),
            self.disconnect_btn.config(state="disabled"),
            self.start_btn.config(state="disabled")
        ))
        
    def disconnect_both(self):
        threading.Thread(target=lambda: asyncio.run(self.disconnect_ble()), daemon=True).start()
        
    def start_process(self):
        mode = self.mode_var.get()
        file = self.file_var.get()
        algo = self.algo_var.get()
        protocol = self.protocol_var.get()
        wifi_ssid = self.config['wifi_ssid']
        wifi_password = self.config['wifi_password']
        command = f"{mode}:{file}:{algo}:{protocol}:{wifi_ssid}:{wifi_password}"
        if mode == "REPEAT":
            try:
                repeats = int(self.repeats_entry.get())
                if 1 <= repeats <= 5:
                    command = f"REPEAT:{repeats}:{file}:{algo}:{protocol}:{wifi_ssid}:{wifi_password}"
                else:
                    messagebox.showerror("Error", "Repeats must be 1-5")
                    return
            except ValueError:
                messagebox.showerror("Error", "Invalid number of repeats")
                return
        threading.Thread(target=lambda: asyncio.run(self.send_start_command(command)), daemon=True).start()
        
    async def send_start_command(self, command):
        try:
            if self.s3_client and self.s3_client.is_connected:
                await self.s3_client.write_gatt_char("beb5483e-36e1-4688-b7f5-ea07361b26a8", command.encode())
            if self.power_client and self.power_client.is_connected:
                await self.power_client.write_gatt_char("ceb5483e-36e1-4688-b7f5-ea07361b26a8", command.encode())
            self.root.after(0, lambda: (
                self.status_text.insert(tk.END, f"Sent command: {command}\n"),
                self.status_text.see(tk.END)
            ))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", f"Failed to send command: {e}"))
            
    def process_data(self):
        current_file = None
        file_data = bytearray()
        file_id = None
        current_waveform_op = None
        
        while any(self.running):
            for i in range(2):
                try:
                    item_type, item = self.data_queues[i].get_nowait()
                    if i == 0:  # ESP32-S3
                        if item_type == 'text':
                            if item.startswith("FILE_START:") and self.protocol_var.get() == "BLE":
                                _, id_, filename, size = item.split(':')
                                file_id = int(id_)
                                current_file = filename
                                file_data = bytearray()
                                self.root.after(0, lambda: (
                                    self.status_text.insert(tk.END, f"Receiving file {id_}: {filename} via BLE\n"),
                                    self.status_text.see(tk.END)
                                ))
                            elif item == "FILE_END" and current_file and self.protocol_var.get() == "BLE":
                                self.compressed_files[file_id] = bytes(file_data)
                                self.save_and_decompress(file_id)
                                current_file = None
                            elif item.startswith("COMPRESSION_START:") or item.startswith("TRANSMISSION_START:") or item == "ALL_DONE":
                                self.root.after(0, lambda: (
                                    self.status_text.insert(tk.END, f"S3: {item}\n"),
                                    self.status_text.see(tk.END)
                                ))
                        elif item_type == 'binary' and current_file and self.protocol_var.get() == "BLE":
                            file_data.extend(item)
                    else:  # CP2102 ESP32
                        if item_type == 'text':
                            if item == "WAVEFORM_START":
                                self.waveform_data = []
                                self.current_waveform = []
                            elif item.startswith("WAVEFORM_OP:"):
                                if self.current_waveform:
                                    self.waveform_data.append(self.current_waveform)
                                _, op, id_, _ = item.split(':')
                                current_waveform_op = (op, int(id_))
                                self.current_waveform = []
                            elif item == "WAVEFORM_END":
                                if self.current_waveform:
                                    self.waveform_data.append(self.current_waveform)
                                self.save_waveform_data()
                            elif item.startswith("POWER_LOGS_START"):
                                self.power_logs = []
                            elif item == "POWER_LOGS_END":
                                self.display_power_logs()
                            elif ',' in item:
                                if current_waveform_op:
                                    try:
                                        ts, volt, curr = map(float, item.split(','))
                                        self.current_waveform.append({
                                            "Timestamp_ms": ts,
                                            "Voltage_mV": volt,
                                            "Current_mA": curr
                                        })
                                    except ValueError:
                                        self.root.after(0, lambda: (
                                            self.status_text.insert(tk.END, f"Invalid waveform data: {item}\n"),
                                            self.status_text.see(tk.END)
                                        ))
                                else:
                                    try:
                                        id_, op, volt, curr, energy, duration = item.split(',')
                                        self.power_logs.append({
                                            "ID": int(id_),
                                            "Operation": op,
                                            "Voltage_mV": float(volt),
                                            "Current_mA": float(curr),
                                            "Energy_mWh": float(energy),
                                            "Duration_ms": int(duration)
                                        })
                                    except ValueError:
                                        self.root.after(0, lambda: (
                                            self.status_text.insert(tk.END, f"Invalid power log: {item}\n"),
                                            self.status_text.see(tk.END)
                                        ))
                            else:
                                self.root.after(0, lambda: (
                                    self.status_text.insert(tk.END, f"Power: {item}\n"),
                                    self.status_text.see(tk.END)
                                ))
                except queue.Empty:
                    pass
            time.sleep(0.01)
        
    def save_and_decompress(self, file_id):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        comp_file = f"compressed_ppg_{file_id}_{timestamp}.bin"
        try:
            with open(comp_file, "wb") as f:
                f.write(self.compressed_files[file_id])
            
            decomp_data = self.decompress(self.compressed_files[file_id])
            decomp_file = f"decompressed_ppg_{file_id}_{timestamp}.csv"
            with open(decomp_file, "wb") as f:
                f.write(decomp_data)
            df = pd.read_csv(decomp_file)
            self.root.after(0, lambda: (
                self.status_text.insert(tk.END, f"Decompressed file {file_id}: {len(df)} rows\n"),
                self.status_text.see(tk.END)
            ))
        except Exception as e:
            self.root.after(0, lambda: (
                self.status_text.insert(tk.END, f"Decompression error for file {file_id}: {e}\n"),
                self.status_text.see(tk.END)
            ))
        
    def decompress(self, data):
        return data
        
    def save_waveform_data(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for i, waveform in enumerate(self.waveform_data):
            if waveform and i < len(self.power_logs):
                op = self.power_logs[i]["Operation"].lower()
                id_ = self.power_logs[i]["ID"]
                df = pd.DataFrame(waveform)
                filename = f"ina228_waveform_{op}_{id_}_{timestamp}.csv"
                try:
                    df.to_csv(filename, index=False)
                    self.root.after(0, lambda: (
                        self.status_text.insert(tk.END, f"Saved waveform to {filename}\n"),
                        self.status_text.see(tk.END)
                    ))
                except Exception as e:
                    self.root.after(0, lambda: (
                        self.status_text.insert(tk.END, f"Error saving waveform {filename}: {e}\n"),
                        self.status_text.see(tk.END)
                    ))
        
    def display_power_logs(self):
        self.root.after(0, lambda: self.power_text.delete(1.0, tk.END))
        total_energy = 0
        comp_energy = 0
        trans_energy = 0
        comp_energies = []
        comp_voltages = []
        comp_currents = []
        comp_durations = []
        
        for log in self.power_logs:
            self.root.after(0, lambda: (
                self.power_text.insert(
                    tk.END,
                    f"{log['Operation']} {log['ID']}: {log['Energy_mWh']:.6f} mWh, "
                    f"{log['Voltage_mV']:.2f} mV, {log['Current_mA']:.2f} mA, "
                    f"{log['Duration_ms']} ms\n"
                ),
                self.power_text.see(tk.END)
            ))
            total_energy += log['Energy_mWh']
            if log['Operation'] == "Compression":
                comp_energy += log['Energy_mWh']
                comp_energies.append(log['Energy_mWh'])
                comp_voltages.append(log['Voltage_mV'])
                comp_currents.append(log['Current_mA'])
                comp_durations.append(log['Duration_ms'])
            else:
                trans_energy += log['Energy_mWh']
        
        if self.mode_var.get() == "REPEAT" and comp_energies:
            avg_energy = sum(comp_energies) / len(comp_energies)
            avg_voltage = sum(comp_voltages) / len(comp_voltages)
            avg_current = sum(comp_currents) / len(comp_currents)
            avg_duration = sum(comp_durations) / len(comp_durations)
            self.root.after(0, lambda: (
                self.power_text.insert(
                    tk.END,
                    f"\nAverage Compression Energy: {avg_energy:.6f} mWh\n"
                    f"Average Compression Voltage: {avg_voltage:.2f} mV\n"
                    f"Average Compression Current: {avg_current:.2f} mA\n"
                    f"Average Compression Duration: {avg_duration:.2f} ms\n"
                ),
                self.power_text.see(tk.END)
            ))
        
        self.root.after(0, lambda: (
            self.power_text.insert(
                tk.END,
                f"\nTotal Compression Energy: {comp_energy:.6f} mWh\n"
                f"Transmission Energy: {trans_energy:.6f} mWh\n"
                f"Total Energy: {total_energy:.6f} mWh\n"
            ),
            self.power_text.see(tk.END)
        ))
        
    def run(self):
        threading.Thread(target=self.process_data, daemon=True).start()
        self.root.mainloop()

if __name__ == "__main__":
    root = tk.Tk()
    app = ESP32GUI(root)
    app.run()