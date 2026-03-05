#include <Wire.h>
#include "MAX30105.h"
#include <WiFi.h>
#include <ArduinoOSCWiFi.h>
#include <WebServer.h>
#include <math.h>

// ====== AP settings ======
const char* AP_SSID     = "ESP32_AP";
const char* AP_PASSWORD = "12345678";

// ====== OSC settings ======
const uint16_t UNREAL_PORT = 9000;   // Unreal Engine OSC server
const uint16_t PYTHON_PORT = 9001;   // Python Flask OSC server
const char* OSC_PATH = "/sensor/value";

// ====== HTTP Server settings ======
WebServer server(80);

// ====== Timing ======
const uint32_t SEND_INTERVAL_MS = 20;   // 50 Hz

// ====== Heartbeat tuning ======
#define IR_THRESHOLD        50000   // finger detection threshold
#define MIN_BEAT_INTERVAL  300     // ms (200 BPM max)
#define MAX_BEAT_INTERVAL  2000    // ms (30 BPM min)

#define AVG_ALPHA           0.95    // DC removal
#define BPM_SMOOTH_ALPHA    0.9    // BPM smoothing (higher = smoother)

// ====== Globals ======
IPAddress broadcastIP;
String ipStr;
uint32_t lastSendMs = 0;

MAX30105 sensor;

// Heartbeat state
bool fingerPresent = false;
bool prevFingerPresent = false;

float irAvg = 0;
bool beatNow = false;
bool beatPrev = false;

uint32_t lastBeatMs = 0;

float bpmRaw = 0;
float bpmSmooth = 0;

// ====== Compute broadcast address ======
IPAddress computeBroadcast(IPAddress ip, IPAddress mask) {
  IPAddress b;
  for (int i = 0; i < 4; i++) b[i] = ip[i] | ~mask[i];
  return b;
}

// ====== HTTP Handlers ======
void handleMessage() {
  String msg1 = server.hasArg("msg1") ? server.arg("msg1") : "";
  String msg2 = server.hasArg("msg2") ? server.arg("msg2") : "";
  String msg3 = server.hasArg("msg3") ? server.arg("msg3") : "";

  Serial.println();
  Serial.println("==============================");
  Serial.print("INPUT 1: "); Serial.println(msg1);
  Serial.print("INPUT 2: "); Serial.println(msg2);
  Serial.print("INPUT 3: "); Serial.println(msg3);
  Serial.println("==============================");

  OscWiFi.send(ipStr, UNREAL_PORT, "/text/input",
               msg1.c_str(), msg2.c_str(), msg3.c_str());
  server.send(200, "text/plain", "{\"status\": \"ok\"}");
}

// ====== Heartbeat processing ======
void processHeartbeat(long irValue) {
  fingerPresent = (irValue > IR_THRESHOLD);

  // Finger removed → reset
  if (!fingerPresent) {
    bpmRaw = 0;
    bpmSmooth = 0;
    irAvg = 0;
    lastBeatMs = 0;
    return;
  }

  // DC removal (running average)
  if (irAvg == 0) irAvg = irValue;
  irAvg = AVG_ALPHA * irAvg + (1.0 - AVG_ALPHA) * irValue;

  float signal = irValue - irAvg;

  // Rising edge detection
  beatNow = (signal > 0);

  if (beatNow && !beatPrev) {
    uint32_t now = millis();
    uint32_t interval = now - lastBeatMs;

    if (interval > MIN_BEAT_INTERVAL && interval < MAX_BEAT_INTERVAL) {
      bpmRaw = 60000.0 / interval;

      // Smooth BPM (EMA)
      if (bpmSmooth == 0)
        bpmSmooth = bpmRaw;
      else
        bpmSmooth = BPM_SMOOTH_ALPHA * bpmSmooth +
                    (1.0 - BPM_SMOOTH_ALPHA) * bpmRaw;
    }

    lastBeatMs = now;
  }

  beatPrev = beatNow;
}

void unrealValue(OscMessage& msg) {
  int value = msg.arg<int>(0);

  Serial.println("===== VALUE FROM UNREAL =====");
  Serial.print("Value: ");
  Serial.println(value);

  // Forward to Python
  OscWiFi.send(ipStr, PYTHON_PORT, "/unreal/value", value);
}

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);
  delay(500);

  if (!sensor.begin(Wire, I2C_SPEED_STANDARD)) {
    Serial.println("MAX30102 not found!");
    while (1);
  }

  Serial.println("MAX30102 found!");

  // Sensor configuration
  sensor.setup();  
  sensor.setPulseAmplitudeRed(0x1F);
  sensor.setPulseAmplitudeIR(0x1F);
  sensor.setPulseAmplitudeGreen(0);

  // Start Wi-Fi AP
  if (!WiFi.softAP(AP_SSID, AP_PASSWORD)) {
    Serial.println("Failed to start AP");
    while (1);
  }

  // Subscribe to OSC messages from Unreal Engine
  OscWiFi.subscribe(9002, "/unreal/value", unrealValue);

  // Start HTTP server for receiving trigger messages
  server.on("/message", handleMessage);
  server.begin();
  Serial.println("HTTP Server started on port 80");

  IPAddress apIP = WiFi.softAPIP();
  IPAddress apMask = WiFi.softAPSubnetMask();
  broadcastIP = computeBroadcast(apIP, apMask);
  ipStr = broadcastIP.toString();

  Serial.println();
  Serial.println("=== ESP32 MAX30102 OSC ===");
  Serial.print("AP IP: "); Serial.println(apIP);
  Serial.print("Broadcast: "); Serial.println(ipStr);
  Serial.print("Unreal OSC Port: "); Serial.println(UNREAL_PORT);
  Serial.print("Python OSC Port: "); Serial.println(PYTHON_PORT);
  Serial.println("IR\tRED\tBPM\tFINGER");
}

void loop() {
  server.handleClient();
  uint32_t now = millis();

  if (now - lastSendMs >= SEND_INTERVAL_MS) {
  // Handle HTTP requests
  
    lastSendMs = now;

    long irValue = sensor.getIR();
    long redValue = sensor.getRed();

    processHeartbeat(irValue);

    // Send OSC to Unreal Engine (port 9000)
    OscWiFi.send(ipStr, UNREAL_PORT, OSC_PATH, irValue, redValue, bpmSmooth, fingerPresent ? 1 : 0);
    // Send OSC to Python Flask (port 9001)
    OscWiFi.send(ipStr, PYTHON_PORT, OSC_PATH, irValue, redValue, bpmSmooth, fingerPresent ? 1 : 0);

    // Serial Plotter
    Serial.print(irValue);
    Serial.print("\t");
    Serial.print(redValue);
    Serial.print("\t");
    Serial.print(bpmSmooth);
    Serial.print("\t");
    Serial.println(fingerPresent ? 1 : 0);
  }

  OscWiFi.update();
}