#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEServer.h>
#include <Preferences.h>
#include <Wire.h>
#include <Adafruit_INA228.h>
#include <time.h>

// BLE UUIDs
#define SERVICE_UUID "12345678-1234-1234-1234-1234567890ab"
#define CHARACTERISTIC_UUID "87654321-4321-4321-4321-ba0987654321"

// BLE objects
BLEServer* pServer = nullptr;
BLEService* pService = nullptr;
BLECharacteristic* pCharacteristic = nullptr;

// INA228
Adafruit_INA228 ina228 = Adafruit_INA228();
bool ina228Available = false;

// Logging (FIFO in NVS)
Preferences prefs;
const int LOG_SIZE = 100;
int logIndex = 0;

// Configurable parameters
int sampleRate = 10;     // Hz
int duration = 30;       // seconds

// CSV data buffer
String csvData;

// Store diagnostic log entry
void logMessage(const String& msg) {
  String key = "log" + String(logIndex % LOG_SIZE);
  prefs.putString(key.c_str(), msg);
  logIndex++;
}

// Read all logs
String dumpLogs() {
  String logs = "";
  for (int i = 0; i < LOG_SIZE; i++) {
    String key = "log" + String(i);
    String entry = prefs.getString(key.c_str(), "");
    if (entry.length() > 0) {
      logs += entry + "\n";
    }
  }
  return logs;
}

// BLE Callbacks
class MyCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* pCharacteristic) {
    String value = pCharacteristic->getValue();
    if (value.length() > 0) {
      Serial.println("Received: " + value);
      logMessage("BLE RX: " + value);

      if (value == "ping") {
        String response = "pong";
        pCharacteristic->setValue(response.c_str());
        pCharacteristic->notify();
      }
      else if (value.startsWith("read_ina")) {
        // Start CSV streaming
        csvData = "";
        unsigned long startTime = millis();
        int samples = sampleRate * duration;
        for (int i = 0; i < samples; i++) {
          float v = ina228.readBusVoltage();
          float c = ina228.getCurrent_mA();
          float p = ina228.readPower();
          csvData += String(v, 8) + "," + String(c, 8) + "," + String(p, 8) + "\n";
          delay(1000 / sampleRate);
        }
        pCharacteristic->setValue(csvData.c_str());
        pCharacteristic->notify();
      }
      else if (value.startsWith("set_sample_rate")) {
        int comma = value.indexOf(',');
        if (comma > 0) {
          sampleRate = value.substring(comma + 1).toInt();
          logMessage("Sample rate set to: " + String(sampleRate));
          pCharacteristic->setValue("Sample rate updated.");
          pCharacteristic->notify();
        }
      }
      else if (value.startsWith("set_duration")) {
        int comma = value.indexOf(',');
        if (comma > 0) {
          duration = value.substring(comma + 1).toInt();
          logMessage("Duration set to: " + String(duration));
          pCharacteristic->setValue("Duration updated.");
          pCharacteristic->notify();
        }
      }
      else if (value.startsWith("set_time")) {
        int comma = value.indexOf(',');
        if (comma > 0) {
          String timeStr = value.substring(comma + 1);
          struct tm tmTime;
          memset(&tmTime, 0, sizeof(tmTime));
          if (sscanf(timeStr.c_str(), "%d-%d-%d %d:%d:%d",
                     &tmTime.tm_year, &tmTime.tm_mon, &tmTime.tm_mday,
                     &tmTime.tm_hour, &tmTime.tm_min, &tmTime.tm_sec) == 6) {
            tmTime.tm_year -= 1900;
            tmTime.tm_mon -= 1;
            time_t t = mktime(&tmTime);
            struct timeval now = { .tv_sec = t, .tv_usec = 0 };
            settimeofday(&now, nullptr);
            logMessage("Time updated via BLE.");
            pCharacteristic->setValue("Time updated.");
            pCharacteristic->notify();
          }
        }
      }
      else if (value == "dump_logs") {
        String logs = dumpLogs();
        pCharacteristic->setValue(logs.c_str());
        pCharacteristic->notify();
      }
    }
  }
};

void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);

  prefs.begin("diagnostics", false);
  logIndex = prefs.getInt("logIndex", 0);

  logMessage("Startup log: ESP32 booted.");

  if (!ina228.begin()) {
    Serial.println("INA228 not found.");
    ina228Available = false;
  } else {
    ina228.setShunt(0.015, 10.0);
    ina228Available = true;
    logMessage("INA228 initialized.");
  }

  BLEDevice::init("ESP32_BLE_Server");
  pServer = BLEDevice::createServer();
  pService = pServer->createService(SERVICE_UUID);
  pCharacteristic = pService->createCharacteristic(
                      CHARACTERISTIC_UUID,
                      BLECharacteristic::PROPERTY_READ |
                      BLECharacteristic::PROPERTY_WRITE |
                      BLECharacteristic::PROPERTY_NOTIFY
                    );

  pCharacteristic->setCallbacks(new MyCallbacks());
  pCharacteristic->setValue("Ready");
  pService->start();

  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->start();

  Serial.println("BLE service started.");
}

void loop() {
  // BLE handled in callbacks
}
