# Micropython Amperage Monitor
- [Micropython Amperage Monitor](#micropython-amperage-monitor)
  - [Introduction](#introduction)
  - [Microcontroller](#microcontroller)
  - [Cabling](#cabling)
    - [Dupont 3x Connector](#dupont-3x-connector)
    - [Analog Output to Amperage for ACS5712](#analog-output-to-amperage-for-acs5712)
  - [Files](#files)
  - [Configuration](#configuration)
    - [ADC Configuration Options](#adc-configuration-options)
  - [Operation](#operation)
  - [CMD Examples](#cmd-examples)
  - [Data Responses](#data-responses)

View our load testing series here:  https://www.learningtopi.com/category/load-testing/

## Introduction
This project utilizes a hall effect based linear current sensor and reports the information to a device connected on a UART interface (separate from the REPL console).

The sensor used is a Gikfun 20A based on an ACS712 module.  This module is capable of reading -20A to +20A and is available from [Amazon](https://www.amazon.com/gp/product/B00RBHOLUU/ref=ppx_yo_dt_b_search_asin_title?ie=UTF8&psc=1).  The specifications for the ACS712 module can be found [HERE](https://www.allegromicro.com/~/media/files/datasheets/acs712-datasheet.ashx).

## Microcontroller
The initial release will use an analog-to-digital (ADC) interface on an ESP32 microcontroller.  Future releases may include other microcontrollers (i.e. RP2040).

> &#x26a0;&#xfe0f; **The ACS712 outputs up to 5V on the signal line and ESP32/RP2040 microcontrollers are only 3.3V tolerant.  Please review the cabling section below and verify before applying more than an a couple of amps through the sensor**

## Cabling
The ACS712 sensor has a 5V VCC input, signal out, and ground available via dupont jumpers on one end of the board.  On the other are 2x screw terminals for the line to monitor.

>>> **Insert a diagram here!**

### Dupont 3x Connector
| Pin Label | Description |
| --------- | ----------- |
| VCC | 5V input
| OUT | Analog output ranging from 0 - 5V
| GND | Ground

The screw terminals should be connected inline with the ground from the device that you intend to monitor the amperage draw from.  As the microcontroller maxes as 3.3V, the polarity of the cables matter!

### Analog Output to Amperage for ACS5712
The table below shows the voltage at different amperage levels.
| Voltage | Amperage |
| ------- | -------- |
| 0V       | -20A     |
| 2.5V     | 0A |
| 5V | 20A |

Since the ACS5712 is capable of reading positive and negative amperage, we need to make sure that the terminals are connected to read our DC current as "negative".  Otherwise at approx 6amps we will exceed the 3.3V limit on the ESP32.  The best way to verify is to test.  Get a baseline reading with no load, then tests again with 1-2 amps of load.  If the output reads over 2.5v, switch the polarity.


## Files
The project contains several files, all of which are outlined here:
| File | Description |
| --- | ---|
| boot.py | Micropython boot script - Outputs some useful stats during the startup process |
| main.py | Main code file for the project
| config.json | Configuration file (not present in repo since it includes passwords)|
| config-sample.json | Sample configuration file with passwords removed, copy to config.json and udpate as needed |
| lib/esp32_controller.py | Generic class that includes connecting to the WiFi, syncing time via NTP, and connecting to MQTT (not used in this project, but will come up in others!)|
| lib/custom_mqtt.py | Custom MQTT library created to fix errors I ran into with other libraries (not used in this project)|
| lib/uping.py | uping library (see file for copyright and license info)|
| loglevel.py | Helper constants and functions for logging purposes|

## Configuration
The configuration is all applied via a json file copied to the microcontroller.  A sample json file is included in the project named config-sample.json.  

> Be sure to rename your file as "config.json" before copying to the microcontroller!
```json
{
    "network": {
        "ssid": "******",  
        "psk": "******"
    },
    "adc": {
        "baseline_time": 30, 
        "interval": 100, 
        "timeout": 30, 
        "avg_count": 5, 
        "pins": [
            {
                "name": "sensor1pin32",
                "pin": 32,
                "atten": 11,
                "zero_voltage": 2.5,
                "max_voltage": 3.3,
                "max_adc_read": 4095,
                "max_amperage": 20
            }
        ]
    },
    "uart": {
        "uart": 2,
        "baudrate": 115200
    },
    "ntp_server": "192.168.1.1",
    "timezone": -7,
    "timezone_name": "PST",
    "logging_console": 7,
    "webrepl": {
        "enabled": true,
        "password": "test123"
    }
}
```

The configuration file is broken down into sections.  The "network" section can be removed from the configuration if WiFi is not needed, however this will aso require the removal of the NTP and WebREPL configuration as well.  Network, timezone, and WebREPL are self explanitory.  The "logging_console" configuration sets the logging level for the Micropython REPL.  0-7 is supported (emergency - debug).  See the loglevel.py file for number to name mappings if needed.

The ADC and UART configuration is outlined below:
### ADC Configuration Options
The ADC (analog-digital-converter) options are broken into two groups.  Settings that apply to all ADC pins, and settings that apply to a single ADC pin.  The project is designed to support multple ADC inputs.

Global ADC configuration is applied under the "adc" dict as follows:

| Field | Type | Description |
| --- | --- | --- |
| baseline_time | int (seconds) | Time to run the baseline for (see baseline section for details) |
| interval | int (milliseconds) | Time between sampling intervals |
| timeout | int (seconds) | Time to run the samping for (can be overridden at runtime) |
| avg_count |  int | Number of samples to average together (decreases outliers, in addition the highest and lowest value are dropped) |
| pins | list | List of dict objects (see below for details), one per ADC to read |

Per Pin configuration is applied as a dictionary object in the "pins" list:

| Field | Type | Description |
| --- | --- | --- |
| name | str | Name of the object - used during reporting |
| pin | int | Pin number the sensor is connected to |
| atten | int | Attenuation - set to 11(dB) See [Espressif](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/adc.html) documentation for details |
| zero_voltage | float | Sensor output voltage at 0(zero) amps - 2.5v for the ACS5712 20A sensor |
| max_voltage | float | Voltage at max amperage - 5v for ACS5712 20Asensor |
| max_adc_read | 4095 | Don't change, this is the maximum value returned from the ADC read call.  This will represent 3.3v |
| max_amperage | 20 | Max amperage of the ACS5712 |

UART configuration provides the serial connectivity to the host that will be sending commands and receiving logging data from the microcontroller.

NOTE:  The UART described here is in addition to the standard REPL serial interface.

> The plan is to add IP connectivity as an option for connectivity at a later date

| Field | Type | Description |
| --- | --- | --- |
| uart | int | UART number to pin mapping can be found in the [Micropython Documentation](https://docs.micropython.org/en/latest/esp32/quickref.html#uart-serial-bus)|
| baudrate | int | Baudrate for serial interface.  Using 115200 |

> For connectivity to the monitoring system, I am using a CP2102 based USB to TTL module available on [Amazon](https://www.amazon.com/gp/product/B01N47LXRA/ref=ppx_yo_dt_b_search_asin_title?ie=UTF8&psc=1).

## Operation
Once the configuration is in place the microcontroller will come up into an idle state until commands are received from the monitoring station.  The intent here is a baseline should be run with no load on the sensor PRIOR to connecting the equipment to be monitored.  This will ensure the most accurate reading.

The following commands are accepted by the microcontroller over the UART interface configured above.

> All commands from the management station must begin with "CMD:..." and end with a newline character.

| Command | Description |
| --- | --- |
| CMD:INIT\n | Initalize the ADC based ammeter.  Ammeter should have NO LOAD to zeroize the reading. |
| CMD:INTERVAL:{ms}\n | Set a sampling interval in milliseconds for a pin (RAM only, does not update config file). |
| CMD:START[:{timeout}]\n | Start the sampling.  Timeout is 600 seconds if none is provided. |
| CMD:STOP\n | Stop the sampling. |
| CMD:ONE\n | Make a single reading and return the result. |
| CMD:STATUS\n |  Return the current status |
| CMD:CONFIG\n | Return the current configuration in the following: CONFIG:{interval}:{pin}:{name}[:{pin}:{name}...] |

## CMD Examples
Using a management station (in my case a Raspberry Pi 4B) connected to the microcontroller UART (via the CP2102 usb to TTL), the following Python can be used to send commands and receive data.

> The python code requires the pySerial package

    pip3 install -U pyserial

> The following python will open the connection, get the status and configuration, as well as send the init and start commands.  All text commands need to be encoded prior to sending.

    import serial
    ser = serial.Serial('/dev/ttyUSBX', baudrate=115200)
    ser.write('CMD:CONFIG\n'.encode())
    ser.read(ser.in_waiting)
    >>> b'CONFIG:100:30:30:32:sensor1pin32:2828\n'
    ser.write('CMD:STATUS\n'.encode())
    >>> b'STATUS:READY:0\n'
    ser.write('CMD:START:5\n'.encode())
    >>> b'START:707603457\nDATA:sensor1pin32:0:0.7413919:[0, 0, 0]:0.0\nDATA:sensor1pin32:117:0.6640293:[0, 0, 0.6640293]:0.2213431\nDATA:sensor1pin32:247:1.018608:[0, 0.6640293, 0.7413919]:0.4684738\nDATA:sensor1pin32:373:1.998535:[0.6640293, 0.7413919, 1.018608]:0.8080098\nDATA:sensor1pin32:497:0.7413919:[0.7413919, 0.7413919, 1.018608]:0.8337973\nDATA:sensor1pin32:617:0.9025641:[0.7413919, 0.9025641, 1.018608]:0.8875215\n...<output omitted>...STOP:707603462\n'

## Data Responses
All data is returned in a similar format to the CMD messages:

| Response | Description |
| --- | --- |
| STATUS:{INITIALIZING\|RUNNING\|NOINIT}[:{TIMEOUT}][:{PIN}] | The timeout value is only present if running or initializing.  The timeout is the remaining time the task will run. |
| CONFIG:{INTERVAL}:{TIMEOUT}:{INIT_TIMEOUT}:{PIN}:{NAME}:{BASELINE}:... | interval=time in ms between samples, timeout=default time when start requested, init_timeout=length of time for the init/baseline, pin=pin for the ADC, name=name given in the config, baseline=baseline 0amp value learned from the init |
| START:{TIMESTAMP} | timestamp from the microcontroller when the sampling started. NOTE: micropython doesn't use EPOCH on microcontrollers, this value is only useful for comparison to the stop time |
| STOP:{TIMESTAMP} | timestamp from the microcontroller when the sampling stopped |
| DATA:{NAME}:{TICKS}:{AMPS}:{LAST_READS}:{AVERAGE} | name=name or pin of the ADC, ticks=milliseconds since the sampling started, amps=latest amerage reading, last_reads=list of the last reads that were averaged, average=average amperage reading from the reads listed |

