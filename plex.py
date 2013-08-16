#!/usr/bin/env python

from collections import deque, defaultdict
from itertools import count, takewhile
import struct
import time
import serial

#####

def main():
  pass

class Utilities:
  def __init__(self):
    self.pk = Packer()
  def evildansclass(self):
    self.pk.disconnect()
    self.pk.connect_and_confirm()
    try: 
      self.pk.checkloop()
    except KeyboardInterrupt:
      self.pk.disconnect()
      print "Disconnected"
      raise

#####

class ThinkGearProtocol:
  syncbyte = 0xaa
  syncnum = 2
  maxpay = 169
  codex = {
    0x02: (1, '(inverse) signal quality'),
    0x04: (1, 'esense attention'),
    0x05: (1, 'esense meditation'),
    0x16: (1, 'blink event'),
    0x55: (1, 'extended codetype - not implemented'),
    0x80: (2, 'raw eeg'),
    0x83: (24, 'power bands')
  }
  disconnect_byte = 0xc1
  autoconnect_byte = 0xc2
  connected_code = 0xd0
  disconnected_code = 0xd2
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
    baudrate = 115200
    port = '/dev/ttyUSB0'
    timeout = 0.015
    try: self.ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
    except:
      for i in range(1,4):
        port = '/dev/ttyUSB' + str(i)
        try: 
          self.ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
          break
        except: continue
    print "Dongle.ser.port: %s" % (port,)
  def control(self, val):
    self.ser.write(bytearray([val]))
  def connect(self):
    print 'sending connect'
    self.control(self.protocol.autoconnect_byte)
  def disconnect(self):
    print 'sending disconnect'
    self.control(self.protocol.disconnect_byte)
  def xbytevals(self):
    while True:
      b = ord(self.ser.read())
      yield b
  def bytevals(self, bufsize=4096):
    buf = bytearray(bufsize)
    while True:
      n = self.ser.readinto(buf)
      for i in range(n):
        yield buf[i]

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

class Packer:
  def __init__(self):
    self.protocol = ThinkGearProtocol
    self.dongle = Dongle()
    self.src = self.dongle.bytevals()
    self.syncer = Sync()
    self.plexer = Plexer()
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
      print "paylen: %i  codetype: %i" % (paylen, codetype)
      if codetype == self.protocol.connected_code:  # 0xd0 
        self.connected = True
        print "connected"
        return True
    return False
  def disconnect(self):
    self.dongle.disconnect()
  def checkpay(self, payout):
    paylen, payload, paycheck = payout
    if paylen <= self.protocol.maxpay:
      return (paycheck == (~sum(payload) & 0xff))
    return False
  def payload_gen(self, payout):
    paylen, payload, paycheck = payout
    it = iter(payload)
    # Initialize co-routines 
    sq = Plexer.plexit(0x02)
    be = Plexer.plexit(0x16)
    rd = Plexer.plexit(0x80)
    pb = Plexer.plexit(0x83)
    while paylen > 0:
      try:
        codetype = it.next()
        paylen -= 1
      except StopIteration:
        print "stopped 3 (codetype)"
        break
      try: codon = self.protocol.codex[codetype]
      except KeyError:
        print "parse error unknown codetype ", hex(codetype)
        break
      # ...
      if codon[0] > 1:  # datalen
        datalen = it.next()
        paylen -= 1
      else: datalen = 1
      assert datalen == codon[0]
      if datalen == 1:
        assert codetype < 0x80
        val = it.next() 
        if codetype == 0x02: 
          sq.send(val)
          self.tracker.count_signal()
          self.tracker.snapshot()
        elif codetype == 0x16: 
          be.send(val)
          self.tracker.count_blink()
      elif datalen == 2:
        # assert codetype == 0x80
        a = it.next()
        b = it.next()
        c = bytearray(2)
        c[0] = a
        c[1] = b
        t = self.protocol.signed_16_bit_big_endian(str(c))
        val = t[0]
        rd.send(val)
        self.tracker.count_raw()
      else:
        # assert datalen == 24
        for j in range(0, datalen, 3):
          a = it.next()
          b = it.next()
          c = it.next()
          val = (a << 16) + (b << 8) + c
          pb.send(val)
          self.tracker.count_power()
      paylen -= datalen
      # yield (codetype, val)
  def checkloop(self):
    while True: 
      self.sync()
      payout = self.read_packet()
      if self.checkpay(payout):
        self.payload_gen(payout)
      else:
        self.tracker.count_bogus()
	      # print "bogus checksum?" ,payout
  def run_checkloop(self):
    try: 
      self.checkloop()
    except KeyboardInterrupt as Completed:
      self.disconnect()
      print "Disconnected"
      print "Tracker dict: ", self.tracker.snapshots


class Plexer:
  protocol=ThinkGearProtocol
  def __init__(self):
    pass
  @staticmethod
  def signal_quality():
    while True:
      val = yield
      print "Signal Quality: %i %f" % (val, time.time())
  @staticmethod
  def raw_data():
    while True:
      val = yield
      scaled = ( val + 1000 ) / 50
      # print "%12s %6i %s" % (codon, val, ')'.rjust(scaled,'-'))
      # print "Raw Data: ", val
      # print "val #%d: %d" % (val_count, val) 
  @staticmethod
  def power_bin():
    while True:
      val = yield
  @staticmethod
  def blink_event():
    while True:
      val = yield
      print "Blink Event: ", val
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
