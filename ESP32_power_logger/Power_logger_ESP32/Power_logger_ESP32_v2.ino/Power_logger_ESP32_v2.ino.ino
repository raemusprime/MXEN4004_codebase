#include <Arduino.h>
#include <Wire.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// Constants
#define INA228_ADDR 0x40
#define SYNC_PIN 4
#define SDA_PIN 21
#define SCL_PIN 22
#define SAMPLE_RATE_HZ 100
#define SAMPLE_INTERVAL_US (1000000 / SAMPLE_RATE_HZ)

// BLE UUIDs
#define SERVICE_UUID "5fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define DATA_UUID "7e400002-b5a3-f393-e0a9-e50e24dcca9e"

// INA228 Registers
#define INA228_CONFIG 0x00
#define INA228_VBUS 0x05
#define INA228_CURRENT 0x07
#define INA228_ENERGY 0x09

// Global variables
BLEServer *pServer = NULL;
BLECharacteristic *pDataChar = NULL;
bool deviceConnected = false;
bool loggingActive = false;
unsigned long start_time = 0;
float start_energy = 0;
String current_op_type = "";
int current_id = 0;
unsigned long last_sample = 0;

// PowerLog and WaveformSample structs
struct PowerLog {
  int id;
  String operation;
  float voltage;
  float current;
  float energy;
  unsigned long duration;
};

struct WaveformSample {
  unsigned long timestamp;
  float voltage;
  float current;
};

PowerLog power_logs[6]; // Max 5 compressions + 1 transmission
WaveformSample waveform_data[6][100];
int waveform_counts[6] = {0};
int current_op = 0;

// BLE Server Callbacks
class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *pServer) { deviceConnected = true; }
  void onDisconnect(BLEServer *pServer) {
    deviceConnected = false;
    BLEDevice::startAdvertising();
  }
};

// Setup function
void setup() {
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);
  pinMode(SYNC_PIN, INPUT);
  
  configureINA228();
  
  BLEDevice::init("ESP32_PPG_POWER");
  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new ServerCallbacks());
  BLEService *pService = pServer->createService(SERVICE_UUID);
  
  pDataChar = pService->createCharacteristic(
    DATA_UUID,
    BLECharacteristic::PROPERTY_NOTIFY
  );
  pDataChar->addDescriptor(new BLE2902());
  
  pService->start();
  BLEDevice::startAdvertising();
}

// Configure INA228
void configureINA228() {
  Wire.beginTransmission(INA228_ADDR);
  Wire.write(INA228_CONFIG);
  Wire.write(0x80); // Reset
  Wire.write(0x00);
  Wire.write(0x04); // Continuous VBUS+Current, 50us
  Wire.endTransmission();
}

// Read INA228 data
void readINA228(float &voltage, float &current) {
  Wire.beginTransmission(INA228_ADDR);
  Wire.write(INA228_VBUS);
  Wire.endTransmission();
  Wire.requestFrom(INA228_ADDR, 4);
  int32_t vbus_raw = (Wire.read() << 24) | (Wire.read() << 16) | (Wire.read() << 8) | Wire.read();
  voltage = vbus_raw * (1.25e-6) * 1000;
  
  Wire.beginTransmission(INA228_ADDR);
  Wire.write(INA228_CURRENT);
  Wire.endTransmission();
  Wire.requestFrom(INA228_ADDR, 4);
  int32_t current_raw = (Wire.read() << 24) | (Wire.read() << 16) | (Wire.read() << 8) | Wire.read();
  current = current_raw * (1e-3) / 0.1;
}

float readINA228Energy() {
  Wire.beginTransmission(INA228_ADDR);
  Wire.write(INA228_ENERGY);
  Wire.endTransmission();
  Wire.requestFrom(INA228_ADDR, 5);
  uint64_t energy_raw = ((uint64_t)Wire.read() << 32) | ((uint64_t)Wire.read() << 24) | ((uint64_t)Wire.read() << 16) | ((uint64_t)Wire.read() << 8) | Wire.read();
  return energy_raw * (3.125e-14) * 3600 * 1000;
}

// Main loop
void loop() {
  if (digitalRead(SYNC_PIN) == HIGH && !loggingActive && current_op < 6) {
    loggingActive = true;
    start_time = millis();
    start_energy = readINA228Energy();
    waveform_counts[current_op] = 0;
    last_sample = micros();
    notifyBLE("Logging power for " + current_op_type + " " + String(current_id));
  }
  
  if (loggingActive && waveform_counts[current_op] < 100) {
    unsigned long now = micros();
    if (now - last_sample >= SAMPLE_INTERVAL_US) {
      float voltage, current;
      readINA228(voltage, current);
      waveform_data[current_op][waveform_counts[current_op]] = {
        millis() - start_time,
        voltage,
        current
      };
      waveform_counts[current_op]++;
      last_sample = now;
    }
  }
  
  if (digitalRead(SYNC_PIN) == LOW && loggingActive) {
    float end_energy = readINA228Energy();
    float voltage, current;
    readINA228(voltage, current);
    power_logs[current_op] = {
      current_id,
      current_op_type,
      voltage,
      current,
      end_energy - start_energy,
      millis() - start_time
    };
    loggingActive = false;
    current_op++;
  }
  
  // Handle BLE commands or other logic here
  delay(10);
}

// Send notification over BLE
void notifyBLE(String message) {
  if (deviceConnected) {
    pDataChar->setValue(message.c_str());
    pDataChar->notify();
    delay(2);
  }
}