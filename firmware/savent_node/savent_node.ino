// Node SAVENT untuk ESP32 DevKit.
// Pin, koreksi, dan keputusan mengikuti docs/HW-SENSING.md dan docs/FSD-SAVENT.md.
// SIMULATE 1 menjalankan jejak tanpa sensor supaya firmware bisa diuji lewat Serial.
// Isi WIFI_SSID untuk mengirim MQTT. Kosongkan SSID bila hanya Serial.

#include <WiFi.h>
#include <PubSubClient.h>

static const int SIMULATE = 1;
static const char *WIFI_SSID = "";
static const char *WIFI_PASSWORD = "";
static const char *MQTT_HOST = "192.168.0.10";
static const int MQTT_PORT = 1883;
static const char *SITE = "hackathon-demo";
static const char *NODE_ID = "indoor-01";

static const int PIN_SDA = 21;
static const int PIN_SCL = 22;
static const int PIN_CO2_RX = 16;
static const int PIN_CO2_TX = 17;
static const int PIN_PM_RX = 25;
static const int PIN_PM_TX = 26;
static const int PIN_FAN = 27;
static const int PIN_LED = 2;
static const bool FAN_ACTIVE_LOW = true;

static const float P_REF = 1013.25f;
static const float A0 = 223.3233f;
static const float A1 = 0.7671f;
static const float A2 = 4.9048f;
static const float A3 = 0.3334f;

static const unsigned long PERIOD_MS = 30000;
static const float WARMUP_CO2 = 180;
static const float WARMUP_GAS = 300;
static const float WARMUP_PM = 30;
static const float MIN_ON = 180;
static const float MIN_OFF = 120;

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
HardwareSerial Co2Serial(1);
HardwareSerial PmSerial(2);

int mode = 1;
bool demand = false;
bool fanOn = false;
bool forceOff = false;
bool co2Valid = false;
float uptime = 0;
float fanChangedAt = -1.0e9f;
float confirmUntil = -1;
unsigned long seq = 0;
unsigned long lastTick = 0;
float historyT[8];
float historyC[8];
int historyN = 0;
float gasBaseline = -1;
int lastRaw = -1;
float held = 0;
bool brokerUp = false;

static float correctCo2(int raw, float pressure) {
  return raw * P_REF / pressure;
}

static const char *co2Flag(int raw, bool checksumOk, bool pressureOk, float heldS) {
  if (uptime < WARMUP_CO2) return "warming";
  if (raw < 0 || !checksumOk || !pressureOk) return "fault";
  if (heldS >= 900 && (raw == 0 || raw == 400 || raw == 5000)) return "stuck";
  if (raw < 400 || raw > 5000) return "out_of_range";
  return "ok";
}

static bool modelSlope(float now, float co2, float *dco2) {
  float bestMiss = 1.0e9f;
  float past = 0;
  float age = 0;
  bool found = false;
  for (int i = 0; i < historyN; i++) {
    float candidate = now - historyT[i];
    if (candidate < 90) continue;
    float miss = fabsf(candidate - 120.0f);
    if (miss < bestMiss) {
      bestMiss = miss;
      past = historyC[i];
      age = candidate;
      found = true;
    }
  }
  if (!found || age <= 0) return false;
  *dco2 = (co2 - past) / (age / 60.0f);
  return true;
}

static void setFan(bool on) {
  if (on == fanOn) return;
  fanOn = on;
  fanChangedAt = uptime;
  digitalWrite(PIN_FAN, (on ^ FAN_ACTIVE_LOW) ? HIGH : LOW);
  digitalWrite(PIN_LED, on ? HIGH : LOW);
}

static void applyFan() {
  bool want = demand && !forceOff && co2Valid;
  bool target = false;
  if (mode == 0 || mode == 1) {
    target = false;
  } else if (mode == 2) {
    target = want && confirmUntil >= uptime;
  } else if (fanOn && !want) {
    if (forceOff || !co2Valid) target = false;
    else if ((uptime - fanChangedAt) < MIN_ON) target = true;
    else target = false;
  } else if (!fanOn && want && (uptime - fanChangedAt) < MIN_OFF) {
    target = false;
  } else {
    target = want;
  }
  setFan(target);
}

static void remember(float t, float co2) {
  if (historyN < 8) {
    historyT[historyN] = t;
    historyC[historyN] = co2;
    historyN++;
    return;
  }
  for (int i = 1; i < 8; i++) {
    historyT[i - 1] = historyT[i];
    historyC[i - 1] = historyC[i];
  }
  historyT[7] = t;
  historyC[7] = co2;
}

static int readCo2(bool *checksumOk) {
  if (SIMULATE) {
    *checksumOk = true;
    float risen = uptime > WARMUP_CO2 ? (uptime - WARMUP_CO2) / 30.0f * 18.0f : 0;
    return (int)(700 + risen);
  }
  uint8_t cmd[9] = {0xFF, 0x01, 0x86, 0x00, 0x00, 0x00, 0x00, 0x00, 0x79};
  Co2Serial.write(cmd, 9);
  uint8_t buf[9];
  unsigned long start = millis();
  int got = 0;
  while (millis() - start < 200 && got < 9) {
    if (Co2Serial.available()) buf[got++] = Co2Serial.read();
  }
  if (got < 9 || buf[0] != 0xFF || buf[1] != 0x86) {
    *checksumOk = false;
    return -1;
  }
  uint8_t sum = 0;
  for (int i = 1; i < 8; i++) sum += buf[i];
  *checksumOk = buf[8] == (uint8_t)(0xFF - sum + 1);
  return buf[2] * 256 + buf[3];
}

static void readPm(int *pm25, int *pm10, bool *checksumOk) {
  *pm25 = SIMULATE ? 18 : -1;
  *pm10 = SIMULATE ? 24 : -1;
  *checksumOk = SIMULATE;
  if (SIMULATE) return;
  while (PmSerial.available() >= 32) {
    if (PmSerial.read() != 0x42 || PmSerial.peek() != 0x4D) continue;
    uint8_t frame[32];
    frame[0] = 0x42;
    if (PmSerial.readBytes(frame + 1, 31) != 31) return;
    uint16_t sum = 0;
    for (int i = 0; i < 30; i++) sum += frame[i];
    uint16_t expect = frame[30] * 256 + frame[31];
    *checksumOk = sum == expect;
    *pm25 = frame[12] * 256 + frame[13];
    *pm10 = frame[14] * 256 + frame[15];
    return;
  }
}

static void publish(const String &body) {
  Serial.println(body);
  if (!brokerUp) return;
  String topic = String("savent/") + SITE + "/" + NODE_ID + "/telemetry";
  mqtt.publish(topic.c_str(), body.c_str());
}

static void onMqtt(char *topic, byte *payload, unsigned int length) {
  String body;
  for (unsigned int i = 0; i < length; i++) body += (char)payload[i];
  if (body.indexOf("\"source\"") < 0) return;
  if (body.indexOf("force_off_release") >= 0) forceOff = false;
  else if (body.indexOf("force_off") >= 0) forceOff = true;
  else if (body.indexOf("confirm") >= 0) confirmUntil = uptime + 60;
  else if (body.indexOf("set_mode") >= 0) {
    int pos = body.indexOf("\"mode\"");
    if (pos >= 0) {
      int value = body.substring(pos).indexOf(':');
      if (value >= 0) mode = body.substring(pos + value + 1).toInt();
    }
  }
  applyFan();
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_FAN, OUTPUT);
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_FAN, FAN_ACTIVE_LOW ? HIGH : LOW);
  if (!SIMULATE) {
    Co2Serial.begin(9600, SERIAL_8N1, PIN_CO2_RX, PIN_CO2_TX);
    PmSerial.begin(9600, SERIAL_8N1, PIN_PM_RX, PIN_PM_TX);
    uint8_t abcOff[9] = {0xFF, 0x01, 0x79, 0x00, 0x00, 0x00, 0x00, 0x00, 0x86};
    delay(100);
    Co2Serial.write(abcOff, 9);
  }
  if (strlen(WIFI_SSID) > 0) {
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    mqtt.setServer(MQTT_HOST, MQTT_PORT);
    mqtt.setCallback(onMqtt);
  }
  lastTick = millis();
}

void loop() {
  if (strlen(WIFI_SSID) > 0) {
    if (!mqtt.connected() && WiFi.status() == WL_CONNECTED) {
      brokerUp = mqtt.connect(NODE_ID);
      if (brokerUp) {
        String commandTopic = String("savent/") + SITE + "/" + NODE_ID + "/command";
        mqtt.subscribe(commandTopic.c_str());
      }
    } else {
      mqtt.loop();
    }
  }
  if (millis() - lastTick < (SIMULATE ? 1000 : PERIOD_MS)) return;
  lastTick = millis();
  uptime += SIMULATE ? 30 : 30;

  bool co2Sum = false;
  bool pmSum = false;
  int pm25 = 0;
  int pm10 = 0;
  int raw = readCo2(&co2Sum);
  readPm(&pm25, &pm10, &pmSum);
  float tC = 27.4f;
  float rh = 62.0f;
  float pressure = 932.0f;
  float gas = 150000;

  if (raw == lastRaw) held += 30;
  else {
    lastRaw = raw;
    held = 0;
  }
  const char *flag = co2Flag(raw, co2Sum, pressure > 0, held);
  co2Valid = strcmp(flag, "ok") == 0;
  float corrected = co2Valid || (raw >= 0 && pressure > 0) ? correctCo2(raw, pressure) : 0;
  if (co2Valid) remember(uptime, corrected);

  float dco2 = 0;
  bool ready = co2Valid && modelSlope(uptime, corrected, &dco2);
  float pred = A0 + A1 * corrected + A2 * dco2 + A3 * rh;
  if (!co2Valid) demand = false;
  else if (ready) {
    if (pred >= 1000 || corrected >= 1000) demand = true;
    else if (pred < 900 && corrected <= 800) demand = false;
  } else if (corrected >= 1000) demand = true;
  else if (corrected <= 800) demand = false;
  applyFan();

  const char *request = "off";
  if (demand && co2Valid) request = fanOn ? "on" : "recommend_on";
  seq++;
  String body = String("{\"seq\":") + seq + ",\"co2_raw_ppm\":" + raw + ",\"co2_ppm\":" + (int)(corrected + 0.5f) +
                ",\"vent_request\":\"" + request + "\",\"fan_on\":" + (fanOn ? "true" : "false") +
                ",\"mode\":" + mode + ",\"quality_co2\":\"" + flag + "\"}";
  publish(body);
  (void)pm25;
  (void)pm10;
  (void)tC;
  (void)gas;
  (void)PIN_SDA;
  (void)PIN_SCL;
}
