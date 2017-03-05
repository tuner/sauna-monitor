# sauna-monitor
An infrastructure for monitoring the sauna warming process.

An ESP8266 based display shows the current temperature and the rate of temperature change.
The display also has a buzzer, which alerts if the sauna is not warming fast enough, i.e.
more wood should be added to the sauna stove. Alert is also triggered when the desired
bathing temperature has been reached.

This project is partially based on the ideas and code of Juho Mäkinen.
See http://www.juhonkoti.net/2016/11/12/having-fun-with-iot

## Architecture

### MQTT

Messages are routed through an MQTT broker. I'm using Mosquitto.

### sauna_monitor.py

A python script is running on my raspberry pi, which among other things monitors the temperature of my sauna.
Juho's version was written in Ruby and wasn't particularly suitable for my infrastructure. I wrote a new one in Python.

### sauna_display/sauna_display.ino

The display is dumb. It just displays the messages received from MQTT or plays some alert sound sequences.
The source code is adapted from Juho's version.
