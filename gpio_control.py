#!/usr/bin/env python3
"""
GPIO Control Module
Controls entrance barrier/gate with LED simulation for testing
"""

import logging
import time

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False


class GpioController:
    def __init__(self, config, gpio_type='entrance'):
        self.config = config
        self.gpio_type = gpio_type
        self.logger = logging.getLogger(__name__)

        # get gpio configuration based on type
        gpio_config = config.get('gpio', {})
        if gpio_type == 'exit':
            gpio_config = config.get('exit_gpio', gpio_config)

        self.gate_pin = gpio_config.get('gate_pin', 18)
        self.led_pin = gpio_config.get('led_pin', 16)
        self.button_pin = gpio_config.get('button_pin', 12)
        self.initialized = False

    def initialize(self):
        """initialize gpio pins"""
        if not GPIO_AVAILABLE:
            self.logger.warning("rpi.gpio not available, using simulation mode")
            self.initialized = True
            return True

        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)

            # setup output pins
            GPIO.setup(self.gate_pin, GPIO.OUT)
            GPIO.setup(self.led_pin, GPIO.OUT)

            # setup input pin with pull-up resistor
            GPIO.setup(self.button_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

            # initial states
            GPIO.output(self.gate_pin, GPIO.LOW)  # gate closed
            GPIO.output(self.led_pin, GPIO.LOW)   # led off

            self.initialized = True
            self.logger.info("gpio initialized successfully")
            return True

        except Exception as e:
            self.logger.error(f"failed to initialize gpio: {e}")
            return False

    def open_gate(self, duration=5):
        """open entrance gate for specified duration"""
        if not self.initialized:
            self.logger.error("gpio not initialized")
            return False

        try:
            self.logger.info("opening entrance gate")

            if GPIO_AVAILABLE:
                GPIO.output(self.gate_pin, GPIO.HIGH)
                GPIO.output(self.led_pin, GPIO.HIGH)  # turn on led to indicate open gate
            else:
                self.logger.info("simulation: gate opened, led on")

            # keep gate open for duration
            time.sleep(duration)

            # close gate
            if GPIO_AVAILABLE:
                GPIO.output(self.gate_pin, GPIO.LOW)
                GPIO.output(self.led_pin, GPIO.LOW)
            else:
                self.logger.info("simulation: gate closed, led off")

            self.logger.info("entrance gate closed")
            return True

        except Exception as e:
            self.logger.error(f"failed to operate gate: {e}")
            return False

    def close_gate(self):
        """ensure gate is closed"""
        if not self.initialized:
            self.logger.error("gpio not initialized")
            return False

        try:
            if GPIO_AVAILABLE:
                GPIO.output(self.gate_pin, GPIO.LOW)
                GPIO.output(self.led_pin, GPIO.LOW)
            else:
                self.logger.info("simulation: gate closed, led off")

            self.logger.info("gate closed")
            return True

        except Exception as e:
            self.logger.error(f"failed to close gate: {e}")
            return False

    def set_led(self, state):
        """control status led"""
        if not self.initialized:
            return False

        try:
            if GPIO_AVAILABLE:
                GPIO.output(self.led_pin, GPIO.HIGH if state else GPIO.LOW)
            else:
                self.logger.debug(f"simulation: led {'on' if state else 'off'}")
            return True

        except Exception as e:
            self.logger.error(f"failed to set led: {e}")
            return False

    def read_button(self):
        """read button state for manual override"""
        if not self.initialized:
            return False

        try:
            if GPIO_AVAILABLE:
                return not GPIO.input(self.button_pin)  # inverted due to pull-up
            else:
                return False  # simulation always returns false

        except Exception as e:
            self.logger.error(f"failed to read button: {e}")
            return False

    def blink_led(self, count=3, interval=0.5):
        """blink led for status indication"""
        for _ in range(count):
            self.set_led(True)
            time.sleep(interval)
            self.set_led(False)
            time.sleep(interval)

    def cleanup(self):
        """cleanup gpio resources"""
        if not GPIO_AVAILABLE or not self.initialized:
            return

        try:
            GPIO.cleanup()
            self.logger.info("gpio cleaned up")
        except Exception as e:
            self.logger.error(f"failed to cleanup gpio: {e}")