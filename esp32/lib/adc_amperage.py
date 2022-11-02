import time
import _thread
import gc
import uasyncio
from machine import ADC, Pin, UART, freq
from loglevel import INFO, ERROR, DEBUG
from esp32_controller import BaseESP32Worker
from utime import ticks_ms, ticks_diff, sleep_ms


# UART/Ethernet command list - 'LIST' is explicitly supported and returns a list of the commands
COMMAND_LIST = [
    'CMD:INIT\\n - Initalize the ADC based ammeter.  Ammeter should have NO LOAD to zeroize the reading.',
    'CMD:INTERVAL:{ms}\\n - Set a sampling interval in milliseconds for a pin (RAM only, does not update config file).',
    'CMD:START[:{timeout}]\\n - Start the sampling.  Timeout is 600 seconds if none is provided.',
    'CMD:STOP\\n - Stop the sampling.',
    'CMD:ONE\\n - Make a single reading and return the result.',
    'CMD:STATUS\\n - Return the current status',
    'CMD:CONFIG\\n - Return the current configuration in the following: CONFIG:{interval}:{pin}:{name}[:{pin}:{name}...]'
]

class AdcAmperage(BaseESP32Worker):
    def __init__(self, **kwargs):
        self._stop_led = None
        self.switch_state = None
        self.init_stop_time = None
        self.baseline_task = None
        self.sampling_task = None
        self.sampling_stop_time = None
        super().__init__(**kwargs)

    def run(self):
        """ Setup the ADC pins """
        self.log('Starting sensors...', INFO)
        self.uart_write_lock = _thread.allocate_lock()
        try:
            for adc_conf in self.config['adc']['pins']:
                self.log(f"Creating ADC on pin {adc_conf['pin']}", INFO)
                adc_conf['obj'] = ADC(Pin(adc_conf['pin']))
                if adc_conf.get('atten', 0) == 11:
                    atten_value = ADC.ATTN_11DB
                elif adc_conf.get('atten', 0) == 2.5:
                    atten_value = ADC.ATTN_2_5DB
                elif adc_conf.get('atten', 0) == 6:
                    atten_value = ADC.ATTN_6DB
                else:
                    atten_value = ADC.ATTN_0DB
                adc_conf['obj'].atten(atten_value)
                self.log(f"Initial read for {adc_conf.get('name', adc_conf['pin'])}:{adc_conf['obj'].read_uv()/1000.0}", DEBUG)

        except Exception as e:
            self.log(f'Error configuring ADC: {e}', ERROR)
            exit(1)

        # Create a variable to hold a break to stop reading as well as running status
        self.break_read = False
        self.sampling_task = False
        self.sampling_stop_time = time.time()
        self.baseline_task = False
        self.init_stop_time = time.time()

        # Opening the UART interface to send data and receive commands
        if 'uart' in self.config:
            self.log(f"Openning UART with {self.config['uart']}...", INFO)
            try:
                temp_config = self.config['uart'].copy()
                uart_id = temp_config.pop('uart', None)
                self.log(f"Openning UART with {temp_config}...", INFO)
                if uart_id is not None:
                    self.uart = UART(uart_id, **temp_config)
                else:
                    self.uart = UART(**temp_config)
            except Exception as e:
                self.log(f'Error configuring UART: {e}', ERROR)
                exit(2)
        else:
            self.uart = None

        # If init_button is configured, create the objects and start the async thread
        self.init_pin = None
        self.led_pin = None
        self._lock = _thread.allocate_lock()
        if 'init_button' in self.config and isinstance(self.config['init_button'].get('button_pin', None), int):
            self.log(f"Initializing init button on pin {self.config['init_button'].get('button_pin')}...")
            self.init_pin = Pin(self.config['init_button']['button_pin'], pull=Pin.PULL_DOWN, mode=Pin.IN)
            self.switch_state = self.init_pin.value
            uasyncio.create_task(self.button_loop(debounce=self.config['init_button'].get('debouce', 200)))
            if isinstance(self.config['init_button'].get('led_pin', None), int):
                self.log(f"Initializing LED on pin {self.config['init_button'].get('led_pin')}...")
                self.led_pin = Pin(self.config['init_button']['led_pin'], mode=Pin.OUT, value=0)
                self._stop_led = True

        # set the cpu frequency to the minimum
        freq(80000000)

        # start the async main loop
        uasyncio.run(self.main_loop())

    async def main_loop(self):
        """ Main processing loop """
        while True:
            # check for UART data received
            if self.uart is not None:
                if self.uart.any():
                    data = self.uart.readline().decode('utf-8')
                    self.log("RECEIVED: " + data.replace('\n', '\\n'), DEBUG)
                    if len(data) >= 8: # 8 is the minimum command length! CMD:ONE\n
                        if data[0:4] == 'CMD:' and data[-1] == '\n':
                            data_parts = data.split(':')
                            if len(data_parts) >= 2:
                                # check and perform actions on supported commands
                                if data_parts[1].replace('\n', '') == 'LIST':
                                    for command in COMMAND_LIST:
                                        with self.uart_write_lock:
                                            self.uart.write(f"{command}\n")

                                elif data_parts[1].replace('\n', '') == 'INIT':
                                    uasyncio.create_task(self.baseline_ammeter())

                                elif data_parts[1].replace('\n', '') == 'STATUS':
                                    with self.uart_write_lock:
                                        self.uart.write(f"{self.get_status}\n")

                                elif data_parts[1].replace('\n', '') == 'CONFIG':
                                    with self.uart_write_lock:
                                        self.log(f'{self.get_config}', DEBUG)
                                        self.uart.write(f"{self.get_config}\n")

                                elif data_parts[1].replace('\n', '') == 'INTERVAL':
                                    self.log('Received INTERVAL Command.  Setting sampling interval (in ram only, does not update the config file).', DEBUG)
                                    if len(data_parts) >= 3:
                                        self.config['adc']['interval'] = int(data_parts[2])

                                elif data_parts[1].replace('\n', '') == 'START':
                                    if not self.sampling_task:
                                        _thread.start_new_thread(self.start_sampling, () if len(data_parts) < 3 else (int(data_parts[2]),))

                                elif data_parts[1].replace('\n', '') == 'STOP':
                                    uasyncio.create_task(self.stop_sampling())

                                elif data_parts[1].replace('\n', '') == 'ONE':
                                    uasyncio.create_task(self.read_ammeter())

                                else:
                                    self.log("Unknown command:" + data.replace('\n', ''), ERROR)
                                    with self.uart_write_lock:
                                        self.uart.write(f"ERROR:Unknown Command {data}")
                            else:
                                self.log("Unknown command:" + data.replace('\n', ''), ERROR)
                                with self.uart_write_lock:
                                    self.uart.write(f"ERROR:Unknown Command {data}")
                        else:
                            self.log("Unknown command:" + data.replace('\n', ''), ERROR)
                            with self.uart_write_lock:
                                self.uart.write(f"ERROR:Unknown Command {data}")
                    else:
                        self.log("Unknown command:" + data.replace('\n', ''), ERROR)
                        with self.uart_write_lock:
                            self.uart.write(f"ERROR:Unknown Command {data}")
                await uasyncio.sleep_ms(100)

    async def button_loop(self, debounce=200):
        """ Async process to check for a button press - pressing will start the init process """
        self.log("Starting async button loop...")
        while True:
            state = self.init_pin.value()
            if state != self.switch_state:
                # switch state changed
                self.switch_state = state
                if state == 1:
                    # trigger
                    self.log("Init button press identified.  Calling sensor init...")
                    uasyncio.create_task(self.baseline_ammeter())

            # wait the debounce interval before rechecking
            await uasyncio.sleep_ms(debounce)

    async def led_flash(self, timeout=60, flashrate=.5):
        """ Async process to flash the LED """
        if self.led_pin is not None:
            with self._lock:
                self._stop_led = False
            start_ticks = ticks_ms()
            while not self._stop_led and ticks_diff(ticks_ms(), start_ticks) < timeout * 1000:  # type: ignore
                self.led_pin.on()
                await uasyncio.sleep_ms(int(flashrate * 1000))
                self.led_pin.off()
                await uasyncio.sleep_ms(int(flashrate * 1000))

    @property
    def get_status(self) -> str:
        """ get the current state and return as a string:
            NOINIT - not yet initialized
            INITIALIZING - initialization in progress
            READY - initialized and ready to start sampling
            RUNNING - currently sampling
        """
        if self.baseline_task:
            message = f"STATUS:INITIALIZING:{round(self.init_stop_time - time.time(), 2)}"
            self.log(message, DEBUG)
            return message
        if self.sampling_task:
            message = f"STATUS:RUNNING:{round(self.sampling_stop_time - time.time(), 2)}"
            self.log(message, DEBUG)
            return message
        for adc_conf in self.config['adc']['pins']:
            if adc_conf.get('baseline', None) is None:
                message = f"STATUS:NOINIT:{adc_conf.get('name', adc_conf['pin'])}"
                self.log(message, DEBUG)
                return message
        self.log("STATUS:READY:0", DEBUG)
        return "STATUS:READY:0"

    @property
    def get_config(self) -> str:
        """ Get the current configuration and return in the following format:
            CONFIG:{interval}:{timeout}:{baseline_time}:{pin}:{name}:{baseline}[:{pin}:{name}:{baseline}...]
        """
        config_line = f"CONFIG:{self.config['adc'].get('interval', 100)}:{self.config['adc'].get('timeout', 600)}:{self.config['adc'].get('baseline_time', 10)}"
        for adc_config in self.config['adc']['pins']:
            config_line = f"{config_line}:{adc_config['pin']}:{adc_config.get('name', 'n/a')}:{adc_config.get('baseline', 0)}"
        self.log(config_line, DEBUG)
        return config_line

    async def baseline_ammeter(self) -> None:
        """ initialize the ammeter reading.  Assumption is there is no load on the circuit.
            Length of test can be modified in the config file """
        # if sampling is in progress, stop it first
        self.baseline_task = True
        if self.sampling_task:
            await self.stop_sampling()
        uasyncio.create_task(self.led_flash())
        # set freq to max
        freq(240000000)

        self.log('baseline start', DEBUG)
        # Start the sampling
        init_seconds = self.config['adc'].get('baseline_time', 10)
        for adc_conf in self.config['adc']['pins']:
            self.init_stop_time = time.time() + init_seconds
            self.log(f"Starting baseline of the ADC Ammeter. Running for {init_seconds} seconds on {adc_conf.get('name', adc_conf['pin'])}", INFO)
            value_list = []
            while time.time() < self.init_stop_time:
                # Read the ADC
                value_list.append(adc_conf['obj'].read_uv())
                gc.collect()
                await uasyncio.sleep_ms(self.config['adc'].get('interval', 100))
            # calculate baseline value
            adc_conf['baseline'] = int(sum(value_list) / len(value_list))
            self.log(f"{adc_conf.get('name', adc_conf['pin'])} baseline is {adc_conf['baseline']}", INFO)

        self.baseline_task = False
        with self._lock:
            self._stop_led = True
        # set the cpu frequency to the minimum
        freq(80000000)

    def start_sampling(self, timeout=None) -> None:
        """ Start sampling on all pins using sampling rate """
        if not self.sampling_task:
            self.sampling_task = True
            uasyncio.create_task(self.led_flash())
            # set freq to max
            freq(240000000)

            # set the stoptime
            self.sampling_stop_time = time.time() + (timeout if timeout is not None else self.config['adc'].get('timeout', 600))

            # create a list to hold X number of records to average in
            for adc_conf in self.config['adc']['pins']:
                adc_conf['log'] = [0] * self.config['adc'].get('avg_count', 5)
            self.log(f"Starting amperage sampling for all pins. Stop in {self.config['adc'].get('timeout', 600)} seconds", INFO)

            # write the start time back for marking purposes
            with self.uart_write_lock:
                self.uart.write(f'START:{time.time()}\n')

            # read count used to populate the log
            read_count = self.config['adc'].get('avg_count', 5)
            start_ticks = ticks_ms()
            while time.time() < self.sampling_stop_time:
                record = "DATA"
                for adc_conf in self.config['adc']['pins']:
                    ticks = ticks_diff(ticks_ms(), start_ticks)
                    amps = _calc_amperage(adc_conf['obj'].read_uv(), adc_conf.get('baseline', 2450000), adc_conf.get('mv_per_a', 185))
                    adc_conf['log'][read_count % self.config['adc'].get('avg_count', 5)] = amps
                    # discard highest and lowest value
                    log_temp = adc_conf['log'].copy()
                    log_temp.sort()
                    log_temp = log_temp[1:len(log_temp) - 1]
                    record += f":{adc_conf.get('name', adc_conf['pin'])}:{ticks}:{amps}:{log_temp}:{sum(log_temp) / len(log_temp)}"
                read_count += 1
                with self.uart_write_lock:
                    self.uart.write(f"{record}\n")

                sleep_ms(self.config['adc'].get('interval', 100))

            with self.uart_write_lock:
                self.log(f'STOP:{time.time()}', DEBUG)
                self.uart.write(f'STOP:{time.time()}\n')
            self.log('Stopping amperage sampling for all pins.')
            self.sampling_task = False
            with self._lock:
                self._stop_led = True
            # set the cpu frequency to the minimum
            freq(80000000)

    async def stop_sampling(self) -> None:
        """ Stop the sampling task by changing to stop time to now """
        if self.sampling_task:
            self.log("Stop of samling requested.", INFO)
            self.sampling_stop_time = time.time()
            # wait for 2x the interval
            await uasyncio.sleep_ms(self.config['adc'].get('interval', 100) * 2)

            if self.sampling_task:
                with self.uart_write_lock:
                    self.uart.write('ERROR:unable to stop sampling\n')

    async def read_ammeter(self) -> None:
        """ Perform a read of the ammeter using the  """
        # read count used to populate the log
        self.log('Starting single read', DEBUG)
        read_count = self.config['adc'].get('avg_count', 5)
        for adc_conf in self.config['adc']['pins']:
            adc_conf['log'] = [0] * self.config['adc'].get('avg_count', 5)
        start_ticks = ticks_ms()
        for i in range(read_count):
            for adc_conf in self.config['adc']['pins']:
                ticks = ticks_diff(ticks_ms(), start_ticks)
                amps = _calc_amperage(adc_conf['obj'].read_uv(), adc_conf.get('baseline', 2450000), adc_conf.get('mv_per_a', 185))
                adc_conf['log'][i] = amps
            read_count += 1
            await uasyncio.sleep_ms(self.config['adc'].get('interval', 100))
        record = "DATA"
        for adc_conf in self.config['adc']['pins']:
            record += f":{adc_conf.get('name', adc_conf['pin'])}:{ticks}:{amps}:{adc_conf['log']}:{sum(adc_conf['log']) / len(adc_conf['log'])}"
        with self.uart_write_lock:
            self.log(record, DEBUG)
            self.uart.write(f"{record}\n")


def _calc_amperage(adc_read:int, adc_baseline:int, mv_per_amp:int) -> float:
    """ Calculate the amperage based on the ready, baseline, max amperage of the sensor and zero point voltage of the sensor """
    return ((adc_baseline) - (adc_read)) / (mv_per_amp * 1000.0)
