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

    interval = config["buffer"].getint("intervaal", 20)

    buf = collections.deque(maxlen=config["buffer"].getint("size", 9))
    buf.append(get_temp())

    last_ts = time.time()

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
            if temp >= config["thresholds"].getfloat("warming", 28.0):
                state = State.WARMING
                print("New state: {}".format(state))
                next_wood_addition_alert = 0

        elif state == State.WARMING:
            if temp >= config["thresholds"].getfloat("ready", 60.0):
                state = State.COOLING
                print("New state: {}".format(state))
                publish("beep", "500 500 500")

            elif slope < config["thresholds"].getFloat("minimumSlope"):
                print("Add wood!!!")
                if next_wood_addition_alert <= 0:
                    publish("beep", config["alerts"].get("addWoodSequence", "50 100 50 100 50 100 50"))
                    next_wood_addition_alert = config["alerts"].getint("addWoodPeriod", 300) / interval

                next_wood_addition_alert -= 1

        elif state == State.COOLING:
            if temp < config["thresholds"].getfloat("resting", 27.0):
                state = State.REST
                print("New state: {}".format(state))


        ts = time.time()
        s = last_ts + interval - ts

        if s > 0:
            print("Sleeping {} seconds".format(s))
            time.sleep(s)

        last_ts = time.time()
        
