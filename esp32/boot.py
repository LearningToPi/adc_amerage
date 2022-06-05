# boot.py - - runs on boot-up
import os
import re
import sys
import machine
import esp32

config_file = 'config.json'
machine.freq(240000000)


print('==============================')
print('Booting...')
print('    ' + re.sub(', ', '\n    ',
        re.sub("[()']", "",
            str(os.uname()))
            ))
print(f"CPU Freq: {machine.freq() / 1000 / 1000 } Mhz")
print(f"Internal Temp: {esp32.raw_temperature()} deg F")
print('==============================')

sys.path.append('/lib')
