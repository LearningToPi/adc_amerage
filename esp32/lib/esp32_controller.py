import json
from time import sleep, localtime, time
import network
#from umqtt.robust import MQTTClient
import ntptime
from custom_mqtt import mqtt_custom as MQTTClient
from loglevel import log_str, DEBUG, INFO, ERROR


class BaseESP32Worker:
    """ Class to contain the work.  Manages the config file and all working threads or processes """
    def __init__(self, config_file='config.json'):
        self._config_file = config_file
        self._update_functions = []
        self.wlan = None
        self.config = {}
        self.mqtt = None
        self.load_config_file()
        self.network_ready()
        if 'mqtt' in self.config:
            self.mqtt_connect()
        self.run()

    def load_config_file(self):
        """ Reload the config file from flash and build a list of functions to call to reload """
        try:
            self.log(f'Opening local config file "{self._config_file}"...')
            input_file = open(self._config_file, 'r', encoding='utf-8')
            self.config = json.loads(input_file.read())
            input_file.close()
            return True
        except Exception as e:
            self.log(f'Cannot open config file. Error: {e}', ERROR)
        return False

    def write_config_file(self):
        """ Writes the config to flash """
        try:
            if isinstance(self.config) == dict and self.config != {}:
                self.log(f'Writing local config file "{self._config_file}"...')
                with open(self._config_file, 'w', encoding='utf-8') as output_file:
                    json.dump(self.config, output_file)
                return True
        except Exception as e:
            self.log(f'Cannot write config file: {e}', ERROR)
        return False

    def update_config(self, new_config:dict):
        """ Update the config with a dict """
        self.config = new_config
        self.write_config_file()
        return True

    def network_ready(self):
        """ Check and connect to the network """
        if self.wlan is None or not self.wlan.isconnected():
            try:
                self.log(f"Connecting to network ssid {self.config['network']['ssid']}...", level=INFO)
                self.wlan = network.WLAN(network.STA_IF)
                self.wlan.active(True)
                self.wlan.disconnect()
                self.wlan.connect(self.config['network']['ssid'], self.config['network']['psk'])
                while not self.wlan.isconnected():
                    self.log("Waiting for wireless to connect...", DEBUG)
                    sleep(1)
                # sync time
                self.log(f'Syncing time to {self.config.get("ntp_server", "0.us.pool.ntp.org")}...', INFO)
                ntptime.host = self.config.get('ntp_server', '0.us.pool.ntp.org')
                ntptime.settime()
            except Exception as e:
                self.log(f'Error connecting to wifi: {e}', ERROR)
                self.wlan.active(False)
                self.wlan = None

        # if webrepl is set to enabled, turn it on now
        if 'webrepl' in self.config and self.config['webrepl'].get('enabled', False) and self.config['webrepl'].get('password', None) is not None:
            import webrepl
            with open('webrepl_cfg.py', 'w', encoding='utf-8') as output_file:
                output_file.write(f"PASS = {self.config['webrepl']['password']}\n")
            webrepl.start(password=self.config['webrepl']['password'])

        return self.wlan.isconnected() if self.wlan is not None else False

    def mqtt_connect(self):
        """ Connect to MQTT server if not connected """
        if self.mqtt is not None:
            try:
                #self.mqtt.sock.close()
                self.mqtt.disconnect()
            except Exception as e:
                self.log(f"Error disconnecting from MQTT: {e}", ERROR)
            self.mqtt = None
        try:
            self.log(f'Connecting to MQTT {self.config["mqtt"]["config"]["server"]}:{self.config["mqtt"]["config"]["port"]}...', INFO)
            self.mqtt = MQTTClient(**self.config['mqtt']['config'])
            self.mqtt.DEBUG = True
            self.mqtt.connect()
            self.log(f"Conneted to MQTT {self.config['mqtt']['config']['server']}:{self.config['mqtt']['config']['port']}", DEBUG)
            if 'lwt' in self.config['mqtt']:
                self.log('Sending LWT Mesage...', INFO)
                self.mqtt.set_last_will(**self.config['mqtt']['lwt'])
                self.log("Sent LWT Message", DEBUG)
            if 'online' in self.config['mqtt']:
                self.log('Sending online message...', INFO)
                self.mqtt.publish(**self.config['mqtt']['online'])
                self.log("Sent Connected Message", DEBUG)
            if 'subscribe' in self.config['mqtt']: # and len(self.config['mqtt']['subscribe']) > 0:
                self.log("Subscribing to topics...", INFO)
                self.mqtt.set_callback(self.mqtt_process_callback)
                for subscription in self.config['mqtt']['subscribe']:
                    self.log(f'Subscribing to {subscription["topic"]}...', INFO)
                    self.mqtt.subscribe(**subscription)
                    self.log(f'Subscribed to {subscription["topic"]}', DEBUG)
                self.log('Checking for pending MQTT Messages...', INFO)
                self.mqtt.check_msg()
        except Exception as e:
            self.log(f"Error connecting to MQTT: {e}", ERROR)
            self.mqtt = None

    def mqtt_send(self, **kwargs):
        """ Send an mqtt message with error handling to reconnect """
        try:
            self.log(f'Sending MQTT message to {kwargs["topic"] if "topic" in kwargs.keys() else "???"}...', DEBUG)
            self.mqtt.publish(**kwargs)
        except Exception as e:
            self.log(f'Error sending MQTT message: {e}', ERROR)
            self.mqtt_connect()

    def mqtt_ping(self):
        """ Send an mqtt ping with error handling """
        try_count = 0
        while True:
            try_count += 1
            try:
                return self.mqtt.ping()
            except Exception as e:
                self.log(f'Error pinging MQTT server, try {try_count}: {e}', ERROR)
                sleep(5)
                if try_count >= self.config['mqtt'].get('retry', 3):
                    self.mqtt_connect()

    def mqtt_check_msg(self):
        """ Check for mqtt message with error handling """
        try:
            self.mqtt.check_msg()
        except Exception as e:
            self.log(f'Error checking messages from MQTT server: {e}', ERROR)
            self.mqtt_connect()

    def mqtt_process_callback(self, topic, message):
        """ Function to be over ridden as needed to process received MQTT messges """
        self.log(f'Message Received: {topic.decode()}, {message.decode()}', INFO)

    def run(self):
        """ Function to be over ridden on a per device basis """
        self.log('No run code was provided', INFO)
        return

    def localtime(self, string=True):
        """ returns the current localtime """
        tz = self.config.get('timezone', -7) if self.config is not None else 0
        now_tz = localtime(time() + tz * 3600)
        if string:
            return f'{now_tz[0]}-{now_tz[1]}-{now_tz[2]} {"0" + str(now_tz[3]) if now_tz[3] < 10 else now_tz[3] }:{"0" + str(now_tz[4]) if now_tz[4] < 10 else now_tz[4] }:{"0" + str(now_tz[5]) if now_tz[5] < 10 else now_tz[5]} {"UTC" if tz == 0 else self.config.get("timezone_name", "ERR")}'
        return now_tz

    def log(self, message, level=INFO, console=True):
        """ Log the message """
        if console and (self.config is None or level <= self.config.get('logging_console', INFO)):
            print(f'{self.localtime()} - {log_str(level)} - {message}')
