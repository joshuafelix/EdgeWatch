/*
  EdgeWatch — Simulated IoT Fleet Firmware (Wokwi / ESP32)
  ----------------------------------------------------------
  A single ESP32 simulates a small FLEET of edge devices in software.
  Each virtual node has its own behavior profile:
    - NORMAL      : stable readings with small random noise
    - DEGRADING_V : battery voltage slowly drains toward failure
    - DEGRADING_T : temperature slowly climbs toward overheating

  Every READING_INTERVAL_MS, each node produces a telemetry reading and:
    1. Prints it as JSON over Serial (easy to pipe into a local ingestion
  script)
    2. Optionally POSTs it to ThingSpeak (one field per metric)

  This lets you demo a "fleet" live from ONE Wokwi simulation — no need
  to spin up 10 separate boards for the hackathon demo.
*/

#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>

// ---------- CONFIG ----------
const char *WIFI_SSID = "Wokwi-GUEST"; // Wokwi's built-in simulated network
const char *WIFI_PASSWORD = "";

// Set to true once you have a ThingSpeak Write API Key for testing.
// Leave false to just watch JSON in the Serial Monitor (fine for early dev).
const bool SEND_TO_THINGSPEAK = true;
const char *THINGSPEAK_API_KEY = "LIV8CB8MI7604IVH";

const unsigned long READING_INTERVAL_MS =
    5000; // how often the whole fleet reports
const int NUM_NODES = 6;

// ---------- NODE MODEL ----------
enum Behavior { NORMAL, DEGRADING_VOLTAGE, DEGRADING_TEMP };

struct Node {
  const char *id;
  Behavior behavior;
  float temperature; // °C
  float voltage;     // V
  float vibration;   // g
  int rssi;          // dBm (signal strength)
  unsigned long uptimeSec;
};

Node fleet[NUM_NODES] = {
    {"node-01", NORMAL, 24.0, 4.10, 0.02, -55, 0},
    {"node-02", NORMAL, 23.5, 4.05, 0.03, -60, 0},
    {"node-03", DEGRADING_VOLTAGE, 24.2, 4.10, 0.02, -58,
     0}, // will "fail" via voltage
    {"node-04", NORMAL, 24.8, 4.08, 0.02, -52, 0},
    {"node-05", DEGRADING_TEMP, 25.0, 4.12, 0.04, -63,
     0}, // will "fail" via overheating
    {"node-06", NORMAL, 23.9, 4.11, 0.02, -57, 0},
};

unsigned long lastReadingTime = 0;

// ---------- HELPERS ----------
float jitter(float amount) {
  // random noise between -amount and +amount
  return ((float)random(-1000, 1000) / 1000.0) * amount;
}

void updateNode(Node &n) {
  n.uptimeSec += READING_INTERVAL_MS / 1000;

  switch (n.behavior) {
  case NORMAL:
    n.temperature += jitter(0.3);
    n.voltage += jitter(0.01);
    n.vibration = 0.02 + jitter(0.01);
    break;

  case DEGRADING_VOLTAGE:
    // slow steady drain, plus small noise — mimics a dying battery
    n.voltage -= 0.015 + jitter(0.005);
    n.temperature += jitter(0.3);
    n.vibration = 0.02 + jitter(0.01);
    break;

  case DEGRADING_TEMP:
    // slow steady climb — mimics a device overheating / cooling failure
    n.temperature += 0.08 + jitter(0.05);
    n.voltage += jitter(0.01);
    n.vibration = 0.03 + jitter(0.02);
    break;
  }

  // signal strength wanders a little regardless of behavior
  n.rssi += random(-2, 3);
  if (n.rssi > -40)
    n.rssi = -40;
  if (n.rssi < -90)
    n.rssi = -90;

  // clamp voltage so it doesn't go negative/unrealistic
  if (n.voltage < 3.0)
    n.voltage = 3.0;
}

void sendToThingSpeak(Node &n) {
  if (!SEND_TO_THINGSPEAK)
    return;
  if (WiFi.status() != WL_CONNECTED)
    return;

  HTTPClient http;
  String url = String("http://api.thingspeak.com/update?api_key=") +
               THINGSPEAK_API_KEY + "&field1=" + n.temperature +
               "&field2=" + n.voltage + "&field3=" + n.vibration +
               "&field4=" + n.rssi;
  http.begin(url);
  int code = http.GET();
  http.end();
  // Note: for a real multi-node fleet you'd use separate ThingSpeak channels
  // per node, or a different backend (MQTT topic per node) — see README.
}

void printReadingJSON(Node &n) {
  StaticJsonDocument<256> doc;
  doc["node_id"] = n.id;
  doc["behavior"] = (n.behavior == NORMAL)              ? "normal"
                    : (n.behavior == DEGRADING_VOLTAGE) ? "degrading_voltage"
                                                        : "degrading_temp";
  doc["temperature_c"] = round(n.temperature * 100) / 100.0;
  doc["voltage_v"] = round(n.voltage * 1000) / 1000.0;
  doc["vibration_g"] = round(n.vibration * 1000) / 1000.0;
  doc["rssi_dbm"] = n.rssi;
  doc["uptime_sec"] = n.uptimeSec;

  serializeJson(doc, Serial);
  Serial.println();
}

// ---------- SETUP / LOOP ----------
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("EdgeWatch fleet simulation booting...");

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 8000) {
    delay(250);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected: " + WiFi.localIP().toString());
  } else {
    Serial.println("\nWiFi not connected — continuing in Serial-only mode.");
  }

  randomSeed(analogRead(0));
}

void loop() {
  if (millis() - lastReadingTime >= READING_INTERVAL_MS) {
    lastReadingTime = millis();

    for (int i = 0; i < NUM_NODES; i++) {
      updateNode(fleet[i]);
      printReadingJSON(fleet[i]);
      sendToThingSpeak(fleet[i]);
    }
    Serial.println("---- fleet cycle complete ----");
  }
}
