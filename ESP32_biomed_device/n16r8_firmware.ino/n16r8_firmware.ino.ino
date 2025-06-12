#include <Arduino.h>
#include <FS.h>
#include <SPIFFS.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// Constants
#define DELAY_MS 5000        // Delay between compression and transmission (5s)
#define CHUNK_SIZE 20        // BLE chunk size for data transmission
#define SYNC_PIN 6           // GPIO pin to signal CP2102 for power logging
#define BUFFER_SIZE 512      // Buffer size for file operations
#define MAX_HUFFMAN_NODES 512 // Max nodes for Huffman tree

// BLE UUIDs
#define SERVICE_UUID "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define COMMAND_UUID "beb5483e-36e1-4688-b7f5-ea07361b26a8"
#define DATA_UUID    "6e400002-b5a3-f393-e0a9-e50e24dcca9e"

// Precomputed weights for autoencoder and PCA-linear
const float AUTOENCODER_W[2] = {0.7071, 0.7071}; // Example weights
const float PCA_W[2] = {0.8, 0.6};               // Example weights
const float AUTOENCODER_B = 0.0;                 // Bias for autoencoder
const float PCA_B = 0.0;                         // Bias for PCA-linear

// BLE global variables
BLEServer *pServer = NULL;
BLECharacteristic *pCommandChar = NULL;
BLECharacteristic *pDataChar = NULL;
bool deviceConnected = false;
bool startReceived = false;
String mode = "SINGLE";
String algorithm = "AUTOENCODER";
String input_file = "/ppg_1.csv";
int repeatCount = 1;

// Huffman Node structure
struct HuffmanNode {
  uint8_t symbol;
  uint32_t freq;
  struct HuffmanNode *left, *right;
};

// BLE Server Callbacks
class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *pServer) { deviceConnected = true; }
  void onDisconnect(BLEServer *pServer) {
    deviceConnected = false;
    BLEDevice::startAdvertising();
  }
};

// BLE Command Callbacks
class CommandCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *pCharacteristic) {
    const uint8_t* data = pCharacteristic->getData();
    size_t length = pCharacteristic->getLength();
    String command = "";
    for (size_t i = 0; i < length; i++) {
      command += (char)data[i];
    }
    if (command.startsWith("SINGLE:")) {
      mode = "SINGLE";
      int colon1 = command.indexOf(':');
      int colon2 = command.indexOf(':', colon1 + 1);
      input_file = "/" + command.substring(colon1 + 1, colon2);
      algorithm = command.substring(colon2 + 1);
      repeatCount = 1;
      startReceived = true;
    } else if (command.startsWith("REPEAT:")) {
      mode = "REPEAT";
      int colon1 = command.indexOf(':');
      int colon2 = command.indexOf(':', colon1 + 1);
      int colon3 = command.indexOf(':', colon2 + 1);
      repeatCount = command.substring(colon1 + 1, colon2).toInt();
      input_file = "/" + command.substring(colon2 + 1, colon3);
      algorithm = command.substring(colon3 + 1);
      if (repeatCount < 1 || repeatCount > 5) repeatCount = 1;
      startReceived = true;
    }
  }
};

// Setup function
void setup() {
  pinMode(SYNC_PIN, OUTPUT);
  digitalWrite(SYNC_PIN, LOW);
  Serial.begin(115200);
  
  if (!SPIFFS.begin(true)) {
    Serial.println("SPIFFS mount failed");
    return;
  }
  
  BLEDevice::init("ESP32_S3_PPG");
  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new ServerCallbacks());
  BLEService *pService = pServer->createService(SERVICE_UUID);
  
  pCommandChar = pService->createCharacteristic(
    COMMAND_UUID,
    BLECharacteristic::PROPERTY_WRITE
  );
  pCommandChar->setCallbacks(new CommandCallbacks());
  
  pDataChar = pService->createCharacteristic(
    DATA_UUID,
    BLECharacteristic::PROPERTY_NOTIFY
  );
  pDataChar->addDescriptor(new BLE2902());
  
  pService->start();
  BLEDevice::startAdvertising();
  
  listSPIFFS();
}

// List SPIFFS files
void listSPIFFS() {
  File root = SPIFFS.open("/");
  File file = root.openNextFile();
  while (file) {
    String msg = "File: " + String(file.name()) + ", Size: " + String(file.size());
    notifyBLE(msg);
    Serial.println(msg);
    file = root.openNextFile();
  }
}

// Main loop
void loop() {
  if (deviceConnected && startReceived) {
    String output_file = "/compressed_" + input_file.substring(1);
    
    // Compression phase
    for (int i = 0; i < repeatCount; i++) {
      notifyBLE("COMPRESSION_START:" + String(i + 1));
      digitalWrite(SYNC_PIN, HIGH);
      delay(10);
      if (algorithm == "AUTOENCODER") {
        compressAutoencoder(input_file, output_file);
      } else if (algorithm == "PCA") {
        compressPCA(input_file, output_file);
      } else if (algorithm == "RLE") {
        compressRLE(input_file, output_file);
      } else if (algorithm == "HUFFMAN") {
        compressHuffman(input_file, output_file);
      }
      digitalWrite(SYNC_PIN, LOW);
      notifyBLE("COMPRESSION_END:" + String(i + 1));
      if (i < repeatCount - 1) delay(100);
    }
    
    // Wait 5 seconds
    notifyBLE("Waiting 5 seconds...");
    delay(DELAY_MS);
    
    // Transmission phase
    notifyBLE("TRANSMISSION_START:1");
    digitalWrite(SYNC_PIN, HIGH);
    delay(10);
    transmitFile(output_file, 1);
    digitalWrite(SYNC_PIN, LOW);
    notifyBLE("TRANSMISSION_END:1");
    
    notifyBLE("ALL_DONE");
    startReceived = false;
  }
  delay(10);
}

// Autoencoder Compression
void compressAutoencoder(String input_file, String output_file) {
  File inputFile = SPIFFS.open(input_file, "r");
  File outputFile = SPIFFS.open(output_file, "w");
  if (!inputFile || !outputFile) {
    notifyBLE("File error: " + input_file);
    return;
  }
  
  char buffer[BUFFER_SIZE];
  uint8_t out_buffer[BUFFER_SIZE];
  int out_pos = 0;
  
  out_buffer[out_pos++] = 0x01; // Algorithm ID for autoencoder
  
  while (inputFile.available()) {
    size_t len = inputFile.readBytesUntil('\n', buffer, BUFFER_SIZE - 1);
    buffer[len] = '\0';
    
    char *token = strtok(buffer, ",");
    float data[2] = {0, 0};
    for (int i = 0; i < 2 && token; i++) {
      data[i] = atof(token);
      token = strtok(NULL, ",");
    }
    
    float z = data[0] * AUTOENCODER_W[0] + data[1] * AUTOENCODER_W[1] + AUTOENCODER_B;
    
    if (out_pos + 4 > BUFFER_SIZE) {
      outputFile.write(out_buffer, out_pos);
      out_pos = 0;
    }
    memcpy(&out_buffer[out_pos], &z, 4);
    out_pos += 4;
  }
  
  if (out_pos > 0) {
    outputFile.write(out_buffer, out_pos);
  }
  
  inputFile.close();
  outputFile.close();
}

// PCA-Linear Compression
void compressPCA(String input_file, String output_file) {
  File inputFile = SPIFFS.open(input_file, "r");
  File outputFile = SPIFFS.open(output_file, "w");
  if (!inputFile || !outputFile) {
    notifyBLE("File error: " + input_file);
    return;
  }
  
  char buffer[BUFFER_SIZE];
  uint8_t out_buffer[BUFFER_SIZE];
  int out_pos = 0;
  
  out_buffer[out_pos++] = 0x02; // Algorithm ID for PCA
  
  while (inputFile.available()) {
    size_t len = inputFile.readBytesUntil('\n', buffer, BUFFER_SIZE - 1);
    buffer[len] = '\0';
    
    char *token = strtok(buffer, ",");
    float data[2] = {0, 0};
    for (int i = 0; i < 2 && token; i++) {
      data[i] = atof(token);
      token = strtok(NULL, ",");
    }
    
    float z = data[0] * PCA_W[0] + data[1] * PCA_W[1] + PCA_B;
    
    if (out_pos + 4 > BUFFER_SIZE) {
      outputFile.write(out_buffer, out_pos);
      out_pos = 0;
    }
    memcpy(&out_buffer[out_pos], &z, 4);
    out_pos += 4;
  }
  
  if (out_pos > 0) {
    outputFile.write(out_buffer, out_pos);
  }
  
  inputFile.close();
  outputFile.close();
}

// RLE Compression
void compressRLE(String input_file, String output_file) {
  File inputFile = SPIFFS.open(input_file, "r");
  File outputFile = SPIFFS.open(output_file, "w");
  if (!inputFile || !outputFile) {
    notifyBLE("File error: " + input_file);
    return;
  }
  
  uint8_t buffer[BUFFER_SIZE];
  uint8_t out_buffer[BUFFER_SIZE];
  int out_pos = 0;
  
  out_buffer[out_pos++] = 0x03; // Algorithm ID for RLE
  
  uint8_t last_byte = 0;
  uint8_t count = 0;
  bool first = true;
  
  while (inputFile.available()) {
    size_t len = inputFile.read(buffer, BUFFER_SIZE);
    for (size_t i = 0; i < len; i++) {
      if (first) {
        last_byte = buffer[i];
        count = 1;
        first = false;
        continue;
      }
      
      if (buffer[i] == last_byte && count < 255) {
        count++;
      } else {
        if (out_pos + 2 > BUFFER_SIZE) {
          outputFile.write(out_buffer, out_pos);
          out_pos = 0;
        }
        out_buffer[out_pos++] = last_byte;
        out_buffer[out_pos++] = count;
        last_byte = buffer[i];
        count = 1;
      }
    }
  }
  
  if (count > 0) {
    if (out_pos + 2 > BUFFER_SIZE) {
      outputFile.write(out_buffer, out_pos);
      out_pos = 0;
    }
    out_buffer[out_pos++] = last_byte;
    out_buffer[out_pos++] = count;
  }
  
  if (out_pos > 0) {
    outputFile.write(out_buffer, out_pos);
  }
  
  inputFile.close();
  outputFile.close();
}

// Huffman Compression
void compressHuffman(String input_file, String output_file) {
  File inputFile = SPIFFS.open(input_file, "r");
  File outputFile = SPIFFS.open(output_file, "w");
  if (!inputFile || !outputFile) {
    notifyBLE("File error: " + input_file);
    return;
  }
  
  // Step 1: Build frequency table
  uint32_t freq[256] = {0};
  uint8_t buffer[BUFFER_SIZE];
  while (inputFile.available()) {
    size_t len = inputFile.read(buffer, BUFFER_SIZE);
    for (size_t i = 0; i < len; i++) {
      freq[buffer[i]]++;
    }
  }
  
  // Step 2: Build Huffman tree
  HuffmanNode *nodes[MAX_HUFFMAN_NODES];
  int node_count = 0;
  for (int i = 0; i < 256; i++) {
    if (freq[i] > 0) {
      nodes[node_count] = new HuffmanNode{(uint8_t)i, freq[i], NULL, NULL};
      node_count++;
    }
  }
  
  while (node_count > 1) {
    int min1 = 0, min2 = 1;
    if (nodes[min2]->freq < nodes[min1]->freq) {
      int temp = min1;
      min1 = min2;
      min2 = temp;
    }
    for (int i = 2; i < node_count; i++) {
      if (nodes[i]->freq < nodes[min1]->freq) {
        min2 = min1;
        min1 = i;
      } else if (nodes[i]->freq < nodes[min2]->freq) {
        min2 = i;
      }
    }
    
    HuffmanNode *parent = new HuffmanNode{0, nodes[min1]->freq + nodes[min2]->freq, nodes[min1], nodes[min2]};
    nodes[min1] = parent;
    nodes[min2] = nodes[node_count - 1];
    node_count--;
  }
  
  HuffmanNode *root = nodes[0];
  
  // Step 3: Generate Huffman codes
  uint8_t codes[256][32];
  uint8_t code_lengths[256] = {0};
  uint8_t temp_code[32];
  generateCodes(root, temp_code, 0, codes, code_lengths);
  
  // Step 4: Write header (algorithm ID + frequency table)
  uint8_t out_buffer[BUFFER_SIZE];
  int out_pos = 0;
  out_buffer[out_pos++] = 0x04; // Algorithm ID for Huffman
  for (int i = 0; i < 256; i++) {
    if (out_pos + 4 > BUFFER_SIZE) {
      outputFile.write(out_buffer, out_pos);
      out_pos = 0;
    }
    memcpy(&out_buffer[out_pos], &freq[i], 4);
    out_pos += 4;
  }
  
  // Step 5: Encode data
  inputFile = SPIFFS.open(input_file, "r");
  uint32_t bit_buffer = 0;
  int bit_count = 0;
  
  while (inputFile.available()) {
    size_t len = inputFile.read(buffer, BUFFER_SIZE);
    for (size_t i = 0; i < len; i++) {
      uint8_t symbol = buffer[i];
      for (int j = 0; j < code_lengths[symbol]; j++) {
        bit_buffer = (bit_buffer << 1) | codes[symbol][j];
        bit_count++;
        if (bit_count == 8) {
          if (out_pos >= BUFFER_SIZE) {
            outputFile.write(out_buffer, out_pos);
            out_pos = 0;
          }
          out_buffer[out_pos++] = (uint8_t)(bit_buffer & 0xFF);
          bit_buffer = 0;
          bit_count = 0;
        }
      }
    }
  }
  
  if (bit_count > 0) {
    bit_buffer <<= (8 - bit_count);
    if (out_pos >= BUFFER_SIZE) {
      outputFile.write(out_buffer, out_pos);
      out_pos = 0;
    }
    out_buffer[out_pos++] = (uint8_t)(bit_buffer & 0xFF);
  }
  
  if (out_pos > 0) {
    outputFile.write(out_buffer, out_pos);
  }
  
  inputFile.close();
  outputFile.close();
  
  freeTree(root);
}

// Helper function to generate Huffman codes
void generateCodes(HuffmanNode *node, uint8_t *code, int depth, uint8_t codes[256][32], uint8_t *lengths) {
  if (!node->left && !node->right) {
    lengths[node->symbol] = depth;
    for (int i = 0; i < depth; i++) {
      codes[node->symbol][i] = code[i];
    }
    return;
  }
  
  if (node->left) {
    code[depth] = 0;
    generateCodes(node->left, code, depth + 1, codes, lengths);
  }
  if (node->right) {
    code[depth] = 1;
    generateCodes(node->right, code, depth + 1, codes, lengths);
  }
}

// Helper function to free Huffman tree memory
void freeTree(HuffmanNode *node) {
  if (!node) return;
  freeTree(node->left);
  freeTree(node->right);
  delete node;
}

// Transmit file over BLE
void transmitFile(String filename, int id) {
  File file = SPIFFS.open(filename, "r");
  if (!file) {
    notifyBLE("Failed to open " + filename);
    return;
  }
  
  size_t file_size = file.size();
  notifyBLE("FILE_START:" + String(id) + ":" + filename + ":" + String(file_size));
  
  uint8_t buffer[CHUNK_SIZE];
  while (file.available()) {
    size_t len = file.read(buffer, CHUNK_SIZE);
    pDataChar->setValue(buffer, len);
    pDataChar->notify();
    delay(2);
  }
  
  notifyBLE("FILE_END");
  file.close();
}

// Send notification over BLE
void notifyBLE(String message) {
  if (deviceConnected) {
    pDataChar->setValue(message.c_str());
    pDataChar->notify();
    delay(2);
  }
}