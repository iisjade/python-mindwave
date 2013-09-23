#!/usr/bin/env python
'''
TODO: * Write pasred raw_data with timestamp 
      * Visualization
      * Run log time chunks - insert analysis method
      * Why still see bogus_count in tracker?
58 bogus_count per 50 signal_count.
      * Why 504 raw_count per 1 signal_count (avg over 50)?
Only read 1 data code per payload?
'''

from collections import deque
from PyQt4 import QtGui, QtCore
import pyqtgraph as pg
import sys
import struct
import time
import serial

#####

def main():
  print "main ...?"

class ThinkGearProtocol:
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
  codex = {
    signal_quality: (1, '(inverse) signal quality'),  # 0x02
    esense_attention: (1, 'esense attention'),  # 0x04
    esense_meditation: (1, 'esense meditation'),  # 0x05
    blink_event: (1, 'blink event'),  # 0x16
    extended_codetype: (1, 'extended codetype - not implemented'),  # 0x55
    raw_eeg: (2, 'raw eeg'),  # 0x80
    power_bands: (24, 'power bands')  # 0x83
  }
  signed_16_bit_big_endian = struct.Struct('>h').unpack

class Sync:
  protocol = ThinkGearProtocol
  def __init__(self):
    self.syncer = deque([], Sync.protocol.syncnum)
  def synced(self, b):
    self.syncer.append(b)
    return self.syncer.count(Sync.protocol.syncbyte) == Sync.protocol.syncnum
  def sync_it(self, src):
    self.syncer.clear()
    while not self.synced(src.next()):
      pass

class Dongle:
  protocol = ThinkGearProtocol
  def __init__(self):
    self.baudrate = 115200
    self.port = '/dev/ttyUSB0'
    self.timeout = 0.00001
    self.ser = None
    self.dongle_on()
    self.hex_out = open('hex_out', 'w')
    self.time_out = open('time_out', 'w')
  def dongle_on(self):
    for i in range(1,4):
      self.port = '/dev/ttyUSB' + str(i)
      try: 
        self.ser = serial.Serial(port=self.port, baudrate=self.baudrate, timeout=self.timeout)
        # Test if this serial device is our dongle
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
    print 'sending connect'
    self.control(self.protocol.autoconnect_byte)
  def disconnect(self):
    print 'sending disconnect'
    self.control(self.protocol.disconnect_byte)
  def bytevals(self, bufsize=4096):
    buf = bytearray(bufsize)
    while True:
      formatted_timestamp = '\n{:10.6f}'.format(time.time())
      self.time_out.write(formatted_timestamp)
      n = self.ser.readinto(buf)
      self.time_out.write("\n" + str(n))
      for i in range(n):
        yield buf[i]
  def log_bytevals(self):
    for b in self.bytevals():
      self.hex_out.write(hex(b)+',')
      yield b

class Tracker:
  def __init__(self):
    self.byte_count = 0
    self.raw_count = 0
    self.power_count = 0
    self.signal_count = 0
    self.blink_count = 0
    self.bogus_count = 0
    self.snapshots = []
  def count_byte(self):
    self.byte_count += 1
  def count_raw(self):
    self.raw_count += 1
  def count_signal(self):
    self.signal_count += 1
  def count_blink(self):
    self.blink_count += 1
  def count_power(self):
    self.power_count += 1
  def count_bogus(self):
    self.bogus_count += 1
  def snapshot(self):
    snap = dict(
      timestamp = time.time(),
      byte_count=self.byte_count,
      raw_count=self.raw_count,
      power_count=self.power_count,
      signal_count=self.signal_count,
      blink_count=self.blink_count,
      bogus_count=self.bogus_count,
    )
    self.snapshots.append(snap)
  def deltas(self):
    ret = []
    spet = []
    it = iter(self.snapshots)
    e = it.next()
    i = 0
    for el in it:
      delta_raw = el['raw_count'] - e['raw_count']
      delta_bogus = el['bogus_count'] - e['bogus_count']
      delta_time = el['timestamp'] - e['timestamp']
      ret.append((delta_raw, delta_bogus, round(delta_time, 4)))
      e = el
    for event in ret:
      if event[2] < 1.5 or event[2] > .9:
        spet.append(event[2])
    argh = array([range(len(spet))])
    for data in spet:
      argh.put(i, data)
      i += 1
    return ret, argh.mean(), argh.std()
    
class Packer:
  def __init__(self):
    self.protocol = ThinkGearProtocol
    self.sq = Plexer.plexit(0x02)
    self.be = Plexer.plexit(0x16)
    self.rd = Plexer.plexit(0x80)
    self.pb = Plexer.plexit(0x83)
    self.dongle = Dongle()
    self.syncer = Sync()
    self.tracker = Tracker()
    self.src = self.dongle.log_bytevals()
    self.connected = False
  def read_packet(self):
    it = self.src
    paylen = it.next()
    if paylen <= self.protocol.maxpay:
      payload = [it.next() for i in range(paylen)] 
      paycheck = it.next()
    else:
      payload = None
      paycheck = None
    payout = (paylen, payload, paycheck)
    return payout
  def connect(self):
    self.dongle.connect()
    while self.connected == False:
      self.confirm()
  def confirm(self):
    self.syncer.sync_it(self.src)
    payout = self.read_packet()
    paylen, payload, paycheck = payout
    if payload:
      codetype = payload[0]
      # print "paylen: %i  codetype: %i" % (paylen, codetype)
      if codetype == self.protocol.connected_code:  # 0xd0 
        self.connected = True
        print "connected"
        return True
    return False
  def disconnect(self):
    self.dongle.disconnect()
    self.connected = False
  def checkpay(self, payout):
    paylen, payload, paycheck = payout
    if paylen <= self.protocol.maxpay:
      return (paycheck == (~sum(payload) & 0xff))
    return False
  def turmite(self, paylen, it):
    return (paylen - 1, it.next())
  def payload_gen(self, payout):
    trace = str(payout) + "," + time.time().__format__('.16') + "\n"
    paylen, payload, paycheck = payout
    it = iter(payload)
    while paylen > 0:
      try:
        paylen, codetype = self.turmite(paylen, it)
      except StopIteration:
        print "stopped 3 (codetype)"
        break
      try: codon = self.protocol.codex[codetype]
      except KeyError:
        print "parse error unknown codetype ", hex(codetype)
        break
      if codon[0] > 1:  # datalen
        paylen, datalen = self.turmite(paylen, it)
      else: 
        datalen = 1
        assert datalen == codon[0]
      if datalen == 1:
        paylen, val = self.turmite(paylen, it)
        if codetype == 0x02: 
          self.sq.send(val)
          self.tracker.count_signal()
          self.tracker.snapshot()
        elif codetype == 0x16:  # not actually expected with current hardware 
          self.be.send(val)
          self.tracker.count_blink()
      elif datalen == 2:
        paylen, a = self.turmite(paylen, it)
        paylen, b = self.turmite(paylen, it)
        c = bytearray(2)
        c[0] = a
        c[1] = b
        t = self.protocol.signed_16_bit_big_endian(str(c))
        val = t[0]
        self.rd.send(val)
        self.tracker.count_raw()
      elif datalen == 24:
        for j in range(0, datalen, 3):
          paylen, a = self.turmite(paylen, it)
          paylen, b = self.turmite(paylen, it)
          paylen, c = self.turmite(paylen, it)
          val = (a << 16) + (b << 8) + c
          self.pb.send(val)
          self.tracker.count_power()
      else:
        print "not implemented - datalen %d" % datalen
  def checkloop(self):
    self.connect()
    while self.connected: 
      self.syncer.sync_it(self.src)
      payout = self.read_packet()
      if self.checkpay(payout):
        self.payload_gen(payout)
      else:
        self.tracker.count_bogus()
        self.dx_payout(payout)
  def dx_payout(self, payout):
    paylen, payload, paycheck = payout
    print "bogus checksum?"
    if payload:
      print "%s\tCodetype: %s" % (bin(~sum(payload) & 0xff), hex(payload[0]))
    else:
      print "no payload"
    if paycheck:
      print bin(paycheck)
    else:
      print "no checksum"

class Plexer:
  protocol=ThinkGearProtocol
  @staticmethod
  def signal_quality():
    while True:
      with open('signal_quality', 'a') as f:
        val = yield
        rec = (val, time.time())
        f.write(str(rec))
        f.write("\n")
  @staticmethod
  def blink_event():
    while True:
      val = yield
  @staticmethod
  def raw_data():
    #raw_plot = Wui.raw_plot
    #raw_plot.send(None)
    delta_time = deque([0, 0], 2)
    while True:
      with open('raw_out', 'a') as f:
        delta_time.append(time.time())
        this_delta = delta_time[1] - delta_time[0]
        formatted_timestamp = '{:10.6f}'.format(this_delta)
        val = yield
        rec = (val, formatted_timestamp)
        #raw_plot.send(val)
        f.write(str(rec[0]) + "," + str(rec[1]))
        f.write("\n")
  @staticmethod
  def power_bin():
    while True:
      delta = yield
      theta = yield
      low_alpha = yield
      high_alpha = yield
      low_beta = yield
      high_beta = yield
      log_gamma = yield
      high_gamma = yield
  @staticmethod
  def logger():
    set_write = False
    while True:
      trace = yield
      if type(trace) == file:
        set_write = True
      if set_write:
        # fout.write(trace)
        pass
  @staticmethod
  def plexit(codetype):
    dispatch = {
      0x02: Plexer.signal_quality,
      # 0x04: 'esense attention',
      # 0x05: 'esense meditation',
      0x16: Plexer.blink_event,
      # 0x55: 'extended codetype - not implemented',
      0x80: Plexer.raw_data,
      0x83: Plexer.power_bin,
      'logger': Plexer.logger,
    }
    try: cor = dispatch[codetype]
    except KeyError:
      print "parse error unknown codetype ", hex(codetype)
      raise
    ret = cor()
    ret.send(None)
    return ret

class Wui:
  def __init__(self):
    self.packer = Packer()
    self.app = QtGui.QApplication(sys.argv) 
    self.widget = QtGui.QWidget()
    self.connect_btn = QtGui.QPushButton('Connect')
    self.disconnect_btn = QtGui.QPushButton('Disconnect')
    self.record_chkbx = QtGui.QCheckBox('Record Data')
    self.plot = pg.PlotWidget()
    self.plot.setRange(yRange=(500, -500))
    self.layout = QtGui.QGridLayout()
    self.widget.setLayout(self.layout)
    self.layout.addWidget(self.connect_btn, 0, 0)
    self.layout.addWidget(self.disconnect_btn, 1, 0)
    self.layout.addWidget(self.record_chkbx, 2, 0)
    self.layout.addWidget(self.plot, 0, 3, 5, 1)
    self.record_chkbx.stateChanged.connect(self.write_file)
    self.connect_btn.clicked.connect(self.send_connect)
    self.disconnect_btn.clicked.connect(self.send_disconnect)
  def send_connect(self):
    print "sending connect"
    self.packer.connect()
    self.packer.checkloop()
  def send_disconnect(self):
    self.packer.disconnect()
  def go(self):
    self.widget.show()
    self.app.exec_()
  def write_file(self):
    pass
  def raw_plot(self):
    self.widget.show()
    self.app.exec_()
    x = deque([0], 1024)
    y = deque([0], 1024)
    i = 0
    while True:
      val = yield 
      x.append(i)
      y.append(val)
      i += 1
      if i % 16 == 0:
        self.plot.plot(x, y, clear=True)
        pg.QtGui.QApplication.processEvents()


if __name__ == '__main__':
    main()
