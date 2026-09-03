/*
 * esp32_bridge.ino — TraceWorks WiFi-to-serial G-code bridge
 * ----------------------------------------------------------
 * Receives a G-code job over HTTP from the TraceWorks backend and streams it,
 * line by line, to an Arduino running GRBL over serial — using GRBL's standard
 * send/"ok" handshake (one line out, wait for "ok"/"error", then the next).
 *
 *   web app  ->  FastAPI backend  ->  [this ESP32]  --Serial2-->  Arduino (GRBL)
 *
 * HTTP API (port 80):
 *   POST /print   body = raw G-code text. Header "X-Check: 1" runs GRBL check
 *                 mode ($C, validate only, no motion) before streaming.
 *                 Returns 202 and starts the job; streaming happens in loop().
 *   GET  /status  -> {"state":"...","line":N,"total":M}
 *   POST /stop    -> aborts the current job
 *   GET  /        -> health/info
 *
 * state: idle | checking | printing | done | error | stopped
 *
 * Wiring (see firmware/README.md):
 *   ESP32 GPIO17 (TX2) -> Arduino RX0
 *   ESP32 GPIO16 (RX2) <- Arduino TX0
 *   ESP32 GND          -> Arduino GND   (common ground, required)
 *
 * Fill in your WiFi credentials below before flashing.
 */

#include <WiFi.h>
#include <WebServer.h>

// ----------------------------------------------------------------- config
#define WIFI_SSID     "YOUR_WIFI_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"

static const uint32_t GRBL_BAUD    = 115200;  // must match your GRBL build
static const int      GRBL_RX_PIN  = 16;      // ESP32 RX2  <- Arduino TX
static const int      GRBL_TX_PIN  = 17;      // ESP32 TX2  -> Arduino RX
static const uint32_t REPLY_TIMEOUT_MS = 15000; // per-line wait for "ok"

WebServer server(80);
HardwareSerial &grbl = Serial2;

// ------------------------------------------------------------- job state
enum State { IDLE, CHECKING, PRINTING, DONE, ERROR, STOPPED };
State   state       = IDLE;
String  job;                 // full G-code buffer for the current job
int     jobPos       = 0;    // byte offset into `job` of the next line
int     lineNo       = 0;    // lines sent so far
int     lineTotal    = 0;    // total non-empty lines in the job
bool    checkMode    = false;
bool    awaitingOk   = false; // a line is out; waiting for GRBL's reply
uint32_t sentAt      = 0;     // millis() when the current line was sent
String  lastError    = "";

const char *stateName(State s) {
  switch (s) {
    case IDLE:     return "idle";
    case CHECKING: return "checking";
    case PRINTING: return "printing";
    case DONE:     return "done";
    case ERROR:    return "error";
    case STOPPED:  return "stopped";
  }
  return "idle";
}

// Count non-empty, non-comment lines so /status totals match what we stream.
int countLines(const String &g) {
  int n = 0, i = 0, len = g.length();
  while (i < len) {
    int nl = g.indexOf('\n', i);
    if (nl < 0) nl = len;
    String ln = g.substring(i, nl);
    ln.trim();
    int sc = ln.indexOf(';');
    if (sc >= 0) { ln = ln.substring(0, sc); ln.trim(); }
    if (ln.length() > 0) n++;
    i = nl + 1;
  }
  return n;
}

// Pull the next cleaned line from `job` starting at jobPos; advance jobPos.
// Returns false when the job is exhausted.
bool nextLine(String &out) {
  int len = job.length();
  while (jobPos < len) {
    int nl = job.indexOf('\n', jobPos);
    if (nl < 0) nl = len;
    String ln = job.substring(jobPos, nl);
    jobPos = nl + 1;
    ln.trim();
    int sc = ln.indexOf(';');
    if (sc >= 0) { ln = ln.substring(0, sc); ln.trim(); }
    if (ln.length() > 0) { out = ln; return true; }
  }
  return false;
}

void sendLine(const String &line) {
  grbl.print(line);
  grbl.print('\n');
  awaitingOk = true;
  sentAt = millis();
}

void finishError(const String &msg) {
  lastError = msg;
  state = ERROR;
  awaitingOk = false;
  job = "";
}

// Read GRBL replies; return true once an "ok"/"error" arrived for the line in
// flight. Banners, [MSG:..] and <status> reports are ignored.
bool pumpReply() {
  while (grbl.available()) {
    String raw = grbl.readStringUntil('\n');
    raw.trim();
    if (raw.length() == 0) continue;
    String low = raw;
    low.toLowerCase();
    if (low == "ok") { awaitingOk = false; return true; }
    if (low.startsWith("error")) { finishError(raw); return true; }
    // else: banner / message / status — keep reading
  }
  return false;
}

// ------------------------------------------------------------- HTTP handlers
void handleRoot() {
  String body = String("{\"name\":\"traceworks-esp32-bridge\",\"state\":\"") +
                stateName(state) + "\"}";
  server.send(200, "application/json", body);
}

void handleStatus() {
  String body = String("{\"state\":\"") + stateName(state) +
                "\",\"line\":" + lineNo + ",\"total\":" + lineTotal;
  if (state == ERROR && lastError.length())
    body += String(",\"error\":\"") + lastError + "\"";
  body += "}";
  server.send(200, "application/json", body);
}

void handlePrint() {
  if (state == PRINTING || state == CHECKING) {
    server.send(409, "application/json",
                "{\"error\":\"a job is already running\"}");
    return;
  }
  if (!server.hasArg("plain") || server.arg("plain").length() == 0) {
    server.send(400, "application/json",
                "{\"error\":\"empty body; expected G-code\"}");
    return;
  }
  job       = server.arg("plain");
  jobPos    = 0;
  lineNo    = 0;
  lineTotal = countLines(job);
  lastError = "";
  awaitingOk = false;
  checkMode = server.hasHeader("X-Check") && server.header("X-Check") == "1";

  // Wake GRBL and clear its startup banner before we start streaming.
  grbl.write("\r\n\r\n");
  delay(50);
  while (grbl.available()) grbl.read();

  if (checkMode) { state = CHECKING; sendLine("$C"); }
  else           { state = PRINTING; }

  String body = String("{\"ok\":true,\"total\":") + lineTotal +
                ",\"check\":" + (checkMode ? "true" : "false") + "}";
  server.send(202, "application/json", body);
}

void handleStop() {
  if (state == PRINTING || state == CHECKING) {
    // Best effort: feed-hold + soft-reset so motion halts promptly.
    grbl.write("!");
    delay(20);
    grbl.write(0x18); // Ctrl-X soft reset
  }
  job = "";
  awaitingOk = false;
  state = STOPPED;
  server.send(200, "application/json", "{\"ok\":true}");
}

// ------------------------------------------------------------- streaming step
void streamStep() {
  if (state != PRINTING && state != CHECKING) return;

  if (awaitingOk) {
    if (pumpReply()) {
      if (state == ERROR) return;            // error already recorded
      if (state == CHECKING && lineNo == 0) {
        // the "ok" we just got was for the "$C" check-mode toggle; start lines
      }
    } else if (millis() - sentAt > REPLY_TIMEOUT_MS) {
      finishError("timeout waiting for GRBL");
      return;
    } else {
      return;                                // still waiting
    }
  }

  String line;
  if (nextLine(line)) {
    lineNo++;
    sendLine(line);
  } else {
    // job drained. If we were checking, toggle check mode back off.
    if (state == CHECKING) grbl.write("$C\n");
    state = DONE;
    job = "";
  }
}

// ------------------------------------------------------------- setup / loop
void setup() {
  Serial.begin(115200);
  grbl.begin(GRBL_BAUD, SERIAL_8N1, GRBL_RX_PIN, GRBL_TX_PIN);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) { delay(400); Serial.print('.'); }
  Serial.println();
  Serial.print("Bridge ready at http://");
  Serial.println(WiFi.localIP());

  // Collect the X-Check header so hasHeader/header() see it.
  const char *headerKeys[] = {"X-Check"};
  server.collectHeaders(headerKeys, 1);

  server.on("/", HTTP_GET, handleRoot);
  server.on("/status", HTTP_GET, handleStatus);
  server.on("/print", HTTP_POST, handlePrint);
  server.on("/stop", HTTP_POST, handleStop);
  server.begin();
}

void loop() {
  server.handleClient();
  streamStep();
}
