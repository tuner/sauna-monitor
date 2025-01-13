#!/usr/bin/env python3

# Copyright (c) 2025 Kari Lavikka
# 
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
# 
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
# CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import math
import time
import configparser
import datetime
import logging
import argparse
import requests

import numpy as np
from scipy.signal import savgol_filter

from subprocess import call
from enum import Enum
from collections import deque

class TemperatureMonitor:
    # Define states
    REST = "REST"
    WARMING = "WARMING"
    COOLING = "COOLING"

    def __init__(
        self,
        window_length=11,
        polyorder=2,
        delta=0.333,
        warming_derivative_threshold=0.5,
        cooling_temperature_threshold=60.0,
        cooling_time_threshold=60,
        rest_temperature_threshold=40.0,
        alert_threshold_derivative=0.7,
        alert_threshold_second_derivative=-0.05,
        max_alert_frequency=3,
    ):
        """
        Initialize the temperature monitor with states and alert logic.
        
        Args:
            window_length (int): Window size for the Savitzky-Golay filter (must be odd).
            polyorder (int): Polynomial order for the Savitzky-Golay filter.
            delta (float): Time interval between measurements.
            warming_derivative_threshold (float): Threshold for transitioning to WARMING.
            cooling_temperature_threshold (float): Temperature to transition to COOLING.
            cooling_time_threshold (int): Time in minutes until transitioning to COOLING.
            rest_temperature_threshold (float): Temperature to transition back to REST.
            alert_threshold_derivative (float): Alert if the first derivative is less than this value.
            alert_threshold_second_derivative (float): Alert if the second derivative is less than this value.
            max_alert_frequency (int): Minimum seconds between consecutive alerts.
        """
        self.window_length = window_length
        self.polyorder = polyorder
        self.delta = delta
        self.warming_derivative_threshold = warming_derivative_threshold
        self.cooling_temperature_threshold = cooling_temperature_threshold
        self.cooling_time_threshold = cooling_time_threshold
        self.rest_temperature_threshold = rest_temperature_threshold
        self.alert_threshold_derivative = alert_threshold_derivative
        self.alert_threshold_second_derivative = alert_threshold_second_derivative
        self.max_alert_frequency = max_alert_frequency

        self.buffer = deque(maxlen=window_length)
        self.state = self.REST
        self.state_start_time = None
        self.last_alert_time = None  # Timestamp of the last alert
    
    def _change_state(self, new_state, timestamp):
        """Change the state and record the time."""
        self.state = new_state
        self.state_start_time = timestamp

    def add_measurement(self, timestamp, temperature):
        """
        Add a new measurement and process it.
        
        Args:
            timestamp (float): Time of the measurement.
            temperature (float): Temperature value.
        
        Returns:
            dict: Calculated values including smoothed temperature, first derivative,
                  second derivative, state, and alert status.
        """
        self.buffer.append((timestamp, temperature))
        
        # Ensure we have enough data to apply the Savitzky-Golay filter
        if len(self.buffer) < self.window_length:
            return {
                "smoothed_temperature": None,
                "first_derivative": None,
                "second_derivative": None,
                "state": self.state,
                "alert": False,
            }
        
        # Extract timestamps and temperatures from the buffer
        timestamps, temperatures = zip(*self.buffer)
        timestamps = np.array(timestamps)
        temperatures = np.array(temperatures)
        
        # Apply Savitzky-Golay filter
        smoothed_temperature = savgol_filter(temperatures, window_length=self.window_length, polyorder=self.polyorder)[-1]
        first_derivative = savgol_filter(temperatures, window_length=self.window_length, polyorder=self.polyorder, deriv=1, delta=self.delta)[-1]
        second_derivative = savgol_filter(temperatures, window_length=self.window_length, polyorder=self.polyorder, deriv=2, delta=self.delta)[-1]
        
        # State transitions
        if self.state == self.REST:
            if first_derivative > self.warming_derivative_threshold:
                self._change_state(self.WARMING, timestamp)
        
        elif self.state == self.WARMING:
            if smoothed_temperature >= self.cooling_temperature_threshold or \
               (self.state_start_time is not None and timestamp - self.state_start_time >= self.cooling_time_threshold):
                self._change_state(self.COOLING, timestamp)
        
        elif self.state == self.COOLING:
            if smoothed_temperature <= self.rest_temperature_threshold:
                self._change_state(self.REST, timestamp)
        
        # Alert logic
        alert = (
            self.state == self.WARMING and
            first_derivative < self.alert_threshold_derivative and
            second_derivative < self.alert_threshold_second_derivative and
            (self.last_alert_time is None or timestamp - self.last_alert_time > self.max_alert_frequency)
        )
        if alert:
            self.last_alert_time = timestamp

        return {
            "smoothed_temperature": smoothed_temperature,
            "first_derivative": first_derivative,
            "second_derivative": second_derivative,
            "state": self.state,
            "alert": alert,
        }

class AlertType(Enum):
    WARMING = 0
    READY = 1
    ADD_WOOD = 2
    GIVE_UP = 3

config = configparser.ConfigParser()

def get_temp():
    return get_sensor_temp(config["sensor"].get("path", "w1_sauna"))


def get_sensor_temp(sensor):
    try:
        mytemp = ''
        f = open(sensor, 'r')
        line = f.readline() # read 1st line
        crc = line.rsplit(' ',1)
        crc = crc[1].replace('\n', '')
        if crc == 'YES':
            line = f.readline() # read 2nd line
            mytemp = int(line.rsplit('t=',1)[1]) / float(1000)
        else:
            mytemp = math.nan
        f.close()

        return mytemp

    except:
        return math.nan


def publish(topic, value):
    call(["mosquitto_pub", "-t", config["display"].get("mqttTopic", "koti/displays/18:FE:34:E8:11:32") + "/" + topic, "-m", value])
    #logger.debug("publishing: %s", value)

def telegram_message(message, result = None):
    token = config["telegram"].get("token")
    chat_id = config["telegram"].get("chatId")
    if token is not None and chat_id is not None:
        if result is not None:
            status = "Temp: {:.1f}°C, Change: {:.2f}°C/min".format(
                result["smoothed_temperature"],
                result["first_derivative"])
            message = message + "\n" + status

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message}
        requests.post(url, json=payload)

def watch():
    config.read("sauna_monitor.ini")
    logger = logging.getLogger()
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.DEBUG)

    interval = config["buffer"].getint("interval", 20)

    log_buffer_minutes = config["buffer"].getint("logBufferMinutes", 10)
    # Keep a buffer of the last measurements. Will be written to the log file when the state changes.
    log_buffer = deque(maxlen=log_buffer_minutes*60//interval)

    def alert_handler(alert_type, result = None):
        logger.info("ALERT: " + str(alert_type))
        if alert_type == AlertType.ADD_WOOD:
            publish("beep", config["alerts"].get("addWoodSequence", "50 100 50 100 50 100 50"))
            telegram_message("Add more firewood!", result)
        elif alert_type == AlertType.GIVE_UP:
            publish("beep", config["alerts"].get("giveUpSequence", "2000"))
        elif alert_type == AlertType.READY:
            publish("beep", config["alerts"].get("readySequence", "500 500 500"))
            telegram_message("Sauna is ready!", result)
        elif alert_type == AlertType.WARMING:
            publish("beep", config["alerts"].get("warmingSequence", "100"))
            telegram_message("Sauna is warming!", result)

    monitor = TemperatureMonitor(window_length=16, polyorder=2, delta=0.33, alert_threshold_derivative=0.7)

    log_file = None

    start_time = time.time()
    log_start_time = start_time
    current_time = start_time
    elapsed_time = 0
    previous_state = TemperatureMonitor.REST

    telegram_message("Sauna monitor started")

    while True:
        temp = get_temp()

        result = monitor.add_measurement(elapsed_time / 60, temp)

        logger.debug("Time: {:.2f}, Temp: {:.3f}, First derivative: {:.3f}, Second derivative: {:.3f}, State: {}".format(
            elapsed_time / 60,
            temp,
            result["first_derivative"] if result["first_derivative"] is not None else math.nan,
            result["second_derivative"] if result["second_derivative"] is not None else math.nan,
            result["state"]))

        # \3 = degree symbol
        publish("r0", "Sauna: {:.1f}\3C".format(temp))
        if result["first_derivative"] is not None:
            publish("r1", "{:+.2f}\3C / min".format(result["first_derivative"]))
        else:
            publish("r1", "N/A")

        if result["alert"]:
            alert_handler(AlertType.ADD_WOOD, result)
        
        # Check for state transition
        current_state = result["state"]
        if current_state != previous_state:
            if current_state == TemperatureMonitor.WARMING:
                alert_handler(AlertType.WARMING, result)

                log_path = config["logging"].get("path")
                if log_path is not None:
                    log_start_time = current_time - log_buffer_minutes * 60
                    log_file = open(log_path + "/" + datetime.datetime.today().strftime('%Y-%m-%d') + ".log", 'w')
                    for entry in log_buffer:
                        log_file.write("{:10.2f}\t{:f}\n".format((entry[0] - log_start_time) / 60.0, entry[1]))
                    log_file.flush()
            elif current_state == TemperatureMonitor.COOLING:
                alert_handler(AlertType.READY, result)
            previous_state = current_state
        
        if log_file is not None:
            if current_state == TemperatureMonitor.WARMING or current_state == TemperatureMonitor.COOLING:
                log_file.write("{:10.2f}\t{:f}\n".format((elapsed_time - log_start_time) / 60.0, temp))
                log_file.flush()
            else:
                log_file.close()
                log_file = None

        log_buffer.append((elapsed_time, temp))

        ts = time.time()
        s = current_time + interval - ts

        if s > 0:
            logger.debug("Sleeping %f seconds", s)
            time.sleep(s)

        current_time = time.time()
        elapsed_time = current_time - start_time
        
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate", type=str, help="simulate using a log file")
    args = parser.parse_args()

    if args.simulate:
        pass # TODO
    else:
        watch()

