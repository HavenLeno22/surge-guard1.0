/*
  SurgeGuard alert hardware - Arduino Uno, RGB LED and buzzer.

  The SurgeGuard backend sends one command per line over USB serial, derived
  from the Operational Decision Engine's report status (never from a timer or
  a button). This sketch only displays what it is told, and says so when it is
  told nothing.

  Wiring, physically verified on 2026-09-17 by driving each pin alone and
  having the operator report the colour (not inferred from pin names; the
  original plan of R=9/G=10/B=11 was never what was on the breadboard):
    Pin 9  -> RGB LED blue leg  (through a resistor)
    Pin 10 -> RGB LED red leg   (through a resistor)
    Pin 11 -> RGB LED green leg (through a resistor)
    RGB LED common leg -> GND (common cathode: all pins LOW is dark)
    Buzzer -> pin 8 (driven with tone(), as the original sketch did)
  Red once showed nothing on pin 10 while the same wire lit red on pin 9: the
  jumper was badly seated in the header. Reseated, pin 10 is steady red. If a
  colour vanishes again, press that jumper home before suspecting firmware.

  Pin 11 is Timer2's PWM pin, and tone() owns Timer2, so analogWrite() on it
  would fight the buzzer. Green is therefore dimmed in software (time-sliced
  with micros()); pin 11 is only ever used as a plain digital output. Dimming
  matters for yellow: full green swamps red and WARNING looked like NORMAL.

  Preserved from the sketch that was on the board
  (NMDC_FogGuard_FINAL_MANUAL_DEMO_v0_9__1_.ino): the buzzer on pin 8, the
  80 ms 1500 Hz startup beep, and the quiet 70 ms 1500 Hz chirp every 1.5 s,
  which is now the WARNING pattern.

  Serial protocol - 115200 baud, one command per line, case-insensitive:
    NORMAL | WARNING | CRITICAL | NO_DATA     set the alert level
    TEST RED | GREEN | BLUE | YELLOW          light one colour, silent
    TEST WARNING_TONE | ALARM                 play a pattern, LED off
    TEST SEQUENCE                             cycle every colour and pattern
    TEST OFF                                  LED off, silent
    TUNE YELLOW <red 0-255> <green 0-255>     set the yellow mix until reset
    PING                                      -> PONG <mode>
    STATUS                                    -> STATE <mode> <since ms>
  Every accepted command is answered "OK <command>", anything else "ERR ...".
  On power-up the sketch prints "READY SURGEGUARD-ALERT <version> ...".

  Level commands (and PING) keep the link alive. After LINK_TIMEOUT_MS without
  one, the LED blinks blue and the buzzer stays silent: the hardware no longer
  knows the crowd's state and must not keep claiming the last one. TEST
  commands are exempt from the timeout so a test can be run from the Serial
  Monitor with no backend at all.
*/

#include <Arduino.h>

// -- Configuration ----------------------------------------------------------

#define FIRMWARE_VERSION "1.1.0"
#define SERIAL_BAUD 115200

#define PIN_BUZZER 8
// Physically verified 2026-09-17, one pin at a time. See the wiring note above.
#define PIN_BLUE 9    // Timer1 PWM
#define PIN_RED 10    // Timer1 PWM
#define PIN_GREEN 11  // Timer2 belongs to tone(): software-dimmed, never analogWrite().

// Common cathode: HIGH lights a colour. Set to true for a common-anode LED
// (its long leg on 5V), where LOW lights a colour.
#define RGB_COMMON_ANODE false

// Green's software PWM period. 2 ms (500 Hz) does not flicker visibly.
#define GREEN_SOFT_PWM_PERIOD_US 2000UL

// Yellow from a red and a green die: green dies are much brighter, so it is
// dimmed. Default only; TUNE YELLOW changes it at runtime for tuning by eye.
#define YELLOW_RED 255
#define YELLOW_GREEN 20  // ~8%: tuned by eye 2026-09-17 (60 still read as green)

#define STARTUP_BEEP_HZ 1500
#define STARTUP_BEEP_MS 80

// WARNING: the original quiet alert pattern.
#define WARNING_TONE_HZ 1500
#define WARNING_TONE_ON_MS 70
#define WARNING_TONE_PERIOD_MS 1500

// CRITICAL: a two-tone alarm with no silent gap.
#define ALARM_HIGH_HZ 2000
#define ALARM_LOW_HZ 1300
#define ALARM_HALF_PERIOD_MS 250

#define LINK_TIMEOUT_MS 10000UL
#define LINK_LOST_BLINK_MS 500
#define SEQUENCE_STEP_MS 1200

#define LINE_BUFFER_SIZE 40

// -- State ------------------------------------------------------------------

enum Mode {
  MODE_WAITING,    // powered up, no command yet: steady blue
  MODE_NORMAL,
  MODE_WARNING,
  MODE_CRITICAL,
  MODE_NO_DATA,    // backend has no current decision stream: steady blue
  MODE_LINK_LOST,  // backend went silent: blinking blue
  MODE_TEST_RED,
  MODE_TEST_GREEN,
  MODE_TEST_BLUE,
  MODE_TEST_YELLOW,
  MODE_TEST_WARNING_TONE,
  MODE_TEST_ALARM,
  MODE_TEST_SEQUENCE,
  MODE_TEST_OFF
};

Mode g_mode = MODE_WAITING;
unsigned long g_modeSince = 0;
unsigned long g_lastLevelCommandAt = 0;
bool g_linkEstablished = false;

// Which tone is sounding, so tone() is only called on a change.
int g_toneHz = 0;

char g_line[LINE_BUFFER_SIZE];
uint8_t g_lineLength = 0;
bool g_lineOverflow = false;

uint8_t g_yellowRed = YELLOW_RED;
uint8_t g_yellowGreen = YELLOW_GREEN;

// -- Outputs ----------------------------------------------------------------

void writeChannel(uint8_t pin, uint8_t level) {
  analogWrite(pin, RGB_COMMON_ANODE ? 255 - level : level);
}

void writeGreen(uint8_t level) {
  // Software PWM with digitalWrite: analogWrite on pin 11 would reprogram
  // Timer2 under tone(). Needs render() on every loop pass, which it gets.
  bool on;
  if (level == 0) on = false;
  else if (level == 255) on = true;
  else on = (micros() % GREEN_SOFT_PWM_PERIOD_US) < (GREEN_SOFT_PWM_PERIOD_US * level) / 255;
  digitalWrite(PIN_GREEN, (on != RGB_COMMON_ANODE) ? HIGH : LOW);
}

void setColour(uint8_t red, uint8_t green, bool blue) {
  writeChannel(PIN_RED, red);
  writeGreen(green);
  writeChannel(PIN_BLUE, blue ? 255 : 0);
}

void soundHz(int hz) {
  if (hz == g_toneHz) return;
  if (hz <= 0) {
    noTone(PIN_BUZZER);
  } else {
    tone(PIN_BUZZER, hz);
  }
  g_toneHz = hz;
}

void playWarningTone(unsigned long elapsed) {
  soundHz((elapsed % WARNING_TONE_PERIOD_MS) < WARNING_TONE_ON_MS ? WARNING_TONE_HZ : 0);
}

void playAlarm(unsigned long elapsed) {
  soundHz(((elapsed / ALARM_HALF_PERIOD_MS) % 2 == 0) ? ALARM_HIGH_HZ : ALARM_LOW_HZ);
}

// -- Mode handling ----------------------------------------------------------

const char* modeName(Mode mode) {
  switch (mode) {
    case MODE_WAITING: return "WAITING";
    case MODE_NORMAL: return "NORMAL";
    case MODE_WARNING: return "WARNING";
    case MODE_CRITICAL: return "CRITICAL";
    case MODE_NO_DATA: return "NO_DATA";
    case MODE_LINK_LOST: return "LINK_LOST";
    case MODE_TEST_RED: return "TEST_RED";
    case MODE_TEST_GREEN: return "TEST_GREEN";
    case MODE_TEST_BLUE: return "TEST_BLUE";
    case MODE_TEST_YELLOW: return "TEST_YELLOW";
    case MODE_TEST_WARNING_TONE: return "TEST_WARNING_TONE";
    case MODE_TEST_ALARM: return "TEST_ALARM";
    case MODE_TEST_SEQUENCE: return "TEST_SEQUENCE";
    case MODE_TEST_OFF: return "TEST_OFF";
  }
  return "UNKNOWN";
}

bool isTestMode(Mode mode) {
  return mode >= MODE_TEST_RED;
}

void enterMode(Mode mode) {
  if (mode != g_mode) {
    g_mode = mode;
    g_modeSince = millis();
  }
}

void render(unsigned long now) {
  unsigned long elapsed = now - g_modeSince;

  switch (g_mode) {
    case MODE_WAITING:
    case MODE_NO_DATA:
      setColour(0, 0, true);
      soundHz(0);
      break;
    case MODE_LINK_LOST:
      setColour(0, 0, (elapsed / LINK_LOST_BLINK_MS) % 2 == 0);
      soundHz(0);
      break;
    case MODE_NORMAL:
    case MODE_TEST_GREEN:
      setColour(0, 255, false);
      soundHz(0);
      break;
    case MODE_WARNING:
      setColour(g_yellowRed, g_yellowGreen, false);
      playWarningTone(elapsed);
      break;
    case MODE_CRITICAL:
      setColour(255, 0, false);
      playAlarm(elapsed);
      break;
    case MODE_TEST_RED:
      setColour(255, 0, false);
      soundHz(0);
      break;
    case MODE_TEST_BLUE:
      setColour(0, 0, true);
      soundHz(0);
      break;
    case MODE_TEST_YELLOW:
      setColour(g_yellowRed, g_yellowGreen, false);
      soundHz(0);
      break;
    case MODE_TEST_WARNING_TONE:
      setColour(0, 0, false);
      playWarningTone(elapsed);
      break;
    case MODE_TEST_ALARM:
      setColour(0, 0, false);
      playAlarm(elapsed);
      break;
    case MODE_TEST_OFF:
      setColour(0, 0, false);
      soundHz(0);
      break;
    case MODE_TEST_SEQUENCE: {
      // Red, green, blue, yellow, then the warning chirp and the alarm, repeating.
      unsigned long step = (elapsed / SEQUENCE_STEP_MS) % 6;
      unsigned long inStep = elapsed % SEQUENCE_STEP_MS;
      if (step == 0) { setColour(255, 0, false); soundHz(0); }
      else if (step == 1) { setColour(0, 255, false); soundHz(0); }
      else if (step == 2) { setColour(0, 0, true); soundHz(0); }
      else if (step == 3) { setColour(g_yellowRed, g_yellowGreen, false); soundHz(0); }
      else if (step == 4) { setColour(g_yellowRed, g_yellowGreen, false); soundHz(inStep < WARNING_TONE_ON_MS ? WARNING_TONE_HZ : 0); }
      else { setColour(255, 0, false); playAlarm(inStep); }
      break;
    }
  }
}

// -- Commands ---------------------------------------------------------------

void reply(const char* prefix, const char* detail) {
  Serial.print(prefix);
  if (detail != nullptr && detail[0] != '\0') {
    Serial.print(' ');
    Serial.print(detail);
  }
  Serial.print('\n');
}

void acceptLevel(Mode mode, const char* name) {
  g_lastLevelCommandAt = millis();
  g_linkEstablished = true;
  enterMode(mode);
  reply("OK", name);
}

void handleCommand(char* line) {
  // Uppercase in place, so commands are case-insensitive.
  for (char* c = line; *c != '\0'; ++c) {
    if (*c >= 'a' && *c <= 'z') *c = *c - 'a' + 'A';
  }

  if (strcmp(line, "NORMAL") == 0) return acceptLevel(MODE_NORMAL, "NORMAL");
  if (strcmp(line, "WARNING") == 0) return acceptLevel(MODE_WARNING, "WARNING");
  if (strcmp(line, "CRITICAL") == 0) return acceptLevel(MODE_CRITICAL, "CRITICAL");
  if (strcmp(line, "NO_DATA") == 0) return acceptLevel(MODE_NO_DATA, "NO_DATA");

  if (strcmp(line, "PING") == 0) {
    g_lastLevelCommandAt = millis();
    return reply("PONG", modeName(g_mode));
  }
  if (strcmp(line, "STATUS") == 0) {
    Serial.print("STATE ");
    Serial.print(modeName(g_mode));
    Serial.print(' ');
    Serial.print(millis() - g_modeSince);
    Serial.print('\n');
    return;
  }

  if (strncmp(line, "TUNE YELLOW ", 12) == 0) {
    // Runtime only (lost on reset): for matching yellow to this LED by eye.
    int red, green;
    if (sscanf(line + 12, "%d %d", &red, &green) != 2 || red < 0 || red > 255 || green < 0 ||
        green > 255) {
      return reply("ERR BAD_TUNE", line + 12);
    }
    g_yellowRed = (uint8_t)red;
    g_yellowGreen = (uint8_t)green;
    Serial.print("OK TUNE YELLOW ");
    Serial.print(red);
    Serial.print(' ');
    Serial.print(green);
    Serial.print('\n');
    return;
  }

  if (strncmp(line, "TEST ", 5) == 0) {
    const char* what = line + 5;
    Mode mode;
    if (strcmp(what, "RED") == 0) mode = MODE_TEST_RED;
    else if (strcmp(what, "GREEN") == 0) mode = MODE_TEST_GREEN;
    else if (strcmp(what, "BLUE") == 0) mode = MODE_TEST_BLUE;
    else if (strcmp(what, "YELLOW") == 0) mode = MODE_TEST_YELLOW;
    else if (strcmp(what, "WARNING_TONE") == 0) mode = MODE_TEST_WARNING_TONE;
    else if (strcmp(what, "ALARM") == 0) mode = MODE_TEST_ALARM;
    else if (strcmp(what, "SEQUENCE") == 0) mode = MODE_TEST_SEQUENCE;
    else if (strcmp(what, "OFF") == 0) mode = MODE_TEST_OFF;
    else return reply("ERR UNKNOWN_TEST", what);
    enterMode(mode);
    return reply("OK TEST", what);
  }

  if (line[0] == '\0') return;  // a blank line is not an error
  reply("ERR UNKNOWN_COMMAND", line);
}

void readSerial() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      g_line[g_lineLength] = '\0';
      if (g_lineOverflow) {
        reply("ERR LINE_TOO_LONG", nullptr);
      } else {
        handleCommand(g_line);
      }
      g_lineLength = 0;
      g_lineOverflow = false;
      continue;
    }
    if (g_lineLength < LINE_BUFFER_SIZE - 1) {
      g_line[g_lineLength++] = c;
    } else {
      g_lineOverflow = true;
    }
  }
}

// -- Arduino entry points ---------------------------------------------------

void setup() {
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_RED, OUTPUT);
  pinMode(PIN_GREEN, OUTPUT);
  pinMode(PIN_BLUE, OUTPUT);

  setColour(0, 0, false);

  // Short startup beep, as before.
  tone(PIN_BUZZER, STARTUP_BEEP_HZ);
  delay(STARTUP_BEEP_MS);
  noTone(PIN_BUZZER);

  Serial.begin(SERIAL_BAUD);
  g_modeSince = millis();
  Serial.print("READY SURGEGUARD-ALERT " FIRMWARE_VERSION " R");
  Serial.print(PIN_RED);
  Serial.print(" G");
  Serial.print(PIN_GREEN);
  Serial.print(" B");
  Serial.print(PIN_BLUE);
  Serial.print(" BUZZER");
  Serial.print(PIN_BUZZER);
  Serial.print(RGB_COMMON_ANODE ? " ANODE" : " CATHODE");
  Serial.print('\n');
}

void loop() {
  readSerial();

  unsigned long now = millis();
  bool levelMode = g_mode == MODE_NORMAL || g_mode == MODE_WARNING || g_mode == MODE_CRITICAL ||
                   g_mode == MODE_NO_DATA;
  if (g_linkEstablished && levelMode && now - g_lastLevelCommandAt > LINK_TIMEOUT_MS) {
    enterMode(MODE_LINK_LOST);
    reply("LINK_LOST", nullptr);
  }

  render(now);
}
