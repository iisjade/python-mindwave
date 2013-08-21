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

from collections import deque, defaultdict
from itertools import count, takewhile
from PyQt4 import QtGui
import struct
import time
import serial
import numpy
import pyqtgraph as pg

#####

def main():
  pass

##### work in progress below, ignore ...
#
'''
class ThinkGearCodes:
  signal_quality = 0x02
  blink_event = 0x16
  esense_attention = 0x04
  esense_meditation = 0x05
  extended_codetype = 0x55
  raw_eeg = 0x80
  power_bands = 0x83

class Dispatcher:
  def __init__(self):
    pass
  def make_entry(self, typecode, datalen, desc, parser): 
    pass
'''
#
##### work in progress above, ignore ...

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
    self.binary_out = open('binary_out', 'w+b')
    baudrate = 115200
    port = '/dev/ttyUSB0'
    timeout = 0.00001
    try: self.ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
    except:
      for i in range(1,4):
        port = '/dev/ttyUSB' + str(i)
        try: 
          self.ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
          break
        except: 
          continue
    print "Dongle.ser.port: %s" % (port,)
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
      n = self.ser.readinto(buf)
      for i in range(n):
        yield buf[i]
  def log_bytevals(self):
    for b in self.bytevals():
      self.binary_out.write(hex(b)+',')
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
    self.fout = open('run_log', 'w')
    self.plotWidget = pg.plot()
    self.protocol = ThinkGearProtocol
    self.dongle = Dongle()
    self.src = self.dongle.log_bytevals()
    self.syncer = Sync()
    self.plexer = Plexer()
    # Initialize co-routines:
    self.sq = Plexer.plexit(0x02)
    self.be = Plexer.plexit(0x16)
    self.rd = Plexer.plexit(0x80)
    self.pb = Plexer.plexit(0x83)
    self.lg = Plexer.plexit('logger')
    self.lg.send(self.fout)
    self.rd.send(self.plotWidget)
    self.connected = False
    self.tracker = Tracker()
  def sync(self):
    self.syncer.sync_it(self.src)
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
    self.sync()
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
    # Should confirm disconnect
  def checkpay(self, payout):
    paylen, payload, paycheck = payout
    if paylen <= self.protocol.maxpay:
      return (paycheck == (~sum(payload) & 0xff))
    return False
  def turmite(self, paylen, it):
    return (paylen - 1, it.next())
  def payload_gen(self, payout):
    trace = str(payout) + "," + time.time().__format__('.16') + "\n"
    self.lg.send(trace)
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
      else: datalen = 1
      assert datalen == codon[0]
      if datalen == 1:
        # assert codetype < 0x80
        paylen, val = self.turmite(paylen, it)
        if codetype == 0x02: 
          self.sq.send(val)
          self.tracker.count_signal()
          self.tracker.snapshot()
        elif codetype == 0x16:  # not actually expected with current hardware 
          self.be.send(val)
          self.tracker.count_blink()
      elif datalen == 2:
        # assert codetype >= 0x80
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
    while True: 
      self.sync()
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
  def run_checkloop(self):
    try: 
      self.disconnect()
      time.sleep(1)
      self.connect()
      self.checkloop()
    except KeyboardInterrupt as Completed:
      self.disconnect()
      print "Disconnected"
      print "Tracker dict: ", self.tracker.snapshots[-1]
      self.fout.close()
      self.dongle.binary_out.close()

class Plexer:
  protocol=ThinkGearProtocol
  def __init__(self):
    pass
  @staticmethod
  def signal_quality():
    while True:
      val = yield
  @staticmethod
  def blink_event():
    while True:
      val = yield
  @staticmethod
  def raw_data():
    bar = deque([0], 1024)
    foo = deque([0], 1024)
    i = 0
    pw = yield
    while True:
      val = yield
      bar.append(i)
      foo.append(val)
      scaled = ( val + 100 ) / 5
      print "%i %6i %s" % (i, val, ')'.rjust(scaled,'-'))
      i += 1
      if i % 1024 == 0:
        pw.plot(bar, foo, clear=True)
        pg.QtGui.QApplication.processEvents()
      # print "Raw Data: ", val
      # print "val #%d: %d" % (val_count, val) 
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
    fout = yield
    while True:
      trace = yield
      fout.write(trace)  
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

if __name__ == '__main__':
  main()
