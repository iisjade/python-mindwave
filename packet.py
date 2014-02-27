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
  headset_not_found = 0xd1
  disconnected_code = 0xd2
  request_denied = 0xd3
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
      return 3
    elif codetype == ThinkGearProtocol.headset_not_found:
      return 2
    elif codetype == ThinkGearProtocol.disconnected_code:
      return 3
    elif codetype == ThinkGearProtocol.request_denied:
      return 0
    elif codetype == ThinkGearProtocol.standby_code:
      return 1
    elif codetype == ThinkGearProtocol.eeg_data:
      return 2
    elif codetype == ThinkGearProtocol.power_bands:
      return 24
    else:
      return -1
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
    self.br = 57600 * 2
    self.p = None
    self.to = 1
    self.ser = self.get_serial()
    self.connecting = False
  def get_serial(self, i=0):
    self.p = '/dev/ttyUSB' + str(i)
    ser = serial.Serial(port=self.p, baudrate=self.br, timeout=self.to)
    if i == 5:
      print "No serial connection made"
      return False
    if ser.isOpen() == False:
      return self.get_serial(i+1)
    return ser
  def control(self, val):
    self.ser.write(bytearray([val]))
  def connect(self):
    if self.ser.isOpen() == False:
      self.ser.open()
    self.control(self.protocol.autoconnect_byte)
    self.connecting = True
  def disconnect(self):
    self.control(self.protocol.disconnect_byte)
    if self.ser.isOpen():
      self.ser.close()
    self.connecting = False
  def bytevals(self):
    while self.ser.isOpen() and self.connecting == True:
      b = self.ser.read()
      print hex(ord(b))
      yield b

class InvalidPacket(BaseException):
  pass

class InvalidPacketPaylen(InvalidPacket):
  pass

class InvalidPacketChecksum(InvalidPacket):
  pass

class InvalidPacketCodetype(InvalidPacket):
  pass

class InvalidPacketDatalen(InvalidPacket):
  pass

class Packet(object):
  def __init__(self, coordinator):
    self.coordinator = coordinator
    self.is_valid = False
    self.src = self.coordinator.bs.synced_src()
    self.paylen = self.src.next()
    self.payload_data = None
    self.paycheck = None
    if self.paylen > ThinkGearProtocol.maxpay: 
      raise InvalidPacketPaylen
    self.payload_data = list(islice(self.src, self.paylen))
    self.paycheck = self.src.next()
    if self.paycheck != ThinkGearProtocol.checksum(self.payload_data):
      raise InvalidPacketChecksum
    self.is_valid = True
  def __iter__(self):
    return self.payload_iterator()
  def payload_iterator(self):
    if not self.is_valid:
      raise InvalidPacket
    pos = 0
    while pos < self.paylen: 
      codetype = self.payload_data[pos]
      pos += 1
      expected_datalen = ThinkGearProtocol.datalen(codetype)
      if expected_datalen == -1:
        self.is_valid = False
        raise InvalidPacketDatalen
      if expected_datalen == 0:
        print codetype
        continue
      if expected_datalen > 1:
        specified_datalen = self.payload_data[pos]
        pos += 1
        if specified_datalen != expected_datalen:
          self.is_valid = False
          raise InvalidDatalen
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
  def __init__(self, MODE_UI, MODE_FFT):
    self.ui_mode = MODE_UI
    self.fft_mode = MODE_FFT
    self.dev = Device()
    self.bs = Bytestream(self.dev)
    self.connected = False
    self.logfile = open("logfile", "w")
    self.datafile = open("datafile", "w")
    self.handlers = self.make_handlers()
    self.ui = self.make_ui()
  def launch_ui(self):
    self.ui.app.exec_()  
  def make_ui(self):
    if self.ui_mode == 'none':
      self.ui = None
    elif self.ui_mode == 'plots':
      self.ui = UI_for_plots(self, self.fft_mode)
      self.launch_ui()
      # never ... mind
    elif self.ui_mode == 'ep':
      self.ui = UI_for_ep(self)
  def make_handlers(self):
    if self.ui_mode == 'none':
      return self.init_headless_handlers()
    elif self.ui_mode == 'plots':
      return self.init_plot_handlers()
    elif self.ui_mode == 'ep':
      return self.init_ep_handlers()
  def init_headless_handlers(self):
    return dict()
  def init_ep_handlers(self):
    return dict()
  def init_plot_handlers(self):
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
    print "retry number: %i" % (5-retry)
    while not self.connected and attempts < 1024:
      self.dev.connect()
      attempts += 1
      print "attempt number: %i" % attempts
      print "are we connected? %r" % self.connected
      try:
        p = Packet(self)
        print p
      except InvalidPacket:
        print "invalid packet"
        continue
      for codetype, data in p:
        if codetype == ThinkGearProtocol.connected_code:
          print "connected"
          self.connected = True
          break
        else:
          "got something other than connection code in packet"
          self.log(codetype, data)
      if not p.is_valid:
        self.log(p)
    if not self.connected and (retry > 0):
      self.dev.disconnect()
      time.sleep(hangtime)
      print "retrying," + str(retry - 1) + "retrys left"
      self.connect(retry - 1)
    elif not self.connected and retry == 0:
      print "exceeded max retrys, failure"
  def receive(self):
    while self.connected:
      p = Packet(self)
      if not p.is_valid:
        self.log(p)
      for codetype, data in p:
        handler = self.handlers.get(codetype)
        if handler is None:
          self.log(p)
          raise InvalidPacketCodetype 
        handler.send(data)
  def signal_quality_handler(self):
    while True:
      data = yield
      val, = data
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
    self.dev.ser = serial.Serial(self.dev.port)
    self.dev.ser.flush()
    self.dev.ser.close()

class UI_for_plots(object):
  def __init__(self, coordinator, MODE_FFT):
    self.coordinator = coordinator
    self.app = QtGui.QApplication(sys.argv)
    # note might put this in global namespace ?
    self.widget = QtGui.QWidget()
    self.connect_btn = QtGui.QPushButton('Connect')
    self.disconnect_btn = QtGui.QPushButton('Disconnect')
    self.acquire_btn = QtGui.QPushButton('Acquire')
    self.rawplot = pg.PlotWidget()
    self.ns_fftplot = pg.PlotWidget()
    self.rd_fftplot = pg.PlotWidget()
    self.rawplot.setRange(yRange=(500, -500))
    self.ns_fftplot.setRange(yRange=(0, 2))
    self.rd_fftplot.setRange(yRange=(0, 90))
    self.layout = QtGui.QGridLayout()
    self.layout.addWidget(self.connect_btn, 0, 0)
    self.layout.addWidget(self.disconnect_btn, 0, 1)
    self.layout.addWidget(self.acquire_btn, 0, 2)
    self.layout.addWidget(self.rawplot, 1, 0, 2, 4)
    self.layout.addWidget(self.ns_fftplot, 3, 0, 2, 4)
    self.layout.addWidget(self.rd_fftplot, 5, 0, 2, 4)
    self.widget.setLayout(self.layout)
    self.connect_btn.clicked.connect(self.send_connect)
    self.disconnect_btn.clicked.connect(self.send_disconnect)
    self.acquire_btn.clicked.connect(self.acquire)
    self.widget.show()
    self.raw_x = deque([0], 1024)
    self.raw_y = deque([0], 1024)
    self.raw_plot_ = self.raw_plot(fft_mode=MODE_FFT)
    self.raw_plot_.send(None)
    self.ns_fft_plot_ = self.ns_fft_plot()
    self.ns_fft_plot_.send(None)
  def send_connect(self):
    self.coordinator.connect()
  def send_disconnect(self):
    print "sending disconnect"
    self.raw_x.clear()
    self.raw_y.clear()
    self.coordinator.disconnect()
    print "disconnected"
  def acquire(self):
    while True:
        try:
          self.coordinator.receive()
        except InvalidPacket:
          print "done receive?"
  def write_file(self):
    pass
  def raw_plot(self, fft_mode):
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
        if fft_mode == '1':
          fft = fftw3.Plan(inputa, outputa, direction='forward', flags=['estimate'])
          fft.execute()
          outputa = (numpy.log10(numpy.abs(outputa)) * 20)[:fft_size/2]
          self.rd_fftplot.plot(bins, outputa, clear=True)
        self.rawplot.plot(self.raw_x, self.raw_y, clear=True)
        pg.QtGui.QApplication.processEvents()
  def ns_fft_plot(self):
    p_bands = range(8)
    while True:
      vals = yield
      ln_vals = numpy.log(vals)/10
      self.ns_fftplot.plot(p_bands, ln_vals, clear=True, symbol='s', pen=None)
      
class UI_for_ep(object):
  def __init__(self, coordinator):
    pass

def main(ui=None, fft=None):
  c = None
  try:
    c = Coordinator(MODE_UI=ui, MODE_FFT=fft)
  finally:
    if c:
      c.cleanup()

if __name__ == '__main__':
  cli = sys.argv
  for arg in cli:
    if '--ui=' in arg:
      ui = arg.split("=")[1]
    elif '--fft=' in arg:
      fft = arg.split("=")[1]
    elif '--help' in arg:
        print '--ui={none, plots}'
        print '--fft={0, 1}'
        sys.exit()
  status_code = main(ui=ui, fft=fft)
  sys.exit(status_code)

