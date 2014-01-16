#!/usr/bin/env python

from collections import deque
from itertools import islice
from PyQt4 import QtGui, QtCore
import pyqtgraph as pg
import sys
import time
import serial

#####

class Coordinator(object):
  '''Creates appropriate ensemble of pipeline components.
     Such as: One (or more) Packer.  One UI.'''
  def __init__(self):
    self.analyze = False
    if self.analyze:
      self.analytics = Analytics()
    self.device = Device()
    self.bytestream = Bytestream(self.device)
    self.synced_src = self.bytestream.synced_src()
    self.protocol = ThinkGearProtocol
    self.packer = Packer(self)
    self.connected = False
    self.ui = UI(self)
    self.rp = self.ui.raw_plot()
    self.fp = self.ui.fft_plot()
    self.rp.send(None)
    self.fp.send(None)
    self.ui.app.exec_()
  def connect(self):
    retry_trigger = 2500
    num_attempts = 0
    print "Sending connect"
    self.device.connect()
    while not self.connected and num_attempts < retry_trigger:
      num_attempts += 1 
      p = Packet(self.synced_src)
      if p.codetype() == self.protocol.connected_code:
        self.connected = True
        print "Connected"
    if not self.connected:
      print "Sending disconnect"
      self.device.disconnect()
      time.sleep(2)
      self.connect()
  def disconnect(self):
    self.device.disconnect()
    self.connected = False
  def mainloop(self):
    while self.connected:
      packet = Packet(self.synced_src)
      if packet.is_valid():
        self.packer.payload(packet)
      else if packet.payload:
        print packet.payload

class Bytestream(object):
  def __init__(self, device):
    self.device = device
    self.syncer = deque([], ThinkGearProtocol.syncnum)
    self.src = self.bytevals()
  def bytevals(self):
    while True:
      b = self.device.ser.read()
      if b:
        yield ord(b)
  def synced_src(self):
    '''increments self.src to end of sync signal'''
    self.syncer.clear()
    while self.syncer.count(ThinkGearProtocol.syncbyte) < ThinkGearProtocol.syncnum:
      self.syncer.append(self.src.next())
    return self.src


class ThinkGearProtocol(object):
  syncbyte = 0xaa
  syncnum = 2
  maxpay = 169
  signal_quality = 0x02
  blink_event = 0x16
  esense_attention = 0x04
  esense_meditation = 0x05
  extended_codetype = 0x55
  raw_eeg = 0x80
  power_bands = 0x83
  disconnect_byte = 0xc1
  autoconnect_byte = 0xc2
  connected_code = 0xd0
  disconnected_code = 0xd2
  supported_codes = {
    signal_quality: (1, '(inverse) signal quality'),  # 0x02
    esense_attention: (1, 'esense attention'),  # 0x04
    esense_meditation: (1, 'esense meditation'),  # 0x05
    blink_event: (1, 'blink event'),  # 0x16
    extended_codetype: (1, 'extended codetype - not implemented'),  # 0x55
    raw_eeg: (2, 'raw eeg'),  # 0x80
    power_bands: (24, 'power bands')  # 0x83
  }

class Device(object):
  protocol = ThinkGearProtocol
  def __init__(self):
    self.baudrate = 57600 * 2
    self.port = None
    self.timeout = 1
    self.ser = None
    self.device_on()
  def device_on(self):
    for i in range(0,4):
      self.port = '/dev/ttyUSB' + str(i)
      try: 
        self.ser = serial.Serial(port=self.port, baudrate=self.baudrate, timeout=self.timeout)
        # Test if this serial device is our device
        od_avg = sum([ord(i) for i in self.ser.read(10)])/10
        if od_avg > 50:
          print od_avg
          break
        else:
          continue
      except: 
        continue
    print self.ser
  def control(self, val):
    self.ser.write(bytearray([val]))
  def connect(self):
    self.control(self.protocol.autoconnect_byte)
  def disconnect(self):
    self.control(self.protocol.disconnect_byte)
  def bytevals(self):
    pause = 0
    while True:
      b = self.ser.read()
      if b:
        yield ord(b)
      elif pause:
        time.sleep(pause)

class Packer(object):
  '''unpacks payload: header, payload, checksum
     extracts codetype and code length from payload
  '''
  def __init__(self, coordinator):
    self.coordinator = coordinator
    self.parser = Parser()
  def payload(self, packet):
    paylen = packet.paylen
    paycheck = packet.paycheck
    payload = packet.payload
    pay_it = iter(payload)
    while paylen > 0:
      paylen -= 1 # subracts codetype from paylen
      current_codetype = pay_it.next()
      expected_datalen = self.coordinator.protocol.supported_codes[current_codetype][0]
      if current_codetype < 0x80:
        assert expected_datalen == 1 
        val = pay_it.next()
      else:
        specified_datalen = pay_it.next()
        paylen -= 1  # accounting for specified_datalen
        assert expected_datalen == specified_datalen # Handle in Packet by breaking from loop and logging currpt packet kjs 2014 01 01
        val = list(islice(pay_it, expected_datalen))
      paylen -= expected_datalen
      if current_codetype == self.coordinator.protocol.raw_eeg:
        parsed_val = self.parser.raw_eeg(val)
        self.coordinator.rp.send(parsed_val)
        if self.coordinator.analyze:
          self.coordinator.analytics.raw_eeg_counter()
      elif current_codetype == self.coordinator.protocol.signal_quality:
        pass
      elif current_codetype == self.coordinator.protocol.esense_attention:
        pass
      elif current_codetype == self.coordinator.protocol.esense_meditation:
        pass
      elif current_codetype == self.coordinator.protocol.power_bands:
        parsed_val = self.parser.power_bands(val)
        self.coordinator.fp.send(parsed_val)
      else:
        print "not implemented - expected_datalen %d" % expected_datalen

class Analytics(object):
  def __init__(self):
    self.time_keeper = deque([0,0], 2)
    self.raw_eeg_count = 0
    self.ref_time = time.time()
    self.protocol = ThinkGearProtocol
  def raw_eeg_counter(self):
    self.raw_eeg_count += 1
    new_time = time.time()
    elapsed = new_time - self.ref_time
    if elapsed >= 1.0:
      if self.raw_eeg_count < 512:
        print "-------------", self.raw_eeg_count, elapsed, "-------------"
      else:
        print self.raw_eeg_count, elapsed
      self.raw_eeg_count = 0
      self.ref_time = new_time

class Packet(object):
  def __init__(self, synced_src):
    self.src = synced_src
    self.bytes_read = 0
    self.paylen = None
    self.payload = None
    self.paycheck = None
    self.load()
  def load(self):
    it = self.src
    self.paylen = it.next()
    if self.paylen <= ThinkGearProtocol.maxpay:
      self.payload = list(islice(it, 0, self.paylen))
      if self.paylen == len(self.payload):
        self.paycheck = it.next()
  def is_valid(self):
    if self.paylen <= ThinkGearProtocol.maxpay:
      return (self.paycheck == (~sum(self.payload) & 0xff))
    return False
  def codetype(self):
    if not self.payload:
      return None
    else:
      return self.payload[0]

class Parser():
  def __init__(self):
    self.protocol = ThinkGearProtocol
  def raw_eeg(self, val):
    '''receives a list of 2 ints
       yields big-endian signed 16 bit integer
    '''
    a, b = val
    val = (a << 8) + b
    if (a & 0x80):
      val -= 65536 
    return val
  def power_bands(self, val):
    # recieves a list of 24 ints
    vals = []
    for index in range(0, len(val), 3):
      a, b, c = val[index:index+3]
      parsed_val = (a << 16) + (b << 8) + c
      vals.append(parsed_val)
    return vals

class UI(object):
  def __init__(self, coordinator):
    self.coordinator = coordinator
    self.app = QtGui.QApplication(sys.argv) 
    self.widget = QtGui.QWidget()
    self.connect_btn = QtGui.QPushButton('Connect')
    self.disconnect_btn = QtGui.QPushButton('Disconnect')
    self.acquire_btn = QtGui.QPushButton('Acquire')
    self.record_chkbx = QtGui.QCheckBox('Record Data')
    self.rawplot = pg.PlotWidget()
    self.fftplot = pg.PlotWidget()
    self.rawplot.setRange(yRange=(500, -500))
    self.fftplot.setRange(yRange=(500000, 0))
    self.layout = QtGui.QGridLayout()
    self.widget.setLayout(self.layout)
    self.layout.addWidget(self.connect_btn, 0, 0)
    self.layout.addWidget(self.disconnect_btn, 0, 1)
    self.layout.addWidget(self.acquire_btn, 0, 2)
    self.layout.addWidget(self.record_chkbx, 0, 3)
    self.layout.addWidget(self.rawplot, 1, 0, 2, 4)
    self.layout.addWidget(self.fftplot, 3, 0, 2, 4)
    self.record_chkbx.stateChanged.connect(self.write_file)
    self.connect_btn.clicked.connect(self.send_connect)
    self.disconnect_btn.clicked.connect(self.send_disconnect)
    self.acquire_btn.clicked.connect(self.mainloop)
    self.widget.show()
    self.raw_x = deque([0], 1024)
    self.raw_y = deque([0], 1024)
  def send_connect(self):
    self.coordinator.connect()
  def send_disconnect(self):
    print "sending disconnect"
    self.raw_x.clear()
    self.raw_y.clear()
    self.coordinator.disconnect()
    print "disconnected"
  def mainloop(self):
    self.coordinator.mainloop()
  def write_file(self):
    pass
  def raw_plot(self):
    sequence_num = 0
    while True:
      val = yield
      self.raw_x.append(sequence_num)
      self.raw_y.append(val)
      sequence_num += 1
      if sequence_num % 32 == 0:
        self.rawplot.plot(self.raw_x, self.raw_y, clear=True)
        pg.QtGui.QApplication.processEvents()
  def fft_plot(self):
    p_bands = range(8)
    while True:
      vals = yield
      self.fftplot.plot(p_bands, vals, clear=True, symbol='s', pen=None)

def main():
  Coordinator()

if __name__ == '__main__':
  main()

