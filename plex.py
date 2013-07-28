from collections import deque, defaultdict
from itertools import count
import struct
import time
import serial

#####

def main():
  simple_test()

def simple_test():
  raw_file = 'simple_data'
  parsed_file = 'parsed_data'
  dongle = Dongle()
  try:
    dongle.connect()
    print "Connected. Writing to foo... Hit ^C to stop."
    with open(raw_file, 'wb') as raw_data, open(parsed_file, 'w') as parsed_data:
      dongle.write_raw_and_parsed_files_from_now_on(raw_data, parsed_data)
  except KeyboardInterrupt:
    dongle.disconnect()
    print "Disconnecting dongle"

#####

class Syncbuf:
  def __init__(self, sequence_number, timestamp, buf):
    self.sequence_number = sequence_number
    self.timestamp = timestamp
    self.buf = buf
  def trace(self):
    s = ','.join([str(self.timestamp),
                  str(self.sequence_number),
                  str(self.buf)])
    s = '\n'.join([s,''])
    return s

class ThinkGearProtocol:
  cmd_auto_connect = bytearray([0xc2])
  cmd_disconnect = bytearray([0xc1])
  start_of_connected_status_packet = [ 0xaa, 0xaa, 0x04, 0xd0 ]
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
  conex = {
    0xd0: (3, 'headset connected'),
    0xd1: (2, 'headset not found'),
    0xd2: (3, 'headset disconnected'),
    0xd3: (0, 'request denied'),
    0xd4: (1, 'scan / standby')
  }
  signed_16_bit_val_parser = struct.Struct('>h')
  @classmethod
  def parse_raw_eeg(cls, buf):
    return cls.signed_16_bit_val_parser.unpack_from(buf)

class Sync:
  protocol = ThinkGearProtocol
  def __init__(self, src):
    assert src
    self.src = src
    self.src_it = iter(src) 
    self.syncer = deque([], Sync.protocol.syncnum)
    self.seqint = count()
    self.sb = None
    self.buf = None
  @classmethod
  def b_synced(cls, buf):
    ctl = cls.protocol
    # assert len(buf) <= ctl.syncnum
    return ctl.syncnum == buf.count(ctl.syncbyte)
  def synced(self):
    return self.b_synced(self.syncer)
  def slurp_one(self):
    b = self.src_it.next()
    i = ord(b)
    return i
  def slurp(self):
    while True:
      yield self.slurp_one()
  def check_sync(self, b):
    self.syncer.append(b)
    return self.synced()
  def stampbuf(self):
    timestamp = time()
    sequence_number = self.seqint.next()
    buf = list()
    self.sb = Syncbuf(sequence_number, timestamp, buf)  
    return self.sb
  def thru_sync(self):
    self.syncer.clear()
    for b in self.slurp():
      yield b
      if self.check_sync(b):
        break
    # assert self.synced()
  def thru_checkbyte(self):
    # assert self.synced()
    paylen = self.slurp_one()
    yield paylen
    # assert paylen <= self.protocol.maxpay
    for i in range(paylen):
      yield self.slurp_one()
    checkbyte = self.slurp_one()
    yield checkbyte
  def syncloop(self):
    while True:
      sb = self.stampbuf()
      buf = sb.buf
      buf.extend(self.thru_sync())
      print "sync? buf: ", buf
      buf.extend(self.thru_checkbyte())
      print "paylen? buf: ", buf
      yield self.sb

class Packer:
  protocol = ThinkGearProtocol
  def __init__(self, src):
    self.src = src
    self.sync = Sync(src)
    self.plex = defaultdict(list)
    self.dump_file = None
  def dumpfile(self):
    if self.dump_file == None:
      filepath = '/home/dream/brain_hackary/data/bar_dump'
      self.dump_file = open(filepath, 'w')
    return self.dump_file
  def checkpay(self, sb):
    it = iter(sb.buf)
    try:
      paylen = it.next()
    except StopIteration:
      print "stopped 1"
      return False 
    if paylen > 169:
      if paylen == self.protocol.syncbyte:  
        print "sync packet"
        print "bogus paylen ", paylen
      return False
    # print "paylen ", paylen
    paysum = sum(it.next() for i in range(paylen))
    try:
      paycheck = it.next()
    except StopIteration:
      print "stopped 2 (paycheck) - prematurely ended packet ?"
      return False
      print "sum %d, tx %d, dx %d" % (paysum, (~paysum & 0xff), paycheck)
    return (paycheck == (~paysum & 0xff))
  def payload_gen(self, sb):
    it = iter(sb.buf)
    paylen = it.next()
    signed_16_bit_val_parser = struct.Struct('>h')
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
      try: codon = Packer.protocol.codex[codetype]
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
        if codetype == 0x02: sq.send(val)
        elif codetype == 0x16: be.send(val)
      elif datalen == 2:
        # assert codetype == 0x80
        a = it.next()
        b = it.next()
        c = bytearray(2)
        c[0] = a
        c[1] = b
        # val = (a << 8) + b  # (most significant byte * 256) + (least significant byte)
        t = signed_16_bit_val_parser.unpack(str(c))
        val = t[0]
        rd.send(val)
        scaled = ( val + 1000 ) / 50
        print "%12s %6i %s" % (codon, val, ')'.rjust(scaled,'-'))
      else:
        # assert datalen == 24
        for j in range(0, datalen, 3):
          a = it.next()
          b = it.next()
          c = it.next()
          val = (a << 16) + (b << 8) + c
          pb.send(val)
      paylen -= datalen
      yield (codetype, val)
  def payload(self, sb):
    return list(self.payload_gen(sb))
  def checkloop(self):
    for sb in self.sync.syncloop():
      # sb.trace()
      if not sb.buf:
        break
      if self.checkpay(sb):
        yield self.payload(sb)
  def dumploop(self):
    with self.dumpfile() as f:
      print "opened file"
      for sb in self.sync.syncloop():
        if not sb.buf:
          print "no sb.buf, exiting at sb %d" % sb.sequence_number
          break
        if self.checkpay(sb):
          s = sb.trace()
          # print s
          f.write(s)

class Plexer:
  @staticmethod
  def signal_quality():
    while True:
      val = yield
      print "Signal Quality: ", val
  @staticmethod
  def raw_data():
    while True:
      val = yield
      print "Raw Data: ", val
  @staticmethod
  def power_bin():
    while True:
      val = yield
      print "Power Bin: ", val
  @staticmethod
  def blink_event():
    while True:
      val = yield
      print "Blink Event: ", val

class Tester:
  def __init__(self):
    self.filepath = '/home/dream/brain_hackary/data/Foo.txt'
    # with open(self.filepath, 'rb') as f:
    #   self.src = f.read()
    self.src = Dongle.ser.read()
    self.pack = Packer(self.src)
  def testit(self):
    return self.pack.dumploop()
    # return self.pack.checkloop()

class Dongle:
  cmd_auto_connect = bytearray([0xc2])
  cmd_disconnect = bytearray([0xc1])
  start_of_connected_status_packet = [ 0xaa, 0xaa, 0x04, 0xd0 ]
  def __init__(self):
    self.buffer = []
    self.is_connected = False
    self.index_into_connection_packet = 0
    self.open()
  def open(self):
    baudrate = 115200
    port = '/dev/ttyUSB0'
    timeout = 0.1
    self.ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
  def read(self):
    buffer = bytearray(256)
    num_bytes_read = self.ser.readinto(buffer)
    # parse it, and set flags
    for i in range(num_bytes_read):
      b = buffer[i]
      if b == Dongle.start_of_connected_status_packet[self.index_into_connection_packet]:
        self.index_into_connection_packet += 1
        if self.index_into_connection_packet >= len(Dongle.start_of_connected_status_packet):
          self.is_connected = True
          self.index_into_connection_packet = 0
      else:
        self.index_into_connection_packet = 0
  def connect(self):
    while True:
      self.read()
      if self.is_connected:
        return
      self.ser.write(Dongle.cmd_auto_connect)
      print "Cannot connect, sleeping for 2s"
      time.sleep(2)
  def write_everything_to_file_from_now_on(self, f):
    while True:
      f.write(self.ser.read())
  def write_raw_and_parsed_files_from_now_on(self, raw_f, parsed_f):
    while True:
      bufbytes = self.ser.read()
      raw_f.write(bufbytes)
      # Send raw data stream through parser, and write parsed data to file.
      parsedbytes = Sync(src=bufbytes)
      parsed_f.write(parsedbytes)
  def disconnect(self):
    self.ser.write(Dongle.cmd_disconnect)
    self.is_connected = False


if __name__ == '__main__':
  main()
