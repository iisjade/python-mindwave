from collections import deque, defaultdict
from itertools import count, takewhile
import struct
import time
import serial

#####

def main():
  write_raw_test()

#####

class ThinkGearProtocol:
  syncnum = 2
  syncbyte = 0xaa
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
  def reset(self):
    self.syncer.clear()
  def sync_it(self, src):
    self.reset()
    while not self.synced(src.next()):
      pass

class Dongle:
  protocol = ThinkGearProtocol
  def __init__(self):
    baudrate = 115200
    port = '/dev/ttyUSB0'  # TODO handle arbitrary (changed) dev address
    timeout = 0.01
    try: self.ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
    except:
      for i in range(1,4):
        port = '/dev/ttyUSB' + str(i)
        try: self.ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
        except: continue
  def control(self, val):
    self.ser.write(bytearray([val]))
  def connect(self):
    self.control(self.protocol.autoconnect_byte)
  def disconnect(self):
    print 'sending disconnect'
    self.control(self.protocol.disconnect_byte)
  def bytevals(self):
    bufsize = 1024
    buf = bytearray(bufsize)
    while True:
      n = self.ser.readinto(buf)
      for i in range(n): 
        b = buf[i] 
        yield b

class Payloader:
  def __init__(self, src):
    self.protocol = ThinkGearProtocol
    self.src = src
    self.syncer = Sync()
  def read_sync(self):
    it = self.src
    self.syncer.reset()
    while not self.syncer.synced(it.next()):
      pass
  def read_paylen_payload_and_checksum(self):
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
  def parse(self, payout):
    pass


class Packer:
  def __init__(self):
    self.protocol = ThinkGearProtocol
    self.is_connected = False
    self.dongle = Dongle()
    self.src = self.dongle.bytevals()
    self.syncer = Sync()
  def synced_src(self):
    self.syncer.sync_it(self.src)
    return self.src
  def connect_and_confirm(self):
    self.dongle.connect()
    confirmed = False
    while not confirmed:
      it = self.synced_src()
      paylen = it.next()
      if paylen != 4:
        continue
      codetype = it.next()
      if codetype != self.protocol.connected_code:
        continue
      confirmed = True
      print 'connected!'
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
    # Initializing co-routines 
    sq = Plexer.signal_quality()
    sq.send(None) #OR sq.next()
    rd = Plexer.raw_data()
    rd.send(None)
    pb = Plexer.power_bin()
    pb.send(None)
    be = Plexer.blink_event() 
    be.send(None)
    while paylen > 0:
      try:
        codetype = it.next()
        paylen -= 1
      except StopIteration:
        print "stopped 3 (codetype)"
        break
      try: codon = self.protocol.codex[codetype]
      except KeyError:
        print "parse error unknown codetype ", codetype
        break
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
        elif codetype == 0x16: 
          be.send(val)
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
        rd.send(codon)
      else:
        # assert datalen == 24
        for j in range(0, datalen, 3):
          a = it.next()
          b = it.next()
          c = it.next()
          val = (a << 16) + (b << 8) + c
          pb.send(val)
      paylen -= datalen
      # yield (codetype, val)
  def checkloop(self):
    pay = Payloader(self.src)
    while True: 
      self.syncer.sync_it(self.src)
      payout = pay.read_paylen_payload_and_checksum()
      if self.checkpay(payout):
        self.payload_gen(payout)
        # pay.parse(payout)
      else:
	      print "bogus checksum?"

class Plexer:
  protocol=ThinkGearProtocol
  @staticmethod
  def signal_quality():
    counter = 0
    while True:
      baseline = time.time()
      val = yield
      counter += 1
      print "Signal Quality: %s, Count#: %i, Timestamp: %s" % (val, counter, time.time()-baseline)
  @staticmethod
  def raw_data():
    while True:
      val = yield
      codon = yield
      scaled = ( val + 1000 ) / 50
      # print "%12s %6i %s" % (codon, val, ')'.rjust(scaled,'-'))
      # print "Raw Data: ", val
  @staticmethod
  def power_bin():
    while True:
      val = yield
      # print "Power Bin: %s, Timestamp: %s" % (val, time.time())
  @staticmethod
  def blink_event():
    while True:
      val = yield
      print "Blink Event: ", val


if __name__ == '__main__':
  main()

def write_raw_test():
  raw_file = 'raw_data'
  parsed_file = 'parsed_data'
  dongle = Dongle()
  try:
    dongle.connect()
    print "Connected. Writing ./raw_data... Hit ^C to stop."
    with open(raw_file, 'wb') as raw_data:
      dongle.write_raw_file(raw_data)
  except KeyboardInterrupt:
    dongle.disconnect()
    print "Disconnecting dongle"

