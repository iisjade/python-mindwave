from collections import deque, defaultdict
from itertools import count
import struct
import time
import serial

#####

def main():
  write_raw_test()

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

#####

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
  def __init__(self):
    self.syncer = deque([], Sync.protocol.syncnum)
  def synced(self, b):
    self.syncer.append(b)
    return self.syncer.count(Sync.protocol.syncbyte) == len(self.syncer)

class RawBuf:
  def __init__(self, outfile):
    self.outfile = outfile
    self.src = Dongle.bytestream
    self.outbuf = list()
    self.buflen = 1024
  def gobble(self):
    b = self.src.next()
    self.outbuf.append(b)
    if len(self.outbuf) == self.buflen:
      self.outfile.write(self.outbuf)
      self.outbuf.clear()
    yield b

class Packer:
  protocol = ThinkGearProtocol
  def __init__(self):
    self.filepath = 'raw_data_output'
    self.rawfile = open(self.filepath, 'wb')
  def checkpay(self, stampbuf, rawfile):
    rb = RawBuf(stampbuf, rawfile)
    it = rb.gobble
    try:
      paylen = it.next()
    except StopIteration:
      print "stopped 1"
      return False 
    if paylen > 169:
      if paylen == self.protocol.syncbyte:  
        print "sync packet"
      else:
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
  def payload_gen(self, bytestream):
    it = bytestream
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
  def payload(self, stamped_buffer):
    return list(self.payload_gen(stamped_buffer))
  def checkloop(self):
    seq = count()
    while True: 
      stamped_buffer = Syncbuf(seq.next())
      stamped_buffer.trace()
      if self.checkpay(stamped_buffer):
        yield self.payload(stamped_buffer)

class Syncbuf:
  def __init__(self, sequence_number):
    self.sequence_number = sequence_number
    self.timestamp = time.time()
    self.buf = list()
  def trace(self):
    s = ','.join([str(self.timestamp),
                  str(self.sequence_number),
                  str(self.buf)])
    s = '\n'.join([s,''])
    return s

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

class Dongle:
  protocol = ThinkGearProtocol
  def __init__(self):
    self.buffer = []
    self.is_connected = False
    baudrate = 115200
    port = '/dev/ttyUSB0'
    timeout = 0.1
    self.ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
  def connect(self):
    index_into_connection_packet = 0
    while True:
      buffer = bytearray(256)
      num_bytes_read = self.ser.readinto(buffer)
      # parse it, and set flags
      for i in range(num_bytes_read):
        b = buffer[i]
        if b == Dongle.protocol.start_of_connected_status_packet[index_into_connection_packet]:
          index_into_connection_packet += 1
          if index_into_connection_packet >= len(Dongle.protocol.start_of_connected_status_packet):
            self.is_connected = True
            index_into_connection_packet = 0
        else:
          index_into_connection_packet = 0
      if self.is_connected:
        return
      self.ser.write(Dongle.protocol.cmd_auto_connect)
      print "Cannot connect, sleeping for 2s"
      time.sleep(2)
  def write_raw_file(self, raw_f):
    while True:
      bufbytes = self.ser.read()
      raw_f.write(bufbytes)
  def bytestream(self):
    while True:
      bufbytes = self.ser.read()
      # Send raw data stream through parser, and write parsed data to file.
      for b in bufbytes:
        yield b
# parser needs to handle stream
# stream as presented by serial read API
#   is a sequence of strings
  def disconnect(self):
    self.ser.write(Dongle.protocol.cmd_disconnect)
    self.is_connected = False


if __name__ == '__main__':
  main()
