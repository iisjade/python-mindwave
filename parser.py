import struct
from time import time
import serial
# import from numpy import mean # kjs May 2013 Not used in script
"""
work in progress - refactoring data acquisition routines - df 15 May 2013
original code from https://github.com/akloster/python-mindwave
"""
class UtilityFunctions:
  def __init__(self):
    pass
  def write_esense_attention(self, file_handle, value):
    if file_handle:
      file_handle.write("%i\n" % value)
  def write_esense_meditation(self, file_handle, value):
    if file_handle:
      file_handle.write("%i\n" % value)
  def write_raw(self, file_handle, counter, value):
    if file_handle:
      file_handle.write("%i, %i\n" % (counter, value))
  def write_packet(self, file_handle, bval, nval):
    if file_handle:
      file_handle.write("%i|%s\n" % (bval, nval))

class MindWavePacketCodeVals:
  def __init__(self):
    self.standby = 0xd4
    self.connected = 0xd0
    self.raw_value = 0x80
    self.poor_signal = 0x02
    self.esense_attention = 0x04
    self.esense_meditation = 0x05
    self.sensor_data = 0x83

class MindWaveSerialPort:
  def __init__(self):
    self.port = '/dev/ttyUSB0'
    self.baudrate = 115200
    self.timeout = 0.0001
    self.dongle = serial.Serial(port=self.port, baudrate=self.baudrate, timeout=self.timeout)

class Parser:
  def __init__(self):
    self.utility = UtilityFunctions()
    self.parser = self.run()
    self.parser.next()  # init generator
    self.current_vector = []
    self.raw_values = []
    self.current_meditation = 0
    self.current_attention= 0
    self.current_spectrum = []
    self.sending_data = False
    self.state ="initializing"
    self.raw_file = None
    self.esense_file = None
    self.packet_file = None
    self.packet_code = MindWavePacketCodeVals()
    self.serial = MindWaveSerialPort()
    self.dongle = self.serial.dongle
    
  def update(self):
    bytes = self.dongle.read(1000)
    # bytes = self.dongle.read(5000) kjs May 2013
    for b in bytes:
      self.parser.send(ord(b))  # Send each byte to the generator

  def write_serial(self, string):
    self.dongle.write(string)
  
  def start_raw_recording(self, file_name):
    self.raw_file = file(file_name, "wt")
    self.raw_start_time = time()

  def start_packet_recording(self, file_name):
    self.packet_file = file(file_name, "wt")
    self.byte_start_time = time()

  def start_esense_recording(self, file_name):
    self.esense_file = file(file_name, "wt")
    self.esense_start_time = time()

  def stop_raw_recording(self):
    if self.raw_file:
      self.raw_file.close()
      self.raw_file = None
    
  def stop_packet_recording(self):
    if self.packet_file:
      a = 1
      self.utility.write_packet(self.packet_file, a)
      self.packet_file.close()
      self.packet_file = None

  def stop_esense_recording(self):
    if self.esense_file:
      self.esense_file.close()
      self.esense_file = None

  def run(self):
    """
      This generator is a convoluted mess - df May 2013
    """
    self.buffer_len = 512*3  # hmmm ... - df May 2013
    counter = 0
    while True:
      # first, check packet sync
      # packet synced by 0xaa 0xaa
      byte = yield
      if byte != 0xaa:
        self.utility.write_packet(self.packet_file, byte, "!0xaa")
        continue
      byte = yield
      if byte != 0xaa:
        self.utility.write_packet(self.packet_file, byte, "!0xaa")
        continue
      # packet sync confirmed
      # read length and code
      packet_length = yield
      self.utility.write_packet(self.packet_file, packet_length, "packet_length")
      packet_code = yield
      self.utility.write_packet(self.packet_file, packet_code, "packet_code")
      if packet_code == self.packet_code.standby:  # 0xd4
        self.dongle_state= "standby"
        continue
      if packet_code == self.packet_code.connected:  # 0xd0
        self.dongle_state = "connected"
        continue
      self.sending_data = True
      left = packet_length - 2
      while left > 0:
        counter += 1
        self.utility.write_raw(self.raw_file, counter, 0-counter)
        if packet_code == self.packet_code.raw_value:  # 0x80
          row_length = yield
          self.utility.write_packet(self.packet_file, row_length, "row_length")
          a = yield
          self.utility.write_packet(self.packet_file, a, "a")
          b = yield
          self.utility.write_packet(self.packet_file, b, "b")
          value = struct.unpack("<h",chr(a)+chr(b))[0]
          self.raw_values.append(value)
          if len(self.raw_values) > self.buffer_len:
            self.raw_values = self.raw_values[ -self.buffer_len: ]
          left -= 2
          self.utility.write_raw(self.raw_file, counter, value)
        elif packet_code == self.packet_code.poor_signal:  # 0x02
          a = yield
          self.poor_signal = a
          if a > 0:
            pass 
          left -= 1
          self.utility.write_raw(self.raw_file, counter, a)
        elif packet_code == self.packet_code.esense_attention:  #  0x04
          a = yield
          if a > 0 :
            v = struct.unpack("b",chr(a))[0]
            if v > 0:
              self.current_attention = v
              self.utility.write_esense_attention(self.esense_file, v)
          left -= 1
        elif packet_code == self.packet_code.esense_meditation:  #  0x05
          a = yield
          if a > 0:
            v = struct.unpack("b",chr(a))[0]
            if v > 0:
              self.current_meditation = v
              self.utility.write_esense_meditation(self.esense_file, v)
          left -= 1
        elif packet_code == self.packet_code.sensor_data:  # 0x83
          vlength = yield
          self.current_vector = []
          for row in range(8):
            a = yield
            b = yield
            c = yield
            value = a*255*255+b*255+c
            self.current_vector.append(value)
          left -= vlength
        packet_code = yield

