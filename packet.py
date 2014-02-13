#!/usr/bin/env python
from itertools import islice
from collections import deque
from PyQt4 import QtGui, QtCore
import pyqtgraph as pg
import sys 
import time
import serial
import fftw3
import numpy
import signal

class ThinkGearProtocol(object):
  syncnum = 2
  maxpay = 169
  signal_quality = 0x02
  esense_attention = 0x04
  esense_meditation = 0x05
  blink_event = 0x16
  extended_codetype = 0x55
  eeg_data = 0x80
  power_bands = 0x83
  syncbyte = 0xaa
  disconnect_byte = 0xc1
  autoconnect_byte = 0xc2
  connected_code = 0xd0
  disconnected_code = 0xd2
  standby_code = 0xd4
  @staticmethod
  def checksum(seq):
    return ~sum(seq) & 0xff
  @staticmethod
  def datalen(codetype):
    if codetype < 0x80:
      return 1
    elif codetype == ThinkGearProtocol.standby_code:
      return 1
    elif codetype == ThinkGearProtocol.connected_code:
      return 2
    elif codetype == ThinkGearProtocol.disconnected_code:
      return 2
    elif codetype == ThinkGearProtocol.eeg_data:
      return 2
    elif codetype == ThinkGearProtocol.power_bands:
      return 24
    else:
      return 0
  @staticmethod
  def parse_eeg(data):
    a, b = data
    c = (a << 8) + b 
    if (a & 0x80):
      c -= 65536
    return c
  @staticmethod
  def parse_power(data):
    # recieves a list of 24 ints
    data_list = list(data)
    bands = []
    for index in range(0, len(data_list), 3):
      a, b, c = data_list[index:index+3]
      parsed_val = (a << 16) + (b << 8) + c
      bands.append(parsed_val)
    return bands

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
    while True:
      yield self.ser.read()

class Packet(object):
  def __init__(self, src):
    self.is_valid = False
    self.paylen = src.next()
    self.payload_data = None
    self.paycheck = None
    if self.paylen <= ThinkGearProtocol.maxpay: 
      self.payload_data = list(islice(src, self.paylen))
      self.paycheck = src.next()
      if self.paycheck == ThinkGearProtocol.checksum(self.payload_data):
        self.is_valid = True
  @property
  def payload_iterator(self):
    pos = 0
    while pos < self.paylen: 
      codetype = self.payload_data[pos]
      pos += 1
      expected_datalen = ThinkGearProtocol.datalen(codetype)
      if expected_datalen < 1:
        self.is_valid = False
        break
      if expected_datalen > 1:
        specified_datalen = self.payload_data[pos]
        pos += 1
        if specified_datalen != expected_datalen:
          self.is_valid = False
          break
      next_pos = pos + expected_datalen 
      dataslice = islice(self.payload_data, pos, next_pos)
      pos = next_pos
      yield (codetype, dataslice) 
  def __repr__(self):
    s = "paylen " + str(self.paylen) 
    if self.is_valid:
      s += "\n" + "valid packet"
    else:
      s += "\n" + "invalid packet"
    if self.payload_data:
      s += "\n payload: " + str(self.payload_data)
    if self.paycheck:
      s += "\n paycheck: " + str(self.paycheck)
    s += "\n"
    return s

class Bytestream(object):
  def __init__(self, dev):
    self.src = (ord(b) for b in dev.bytevals() if b)
    self.sync_count = 0
    self.last_synced = None
    self.syncer = deque([], ThinkGearProtocol.syncnum)
    self.cruft = deque()
  @property
  def is_synced(self):
    return (self.syncer.count(ThinkGearProtocol.syncbyte) == ThinkGearProtocol.syncnum)
  @property
  def synced_src(self):
    self.sync()
    return self.src
  def sync(self):
    self.syncer.clear()
    self.cruft.clear()
    while not self.is_synced:
      b = self.src.next()
      self.syncer.append(b)
      self.cruft.append(b)
    self.last_synced = time.time()
    self.sync_count += 1

class Coordinator(object):
  def __init__(self):
    self.dev = Device()
    self.bs = Bytestream(self.dev)
    self.connected = False
    self.ui = UI(self)
    self.handlers = self.init_handlers()
    self.logfile = open("logfile", "w")
    self.datafile = open("datafile", "w")
    self.ui.app.exec_()
    # never ... mind
  def init_handlers(self):
    d = {
      ThinkGearProtocol.signal_quality : self.signal_quality_handler(),
      ThinkGearProtocol.esense_attention : self.esense_attention_handler(),
      ThinkGearProtocol.esense_meditation : self.esense_meditation_handler(),
      ThinkGearProtocol.eeg_data : self.eeg_data_handler(),
      ThinkGearProtocol.power_bands : self.power_bands_handler()
    }
    for handler in d.values():
      handler.send(None)
    return d
  def log(self, a, b=None):
    s = "\n sequence number: " + str(self.bs.sync_count)
    s += "\n timestamp: " + repr(self.bs.last_synced)
    if b:
      s += "\n" + ','.join([str(a), str(list(b))])
    else:
      s += "\n" + str(a)
    self.logfile.write(s)
  def disconnect(self):
    self.dev.disconnect()
    self.connected = False
  def connect(self, retry = 5):
    hangtime = 2
    if self.connected:
      print "already connected, disconnecting first"
      self.disconnect()
      time.sleep(hangtime)
    print "sending connect"
    self.dev.connect()
    print "sent connect"
    attempts = 0
    while not self.connected and attempts < 1024:
      self.dev.connect()
      p = Packet(self.bs.synced_src)
      if not p.is_valid:
        print "invalid packet"
        self.log(p)
        continue
      for codetype, data in p.payload_iterator: 
        if codetype == ThinkGearProtocol.connected_code:
          print "connected"
          self.connected = True
          break
        else:
          "got something other than connection code in packet"
          self.log(codetype, data)
      attempts += 1
    if not self.connected and (retry > 0):
      self.dev.disconnect()
      time.sleep(hangtime)
      print "retrying," + str(retry - 1) + "retrys left"
      self.connect(retry - 1)
    elif not self.connected and retry == 0:
      print "exceeded max retrys, failure"
  def receive(self):
    while self.connected:
      p = Packet(self.bs.synced_src)
      if not p.is_valid:
        self.log(p)
        continue
      for codetype, data in p.payload_iterator: 
        handler = self.handlers.get(codetype)
        if handler is None:
          self.log(codetype, data)
          continue
        handler.send(data)
  def signal_quality_handler(self):
    while True:
      data = yield
      val, = data
      self.ui.signalquality_plot_.send(val)
  def esense_attention_handler(self):
    while True:
      data = yield
      val, = data
  def esense_meditation_handler(self):
    while True:
      data = yield
      val, = data
  def eeg_data_handler(self):
    while True:
      data = yield
      val = ThinkGearProtocol.parse_eeg(data)
      sequence_number = self.bs.sync_count
      t = (val, sequence_number)
      self.ui.raw_plot_.send(t)
      self.write_packet(val, sequence_number)
  def power_bands_handler(self):
    while True:
      data = yield
      if data is None:
        print data
      else:
        vals = ThinkGearProtocol.parse_power(data)
        self.ui.ns_fft_plot_.send(vals)
  def write_packet(self, val, sequence_number):
    s = '\n' + str(sequence_number) + ',' + str(val)
    self.datafile.write(s)
  def cleanup(self):
    self.logfile.close()
    self.datafile.close()
    self.dev.ser.close()
    signal.signal(signal.SIGINT, signal.SIG_DFL)

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
    self.ns_fftplot = pg.PlotWidget()
    self.rd_fftplot = pg.PlotWidget()
    self.rawplot.setRange(yRange=(500, -500))
    self.ns_fftplot.setRange(yRange=(20, 0))
    self.rd_fftplot.setRange(yRange=(0, 90))
    self.layout = QtGui.QGridLayout()
    self.widget.setLayout(self.layout)
    self.layout.addWidget(self.connect_btn, 0, 0)
    self.layout.addWidget(self.disconnect_btn, 0, 1)
    self.layout.addWidget(self.acquire_btn, 0, 2)
    self.layout.addWidget(self.record_chkbx, 0, 3)
    self.layout.addWidget(self.rawplot, 1, 0, 2, 4)
    self.layout.addWidget(self.ns_fftplot, 3, 0, 2, 4)
    self.layout.addWidget(self.rd_fftplot, 5, 0, 2, 4)
    self.record_chkbx.stateChanged.connect(self.write_file)
    self.connect_btn.clicked.connect(self.send_connect)
    self.disconnect_btn.clicked.connect(self.send_disconnect)
    self.acquire_btn.clicked.connect(self.acquire)
    self.widget.show()
    self.raw_x = deque([0], 1024)
    self.raw_y = deque([0], 1024)
    self.raw_plot_ = self.raw_plot()
    self.raw_plot_.send(None)
    self.ns_fft_plot_ = self.ns_fft_plot()
    self.ns_fft_plot_.send(None)
    self.sq_x = deque([0], 2)
    self.sq_y = deque([0], 2)
    self.signalquality_plot_ = self.signalquality_plot()
    self.signalquality_plot_.send(None)
  def send_connect(self):
    self.coordinator.connect()
  def send_disconnect(self):
    print "sending disconnect"
    self.raw_x.clear()
    self.raw_y.clear()
    self.sq_x.clear()
    self.sq_y.clear()
    self.coordinator.disconnect()
    print "disconnected"
  def acquire(self):
    self.coordinator.receive()
  def write_file(self):
    pass
  def raw_plot(self):
    fft_size = 512
    bins = [i for i in range(fft_size/2)]
    while True:
      val, seq_num = yield
      self.raw_x.append(seq_num)
      self.raw_y.append(val)
      if seq_num % 32 == 0 and len(self.raw_y) >= fft_size:
        raw_y_list = list(self.raw_y)
        inputa = numpy.array(raw_y_list[-fft_size:], dtype=complex)
        #hann_window = numpy.hanning(fft_size)
        #inputa = inputa * hann_window
        #inputa = inputa * flattop_window
        outputa = numpy.zeros(fft_size, dtype=complex)
        fft = fftw3.Plan(inputa, outputa, direction='forward', flags=['estimate'])
        fft.execute()
        outputa = (numpy.log10(numpy.abs(outputa)) * 20)[:fft_size/2]
        self.rawplot.plot(self.raw_x, self.raw_y, clear=True)
        self.rd_fftplot.plot(bins, outputa, clear=True)
        pg.QtGui.QApplication.processEvents()
  def ns_fft_plot(self):
    p_bands = range(8)
    while True:
      vals = yield
      ln_vals = numpy.log(vals)
      self.ns_fftplot.plot(p_bands, ln_vals, clear=True, symbol='s', pen=None)
  def signalquality_plot(self):
    sq_num = 0
    while True:
      val = yield
      self.sq_x.append(sq_num)
      self.sq_y.append(val)
      #self.sqplot.plot(self.sq_x, self.sq_y, clear=True)
      sq_num += 1
      

def main():
  try:
    c = Coordinator()
  finally:
    c.cleanup()

if __name__ == '__main__':
  main()

