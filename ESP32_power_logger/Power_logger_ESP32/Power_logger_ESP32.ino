#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEServer.h>
#include <Wire.h>
#include <Adafruit_INA228.h>

// BLE Service and Characteristic UUIDs
#define SERVICE_UUID "12345678-1234-1234-1234-1234567890ab"
#define CHARACTERISTIC_UUID "87654321-4321-4321-4321-ba0987654321"

// BLE objects
BLEServer* pServer = nullptr;
BLEService* pService = nullptr;
BLECharacteristic* pCharacteristic = nullptr;

// INA228 object
Adafruit_INA228 ina228 = Adafruit_INA228();
bool ina228Available = false;
// Counter
int pingCounter = 0;

// Read INA228 measurements
String readINA228() {
  float busVoltage = ina228.readBusVoltage();    // in Volts
  float current = ina228.getCurrent_mA();          // in milliAmps
  float power = ina228.readPower();              // in Watts
  String csvData = String(busVoltage, 8) + "," +
                   String(current, 8) + "," +
                   String(power, 8);
  return csvData;
}

// BLE callbacks
class MyCallbacks: public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *pCharacteristic) {
    String value = pCharacteristic->getValue();
    if (value.length() > 0) {
      if (Serial) {
        Serial.print("Received: ");
        Serial.println(value.c_str());
      }

      if (value == "ping") {
        float tempC = temperatureRead();  // ESP32 internal temperature
        pingCounter++;
        String response = "Hello World! Temp: " + String(tempC, 2) +
                          " C, Count: " + String(pingCounter) +
                          ", Time(ms): " + String(millis());
        pCharacteristic->setValue(response.c_str());
        pCharacteristic->notify();
      } 
      else if (value == "read_ina") {
        String csvData = readINA228();
        pCharacteristic->setValue(csvData.c_str());
        pCharacteristic->notify();
      }
    }
  }
};

void setup() {
  if (Serial) Serial.begin(115200);
  delay(1000);
  if (Serial) {
    Serial.println("Starting BLE work!");
  }

  // Initialize INA228
  if (!ina228.begin()) {
    Serial.println("⚠️ INA228 not found. Continuing without INA228 support.");
    ina228Available = false;
  } else {
    Serial.println("INA228 Initialized!");
    ina228.setShunt(0.015, 10.0);
    ina228Available = true;
  }

  // Initialize BLE
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

  Serial.println("BLE Service started, waiting for client connection...");
}

void loop() {
  // Nothing to do here, BLE callbacks handle everything
}
