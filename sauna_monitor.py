#!/usr/bin/env python3

# Copyright (c) 2017 Kari Lavikka
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
import collections
import time
import configparser
import datetime

from subprocess import call
from enum import Enum

# States
class State(Enum):
    REST = 1
    WARMING = 2
    COOLING = 3

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
    print(value)


if __name__ == '__main__':
    config.read("sauna_monitor.ini")

    state = State.REST

    next_wood_addition_alert = 0

    interval = config["buffer"].getint("interval", 20)

    # A queue is used for calculating a moving average of the temperature.
    # Temperature sensor's precision is limited and comparing adjacent samples
    # may yield erroneous derivatives. A longer interval mitigates the effect.
    buf = collections.deque(maxlen=config["buffer"].getint("size", 9))
    buf.append(get_temp())

    last_ts = time.time()

    log_file = None

    while True:
        temp = get_temp()

        # Temperature change per minute
        slope = (temp - buf[0]) / (len(buf) * interval / 60.0)

        buf.append(temp)

        print("State: {}".format(state))

        # \3 = degree symbol
        publish("r0", "Sauna: {:.1f}\3C".format(temp))
        publish("r1", "{:+.2f}\3C / min".format(slope))

        # Update state
        if state == State.REST:
            if slope >= config["thresholds"].getfloat("warmingDerivative", 0.1):
                state = State.WARMING
                warming_start = last_ts # reference for logging
                print("New state: {}".format(state))
                next_wood_addition_alert = config["alerts"].getint("initialAddWoodAlertPeriod", 900) / interval
                give_up = config["thresholds"].getint("giveUpAfter", 900) / interval

                log_path = config["logging"].get("path")
                if log_path is not None:
                    log_file = open(log_path + "/" + datetime.datetime.today().strftime('%Y-%m-%d') + ".log", 'w')

        elif state == State.WARMING:
            if temp >= config["thresholds"].getfloat("ready", 60.0):
                state = State.COOLING
                print("New state: {}".format(state))
                publish("beep", config["alerts"].get("readySequence", "500 500 500"))

            elif slope < config["thresholds"].getfloat("minimumDerivative"):
                # Give up if the slope stays below the threshold for too long
                if give_up <= 0:
                    state = State.COOLING
                    print("Giving up. Sauna does not seem to get warm today.")
                    publish("beep", "2000")

                else:
                    if next_wood_addition_alert <= 0:
                        print("Add wood!!!")
                        publish("beep", config["alerts"].get("addWoodSequence", "50 100 50 100 50 100 50"))
                        next_wood_addition_alert = config["alerts"].getint("addWoodPeriod", 300) / interval

                    next_wood_addition_alert -= 1
                    give_up -= 1

        elif state == State.COOLING:
            if temp < config["thresholds"].getfloat("resting", 27.0):
                state = State.REST
                print("New state: {}".format(state))


        if log_file is not None:
            if state == State.WARMING or state == State.COOLING:
                log_file.write("{:10.2f}\t{:f}\t{:f}\n".format((last_ts - warming_start) / 60.0, temp, slope))
                log_file.flush()
            else:
                log_file.close()
                log_file = None


        ts = time.time()
        s = last_ts + interval - ts

        if s > 0:
            print("Sleeping {} seconds".format(s))
            time.sleep(s)

        last_ts = time.time()
        
