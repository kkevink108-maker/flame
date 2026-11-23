// Flame HID: a USB keyboard + absolute mouse for the game computer, driven by
// text commands on UART1 (GP4 = TX, GP5 = RX, 115200 baud) from a USB-serial
// adapter on the other PC.
//
//   PING          -> PONG
//   MOVE x y      -> OK      (x, y = 0..32767 across the whole screen)
//   CLICK         -> OK      (left click where the mouse is)
//   KEY name      -> OK      (ENTER, ESC, SPACE, TAB, BACKSPACE, UP/DOWN/LEFT/RIGHT,
//                             F1..F12, A..Z, 0..9)
//   anything else -> ERR ...
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bsp/board_api.h"
#include "hardware/uart.h"
#include "pico/stdlib.h"
#include "tusb.h"
#include "usb_descriptors.h"

#define UART uart1
#define UART_TX_PIN 4
#define UART_RX_PIN 5
#define BAUD 115200

static int16_t mouse_x = 16384, mouse_y = 16384;

static void reply(const char *s) {
    uart_puts(UART, s);
    uart_puts(UART, "\n");
}

// Keep USB serviced while waiting.
static void wait_ms(uint32_t ms) {
    absolute_time_t end = make_timeout_time_ms(ms);
    while (!time_reached(end)) tud_task();
}

// Wait until the previous report has been sent. False if USB isn't up.
static bool hid_wait_ready(void) {
    absolute_time_t end = make_timeout_time_ms(100);
    while (!tud_hid_ready()) {
        tud_task();
        if (!tud_mounted() || time_reached(end)) return false;
    }
    return true;
}

static bool send_mouse(uint8_t buttons) {
    if (!hid_wait_ready()) return false;
    return tud_hid_abs_mouse_report(REPORT_ID_MOUSE, buttons, mouse_x, mouse_y, 0, 0);
}

static bool send_key(uint8_t keycode) {
    uint8_t keys[6] = {keycode, 0, 0, 0, 0, 0};
    if (!hid_wait_ready()) return false;
    return tud_hid_keyboard_report(REPORT_ID_KEYBOARD, 0, keycode ? keys : NULL);
}

static uint8_t keycode_for(const char *name) {
    static const struct { const char *name; uint8_t code; } named[] = {
        {"ENTER", HID_KEY_ENTER}, {"RETURN", HID_KEY_ENTER}, {"ESC", HID_KEY_ESCAPE},
        {"ESCAPE", HID_KEY_ESCAPE}, {"SPACE", HID_KEY_SPACE}, {"TAB", HID_KEY_TAB},
        {"BACKSPACE", HID_KEY_BACKSPACE}, {"UP", HID_KEY_ARROW_UP}, {"DOWN", HID_KEY_ARROW_DOWN},
        {"LEFT", HID_KEY_ARROW_LEFT}, {"RIGHT", HID_KEY_ARROW_RIGHT},
    };
    for (size_t i = 0; i < sizeof(named) / sizeof(named[0]); i++)
        if (strcmp(name, named[i].name) == 0) return named[i].code;
    if (name[0] == 'F' && name[1]) {
        int n = atoi(name + 1);
        if (n >= 1 && n <= 12) return (uint8_t)(HID_KEY_F1 + n - 1);
    }
    if (name[0] && !name[1]) {
        if (name[0] >= 'A' && name[0] <= 'Z') return (uint8_t)(HID_KEY_A + name[0] - 'A');
        if (name[0] >= '1' && name[0] <= '9') return (uint8_t)(HID_KEY_1 + name[0] - '1');
        if (name[0] == '0') return HID_KEY_0;
    }
    return 0;
}

static void handle(char *line) {
    for (char *p = line; *p; p++) *p = (char)toupper((unsigned char)*p);
    char *cmd = strtok(line, " \t");
    if (!cmd) return;

    if (strcmp(cmd, "PING") == 0) {
        reply("PONG");
        return;
    }
    if (!tud_mounted()) {
        reply("ERR USB not connected to the game computer");
        return;
    }
    if (strcmp(cmd, "MOVE") == 0) {
        char *sx = strtok(NULL, " \t"), *sy = strtok(NULL, " \t");
        if (!sx || !sy) { reply("ERR use MOVE x y"); return; }
        long x = strtol(sx, NULL, 10), y = strtol(sy, NULL, 10);
        mouse_x = (int16_t)(x < 0 ? 0 : x > 32767 ? 32767 : x);
        mouse_y = (int16_t)(y < 0 ? 0 : y > 32767 ? 32767 : y);
        reply(send_mouse(0) ? "OK" : "ERR USB busy");
    } else if (strcmp(cmd, "CLICK") == 0) {
        bool ok = send_mouse(MOUSE_BUTTON_LEFT);
        wait_ms(40 + (time_us_32() % 30));       // hold like a real click
        ok = send_mouse(0) && ok;
        reply(ok ? "OK" : "ERR USB busy");
    } else if (strcmp(cmd, "KEY") == 0) {
        char *name = strtok(NULL, " \t");
        uint8_t code = name ? keycode_for(name) : 0;
        if (!code) { reply("ERR unknown key"); return; }
        bool ok = send_key(code);
        wait_ms(50 + (time_us_32() % 30));
        ok = send_key(0) && ok;
        reply(ok ? "OK" : "ERR USB busy");
    } else {
        reply("ERR unknown command");
    }
}

int main(void) {
    board_init();
    tusb_init();

    uart_init(UART, BAUD);
    gpio_set_function(UART_TX_PIN, GPIO_FUNC_UART);
    gpio_set_function(UART_RX_PIN, GPIO_FUNC_UART);

    char line[64];
    size_t len = 0;
    while (true) {
        tud_task();
        while (uart_is_readable(UART)) {
            char c = uart_getc(UART);
            if (c == '\n' || c == '\r') {
                line[len] = 0;
                if (len) handle(line);
                len = 0;
            } else if (len < sizeof(line) - 1) {
                line[len++] = c;
            } else {
                len = 0;                          // too long: drop it
            }
        }
    }
}

// TinyUSB callbacks we don't use.
uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t report_id, hid_report_type_t report_type,
                               uint8_t *buffer, uint16_t reqlen) {
    (void)instance; (void)report_id; (void)report_type; (void)buffer; (void)reqlen;
    return 0;
}

void tud_hid_set_report_cb(uint8_t instance, uint8_t report_id, hid_report_type_t report_type,
                           uint8_t const *buffer, uint16_t bufsize) {
    (void)instance; (void)report_id; (void)report_type; (void)buffer; (void)bufsize;
}
