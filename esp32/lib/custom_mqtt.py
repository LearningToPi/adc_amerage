import gc
from time import localtime, time
from uerrno import EINPROGRESS, ETIMEDOUT
from umqtt import simple
import usocket as socket
import utime
import ussl
from loglevel import log_str, INFO

#from umqtt.simple import MQTTException
gc.collect()
BUSY_ERRORS = [EINPROGRESS, ETIMEDOUT, 118, 119]


def qos_check(qos):
    if not (qos == 0 or qos == 1):
        raise ValueError('Only qos 0 and 1 are supported.')


class mqtt_custom(simple.MQTTClient):
    """ Override functions in the robust umqtt class to fix error issues """
    DELAY = 2
    DEBUG = False
    TZ = -7
    TZ_NAME = 'MST'

    def delay(self):
        utime.sleep(self.DELAY)

    def localtime(self, string=True):
        """ returns the current localtime """
        now_tz = localtime(time() + self.TZ * 3600)
        if string:
            return f'{now_tz[0]}-{now_tz[1]}-{now_tz[2]} {"0" + str(now_tz[3]) if now_tz[3] < 10 else now_tz[3] }:{"0" + str(now_tz[4]) if now_tz[4] < 10 else now_tz[4] }:{"0" + str(now_tz[5]) if now_tz[5] < 10 else now_tz[5]} {self.TZ_NAME}'
        return now_tz

    def log(self, in_reconnect, e, level=INFO):
        if self.DEBUG:
            if in_reconnect:
                print(f'{self.localtime()} - {log_str(level)} - MQTT Reconnect: {e}')
                #print(f"mqtt reconnect: {e}")
            else:
                print(f'{self.localtime()} - {log_str(level)} - MQTT: {e}')
                #print(f"mqtt: {e}")

    def connect(self, clean_session=True):
        if isinstance(self.sock, socket.socket):
            self.log(True, "Closing existing socket...")
            self.sock.close()
            self.sock = None
            self.log(True, "Existing socket closed")
        gc.collect()
        self.sock = socket.socket()
        addr = socket.getaddrinfo(self.server, self.port)[0][-1]
        #### tdunteman - added try except with raise only if not a busy error
        try:
            self.sock.settimeout(10.0)
            self.sock.connect(addr)
        except OSError as e:
            print(f"connect error: {e}")
            if e.args[0] not in BUSY_ERRORS:
                raise
        if self.ssl:
            gc.collect()
            self.sock = ussl.wrap_socket(self.sock, **self.ssl_params)

        premsg = bytearray(b"\x10\0\0\0\0\0")
        msg = bytearray(b"\x04MQTT\x04\x02\0\0")

        sz = 10 + 2 + len(self.client_id)
        msg[6] = clean_session << 1
        if self.user is not None:
            sz += 2 + len(self.user) + 2 + len(self.pswd)
            msg[6] |= 0xC0
        if self.keepalive:
            assert self.keepalive < 65536
            msg[7] |= self.keepalive >> 8
            msg[8] |= self.keepalive & 0x00FF
        if self.lw_topic:
            sz += 2 + len(self.lw_topic) + 2 + len(self.lw_msg)
            msg[6] |= 0x4 | (self.lw_qos & 0x1) << 3 | (self.lw_qos & 0x2) << 3
            msg[6] |= self.lw_retain << 5

        i = 1
        while sz > 0x7F:
            premsg[i] = (sz & 0x7F) | 0x80
            sz >>= 7
            i += 1
        premsg[i] = sz

        self.sock.write(premsg, i + 2)
        self.sock.write(msg)
        # print(hex(len(msg)), hexlify(msg, ":"))
        self._send_str(self.client_id)
        if self.lw_topic:
            self._send_str(self.lw_topic)
            self._send_str(self.lw_msg)
        if self.user is not None:
            self._send_str(self.user)
            self._send_str(self.pswd)
        #### tdunteman - switch to new read with error handling
        # msg = self.sock.read(4)
        resp = self._sock_read(4)
        assert resp[0] == 0x20 and resp[1] == 0x02
        if resp[3] != 0:
            raise simple.MQTTException(resp[3])
        return resp[2] & 1

    def _sock_read(self, *args):
        """ Read function to handle errors """
        data = b''
        try:
            msg = self.sock.read(*args)
        except OSError as e:
            print(f'read error: {e}')
            if e.args[0] not in BUSY_ERRORS:
                raise
        if msg == b'': ## connection closed by host
            raise OSError(-1)
        if msg is not None:
            data = b''.join((data, msg))
        return data

    def reconnect(self):
        i = 0
        while 1:
            try:
                self.log(False, "Attempting Reconnect...")
                self.connect(True)
                print("MQTT Reconnect Successful")
                return
            except OSError as e:
                print("RECONNECT ERROR")
                self.log(True, e)
                gc.collect()
                i += 1
                self.delay(i)

    def wait_msg(self):
        while 1:
            try:
                return super().wait_msg()
            except OSError as e:
                self.log(False, e)
            return self.reconnect()

    def check_msg(self):
        self.sock.setblocking(False)
        return self.wait_msg()

    def publish(self, topic, msg, retain=False, qos=0):
        while 1:
            try:
                return super().publish(topic, msg, retain, qos)
            except OSError as e:
                self.log(False, e)
            self.reconnect()
