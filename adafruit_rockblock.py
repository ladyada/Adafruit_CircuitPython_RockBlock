# The MIT License (MIT)
#
# Copyright (c) 2020 Carter Nelson for Adafruit Industries
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
"""
`adafruit_rockblock`
================================================================================

CircuitPython driver for Rock Seven RockBLOCK Iridium satellite modem


* Author(s): Carter Nelson

Implementation Notes
--------------------

**Hardware:**

* `RockBLOCK 9603 Iridium Satellite Modem <https://www.adafruit.com/product/4521>`_

**Software and Dependencies:**

* Adafruit CircuitPython firmware for the supported boards:
  https://github.com/adafruit/circuitpython/releases

"""


import time
import struct

__version__ = "0.0.0-auto.0"
__repo__ = "https://github.com/adafruit/Adafruit_CircuitPython_RockBlock.git"


class RockBlock:
    """Driver for RockBLOCK Iridium satellite modem."""

    def __init__(self, uart, baudrate=19200):
        self._uart = uart
        self._uart.baudrate = baudrate
        self._buf_out = None
        self.reset()

    def _uart_xfer(self, cmd):
        """Send AT command and return response as tuple of lines read."""
        self._uart.reset_input_buffer()
        self._uart.write(str.encode("AT" + cmd + "\r"))

        resp = []
        line = self._uart.readline()
        resp.append(line)
        while not any(EOM in line for EOM in (b"OK\r\n", b"ERROR\r\n")):
            line = self._uart.readline()
            resp.append(line)

        self._uart.reset_input_buffer()

        return tuple(resp)

    def reset(self):
        """Perform a software reset."""
        if self._uart_xfer("&F0") is None:  # factory defaults
            return False
        if self._uart_xfer("&K0") is None:  # flow control off
            return False
        return True

    def _transfer_buffer(self):
        """Copy out buffer to in buffer to simulate receiving a message."""
        self._uart_xfer("+SBDTC")

    @property
    def data_out(self):
        "The binary data in the outbound buffer."
        return self._buf_out

    @data_out.setter
    def data_out(self, buf):
        if buf is None:
            # clear the buffer
            resp = self._uart_xfer("+SBDD0")
            resp = int(resp[1].strip().decode())
            if resp == 1:
                raise RuntimeError("Error clearing buffer.")
        else:
            # set the buffer
            if len(buf) > 340:
                raise RuntimeError("Maximum length of 340 bytes.")
            self._uart.write(str.encode("AT+SBDWB={}\r".format(len(buf))))
            line = self._uart.readline()
            while line != b"READY\r\n":
                line = self._uart.readline()
            # binary data plus checksum
            self._uart.write(buf + struct.pack(">H", sum(buf)))
            line = self._uart.readline()  # blank line
            line = self._uart.readline()  # status response
            resp = int(line)
            if resp != 0:
                raise RuntimeError("Write error", resp)
            # seems to want some time to digest
            time.sleep(0.1)
        self._buf_out = buf

    @property
    def text_out(self):
        """The text in the outbound buffer."""
        text = None
        # TODO: add better check for non-text in buffer
        # pylint: disable=broad-except
        try:
            text = self._buf_out.decode()
        except Exception:
            pass
        return text

    @text_out.setter
    def text_out(self, text):
        if not isinstance(text, str):
            raise ValueError("Only strings allowed.")
        if len(text) > 120:
            raise ValueError("Text size limited to 120 bytes.")
        self.data_out = str.encode(text)

    @property
    def data_in(self):
        """The binary data in the inbound buffer."""
        data = None
        if self.status[2] == 1:
            resp = self._uart_xfer("+SBDRB")
            data = resp[0].splitlines()[1]
            data = data[2:-2]
        return data

    @data_in.setter
    def data_in(self, buf):
        if buf is not None:
            raise ValueError("Can only set in buffer to None to clear.")
        resp = self._uart_xfer("+SBDD1")
        resp = int(resp[1].strip().decode())
        if resp == 1:
            raise RuntimeError("Error clearing buffer.")

    @property
    def text_in(self):
        """The text in the inbound buffer."""
        text = None
        if self.status[2] == 1:
            resp = self._uart_xfer("+SBDRT")
            try:
                text = resp[2].strip().decode()
            except UnicodeDecodeError:
                pass
        return text

    @text_in.setter
    def text_in(self, text):
        self.data_in = text

    def satellite_transfer(self, location=None):
        """Initiate a Short Burst Data transfer with satellites."""
        status = (None,) * 6
        if location:
            resp = self._uart_xfer("+SBDIX=" + location)
        else:
            resp = self._uart_xfer("+SBDIX")
        if resp[-1].strip().decode() == "OK":
            status = resp[-3].strip().decode().split(":")[1]
            status = [int(s) for s in status.split(",")]
            if status[0] <= 8:
                # outgoing message sent successfully
                self.data_out = None
        return tuple(status)

    @property
    def status(self):
        """Return tuple of Short Burst Data status."""
        resp = self._uart_xfer("+SBDSX")
        if resp[-1].strip().decode() == "OK":
            status = resp[1].strip().decode().split(":")[1]
            return tuple([int(a) for a in status.split(",")])
        return (None,) * 6

    @property
    def model(self):
        """Return modem model."""
        resp = self._uart_xfer("+GMM")
        if resp[-1].strip().decode() == "OK":
            return resp[1].strip().decode()
        return None

    @property
    def imei(self):
        """Return modem imei/serial."""
        resp = self._uart_xfer("+CGSN")
        if resp[-1].strip().decode() == "OK":
            return resp[1].strip().decode()
        return None

    @property
    def rssi(self):
        """Return Received Signal Strength Indicator (RSSI)
        values returned are 0 to 5, where 0 is no signal (0 bars) and 5 is strong signal (5 bars).
        Important note: signal strength may not be fully accurate, so
        waiting for high signal strength prior to sending a message isn't always recommended.
        For details see https://docs.rockblock.rock7.com/docs/checking-the-signal-strength
        """
        resp = self._uart_xfer("+CSQ")
        if resp[-1].strip().decode() == "OK":
            return resp[1].strip().decode().split(":")[1]
        return None

    @property
    def version(self):
        """Return the modem components' firmware versions.
        For example: Call Processor Version, Modem DSP Version, DBB Version (ASIC),
        RFA VersionSRFA2), NVM Version, Hardware Version, BOOT Version
        """
        resp = self._uart_xfer("+CGMR")
        if resp[-1].strip().decode() == "OK":
            lines = []
            for x in range(1, len(resp) - 2):
                line = resp[x]
                if line != b"\r\n":
                    lines.append(line.decode().strip())
            return lines
        return None

    @property
    def ring_alert(self):
        """Retrieve setting for SBD Ring Alerts."""
        resp = self._uart_xfer("+SBDMTA?")
        if resp[-1].strip().decode() == "OK":
            return bool(int(resp[1].strip().decode().split(":")[1]))
        return None

    @ring_alert.setter
    def ring_alert(self, value=1):
        """Enable or disable ring alert feature."""
        if value in [True, False]:
            resp = self._uart_xfer("+SBDMTA=" + str(int(value)))
            if resp[-1].strip().decode() == "OK":
                return True
            raise RuntimeError("Error setting Ring Alert.")
        raise ValueError(
            "Use 0 or False to disable Ring Alert or use 0 or True to enable Ring Alert."
        )

    @property
    def ring_indication(self):
        """
        Query the ring indication status, returning the reason for the most recent assertion
        of the Ring Indicate signal.

        The response contains separate indications for telephony and SBD ring indications.
        The response is in the form:
        [<tel_ri>,<sbd_ri>]

        <tel_ri> indicates the telephony ring indication status:
        0 No telephony ring alert received.
        1 Incoming voice call.
        2 Incoming data call.
        3 Incoming fax call.

        <sbd_ri> indicates the SBD ring indication status:
        0 No SBD ring alert received.
        1 SBD ring alert received.
        """
        resp = self._uart_xfer("+CRIS")
        if resp[-1].strip().decode() == "OK":
            return resp[1].strip().decode().split(":")[1].split(",")
        return None

    @property
    def geolocation(self):
        """
        Return the geolocation of the modem as measured by the Iridium constellation
        and the current time based on the Iridium network timestamp.
        The response is in the form:
        [<x>,<y>,<z>,<timestamp>]

        <x>,<y>,<z> is a geolocation grid code from an earth centered Cartesian coordinate system,
        using dimensions, x, y, and z, to specify location. The coordinate system is aligned
        such that the z-axis is aligned with the north and south poles, leaving the x-axis
        and y-axis to lie in the plane containing the equator. The axes are aligned such that
        at 0 degrees latitude and 0 degrees longitude, both y and z are zero and
        x is positive (x = +6376, representing the nominal earth radius in kilometres).
        Each dimension of the geolocation grid code is displayed in decimal form using
        units of kilometres. Each dimension of the geolocation grid code has a minimum value
        of –6376, a maximum value of +6376, and a resolution of 4.
        This geolocation coordinate system is known as ECEF (acronym earth-centered, earth-fixed),
        also known as ECR (initialism for earth-centered rotational)

        <timestamp> is a time_struct
        The timestamp is assigned by the modem when the geolocation grid code received from
        the network is stored to the modem's internal memory.
        The timestamp used by the modem is Iridium system time, which is a running count of
        90 millisecond intervals, since Sunday May 11, 2014, at 14:23:55 UTC.
        The timestamp returned by the modem is a 32-bit integer displayed in hexadecimal form.
        We convert the modem's timestamp and return it as a time_struct.
        """
        resp = self._uart_xfer("-MSGEO")
        if resp[-1].strip().decode() == "OK":
            temp = resp[1].strip().decode().split(":")[1].split(",")
            ticks_since_epoch = int(temp[3], 16)
            ms_since_epoch = (
                ticks_since_epoch * 90
            )  # convert iridium ticks to milliseconds

            # milliseconds to seconds
            # hack to divide by 1000 and avoid using limited floating point math which throws the
            #    calculations off quite a bit, this should be accurate to 1 second or so
            ms_str = str(ms_since_epoch)
            substring = ms_str[0 : len(ms_str) - 3]
            secs_since_epoch = int(substring)

            # iridium epoch
            iridium_epoch = time.struct_time(((2014), (5), 11, 14, 23, 55, 6, -1, -1))
            iridium_epoch_unix = time.mktime(iridium_epoch)

            # add timestamp's seconds to the iridium epoch
            time_now_unix = iridium_epoch_unix + int(secs_since_epoch)

            # convert to time struct
            time_now = time.localtime(time_now_unix)

            values = [
                int(temp[0]),
                int(temp[1]),
                int(temp[2]),
                time_now,
            ]
            return values
        return None

    @property
    def timestamp(self):
        """
        Return the current date and time as given by the Iridium network
        The timestamp is assigned by the modem when the geolocation grid code received from
        the network is stored to the modem's internal memory.
        The timestamp used by the modem is Iridium system time, which is a running count of
        90 millisecond intervals, since Sunday May 11, 2014, at 14:23:55 UTC.
        We convert the modem's timestamp and return it as a time_struct.
        """
        resp = self._uart_xfer("-MSSTM")
        if resp[-1].strip().decode() == "OK":
            temp = resp[1].strip().decode().split(":")[1]
            print(temp)
            if temp == " no network service":
                return None
            ticks_since_epoch = int(temp, 16)
            ms_since_epoch = (
                ticks_since_epoch * 90
            )  # convert iridium ticks to milliseconds

            # milliseconds to seconds\
            # hack to divide by 1000 and avoid using limited floating point math which throws the
            # calculations off quite a bit, this should be accurate to 1 second or so
            ms_str = str(ms_since_epoch)
            substring = ms_str[0 : len(ms_str) - 3]
            secs_since_epoch = int(substring)

            # iridium epoch
            iridium_epoch = time.struct_time(((2014), (5), 11, 14, 23, 55, 6, -1, -1))
            iridium_epoch_unix = time.mktime(iridium_epoch)

            # add timestamp's seconds to the iridium epoch
            time_now_unix = iridium_epoch_unix + int(secs_since_epoch)

            # convert to time struct
            time_now = time.localtime(time_now_unix)

            return time_now
        return None
