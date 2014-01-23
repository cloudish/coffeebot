#!/usr/bin/python

# Python library for Adafruit I2C/SPI LCD backpack for Raspberry Pi.
# Written by Mike Simpson.  MIT license.

# This is based on code from Adafruit, lrvick and LiquidCrystal.
# Adafruit - https://github.com/adafruit/Adafruit-Raspberry-Pi-Python-Code 
# lrvic - https://github.com/lrvick/raspi-hd44780/blob/master/hd44780.py
# LiquidCrystal - https://github.com/arduino/Arduino/blob/master/libraries/LiquidCrystal/LiquidCrystal.cpp

from Adafruit_I2C import Adafruit_I2C
from time import sleep

class Adafruit_CharLCDBackpack(Adafruit_I2C):
    # ----------------------------------------------------------------------
    # Constants

    # Port expander registers
    MCP23008_IODIR      = 0x00
    MCP23008_IPOL       = 0x01
    MCP23008_GPINTEN    = 0x02
    MCP23008_DEFVAL     = 0x03
    MCP23008_INTCON     = 0x04
    MCP23008_IOCON      = 0x05
    MCP23008_GPPU       = 0x06
    MCP23008_INTF       = 0x07
    MCP23008_INTCAP     = 0x08
    MCP23008_GPIO       = 0x09
    MCP23008_OLAT       = 0x0A

    # LED colors
    OFF                     = 0x00
    ON                      = 0x01

    # LCD Commands
    LCD_CLEARDISPLAY        = 0x01
    LCD_RETURNHOME          = 0x02
    LCD_ENTRYMODESET        = 0x04
    LCD_DISPLAYCONTROL      = 0x08
    LCD_CURSORSHIFT         = 0x10
    LCD_FUNCTIONSET         = 0x20
    LCD_SETCGRAMADDR        = 0x40
    LCD_SETDDRAMADDR        = 0x80

    # Flags for display on/off control
    LCD_DISPLAYON           = 0x04
    LCD_DISPLAYOFF          = 0x00
    LCD_CURSORON            = 0x02
    LCD_CURSOROFF           = 0x00
    LCD_BLINKON             = 0x01
    LCD_BLINKOFF            = 0x00

    # Flags for display entry mode
    LCD_ENTRYRIGHT          = 0x00
    LCD_ENTRYLEFT           = 0x02
    LCD_ENTRYSHIFTINCREMENT = 0x01
    LCD_ENTRYSHIFTDECREMENT = 0x00

    # Flags for display/cursor shift
    LCD_DISPLAYMOVE = 0x08
    LCD_CURSORMOVE  = 0x00
    LCD_MOVERIGHT   = 0x04
    LCD_MOVELEFT    = 0x00

    # ----------------------------------------------------------------------
    # Constructor

    def __init__(self, busnum=1, addr=0x20, debug=False):
        self.i2c = Adafruit_I2C(addr, busnum, debug)

        # I2C is relatively slow.  MCP output port states are cached
        # so we don't need to constantly poll-and-change bit states.
        #self.porta, self.gpio, self.ddrb = 0, 0, 0b00010000
        self.porta, self.gpio, self.ddrb = 0, 0, 0b00000010

        # Set MCP23008 IOCON register to sequential operation.
        self.i2c.bus.write_byte_data(
          self.i2c.address, self.MCP23008_IOCON, 0)

        # Brute force reload ALL registers to known state.  This also
        # sets up all the input pins, pull-ups, etc. for the backpack.
        self.i2c.bus.write_i2c_block_data(
          self.i2c.address,
          0,
          [ 0b11111111,   #IODIR
            0b00000000,   #IOPOL
            0b00000000,   #GPINTEN
            0b00000000,   #DEFVAL
            0b00000000,   #INTCON
            0b00000000,   #IOCON
            0b00000000,   #GPPU
            0b00000000,   #INTF
            0b00000000,   #INTCAP
            0b00000000,   #GPIO
            0b00000000 ]) #OLAT

        # Disable sequential operation.
        # The address register will no longer increment 
        # automatically after this -- multi-byte operations 
        # must be broken down into single-byte calls.
        self.i2c.bus.write_byte_data(
          self.i2c.address, self.MCP23008_IOCON, 1)

        self.displayshift   = (self.LCD_CURSORMOVE |
                               self.LCD_MOVERIGHT)
        self.displaymode    = (self.LCD_ENTRYLEFT |
                               self.LCD_ENTRYSHIFTDECREMENT)
        self.displaycontrol = (self.LCD_DISPLAYON |
                               self.LCD_CURSOROFF |
                               self.LCD_BLINKOFF)

        self.write(0x33) # Init
        self.write(0x32) # Init
        self.write(0x28) # 2 line 5x8 matrix
        self.write(self.LCD_CLEARDISPLAY)
        self.write(self.LCD_CURSORSHIFT    | self.displayshift)
        self.write(self.LCD_ENTRYMODESET   | self.displaymode)
        self.write(self.LCD_DISPLAYCONTROL | self.displaycontrol)
        self.write(self.LCD_RETURNHOME)

    # ----------------------------------------------------------------------
    # Write operations

    ## (Old) The LCD data pins (D4-D7) connect to MCP pins 12-9 (PORTB4-1), in
    ## that order.  Because this sequence is 'reversed,' a direct shift
    ## won't work.  This table remaps 4-bit data values to MCP GPIO
    ## outputs, incorporating both the reverse and shift.
    #flip = ( 0b00000000, 0b00010000, 0b00001000, 0b00011000,
    #         0b00000100, 0b00010100, 0b00001100, 0b00011100,
    #         0b00000010, 0b00010010, 0b00001010, 0b00011010,
    #         0b00000110, 0b00010110, 0b00001110, 0b00011110 )

    # Low-level 4-bit interface for LCD output.  This doesn't actually
    # write data, just returns a byte array of the GPIO state over time.
    # Can concatenate the output of multiple calls (up to 8) for more
    # efficient batch write.
    def out4(self, bitmask, value):
        #hi = bitmask | self.flip[value >> 4]
        #lo = bitmask | self.flip[value & 0x0F]
        hi = bitmask | ((value >> 4) << 1)
        lo = bitmask | ((value & 0x0F) << 1)
        return [hi | 0b00100000, hi, lo | 0b00100000, lo]

    # The speed of LCD accesses is inherently limited by I2C through the
    # port expander.  A 'well behaved program' is expected to poll the
    # LCD to know that a prior instruction completed.  But the timing of
    # most instructions is a known uniform 37 mS.  The enable strobe
    # can't even be twiddled that fast through I2C, so it's a safe bet
    # with these instructions to not waste time polling (which requires
    # several I2C transfers for reconfiguring the port direction).
    # The D7 pin is set as input when a potentially time-consuming
    # instruction has been issued (e.g. screen clear), as well as on
    # startup, and polling will then occur before more commands or data
    # are issued.

    pollables = ( LCD_CLEARDISPLAY, LCD_RETURNHOME )

    # Write byte, list or string value to LCD
    def write(self, value, char_mode=False):
        """ Send command/data to LCD """

        # If pin D7 is in input state, poll LCD busy flag until clear.
        #if self.ddrb & 0b00010000:
        if self.ddrb & 0b00000010:
            lo = (self.gpio & 0b00000001) | 0b01000000
            hi = lo | 0b00100000 # E=1 (strobe)

            self.i2c.bus.write_byte_data(
              self.i2c.address, self.MCP23008_GPIO, lo)

            while True:
                # Strobe high (enable)
                self.i2c.bus.write_byte(self.i2c.address, hi)

                # First nybble contains busy state
                bits = self.i2c.bus.read_byte(self.i2c.address)

                # Strobe low, high, low.  Second nybble (A3) is ignored.
                self.i2c.bus.write_i2c_block_data(
                  self.i2c.address, self.MCP23008_GPIO, [lo, hi, lo])

                if (bits & 0b00000010) == 0: break # D7=0, not busy

            self.gpio = lo

            # Polling complete, change D7 pin to output
            #self.ddrb &= 0b11101111
            self.ddrb &= 0b11111101

            self.i2c.bus.write_byte_data(self.i2c.address,
              self.MCP23008_IODIR, self.ddrb)

        bitmask = self.gpio & 0b00000001   # Mask out GPIO LCD control bits
        if char_mode: bitmask |= 0b10000000 # Set data bit if not a command

        # If string or list, iterate through multiple write ops
        if isinstance(value, str):
            last = len(value) - 1 # Last character in string
            data = []             # Start with blank list

            for i, v in enumerate(value): # For each character...
                # Append 4 bytes to list representing GPIO over time.
                # First the high 4 data bits with strobe (enable) set
                # and unset, then same with low 4 data bits (strobe 1/0).
                data.extend(self.out4(bitmask, ord(v)))

                # I2C block data write is limited to 32 bytes max.
                # If limit reached, write data so far and clear.
                # Also do this on last byte if not otherwise handled.
                if (len(data) >= 32) or (i == last):
                    self.i2c.bus.write_i2c_block_data(
                      self.i2c.address, self.MCP23008_GPIO, data)
                    self.gpio = data[-1] # Save state of last byte out
                    data       = []       # Clear list for next iteration
        elif isinstance(value, list):
            # Same as above, but for list instead of string
            last = len(value) - 1
            data = []

            for i, v in enumerate(value):
                data.extend(self.out4(bitmask, v))

                if (len(data) >= 32) or (i == last):
                    self.i2c.bus.write_i2c_block_data(
                      self.i2c.address, self.MCP23008_GPIO, data)
                    self.gpio = data[-1]
                    data       = []
        else:
            # Single byte
            data = self.out4(bitmask, value)
            self.i2c.bus.write_i2c_block_data(
              self.i2c.address, self.MCP23008_GPIO, data)
            self.gpio = data[-1]

        # If a poll-worthy instruction was issued, reconfigure D7
        # pin as input to indicate need for polling on next call.
        if (not char_mode) and (value in self.pollables):
            #self.ddrb |= 0b00010000
            self.ddrb |= 0b00000010
            self.i2c.bus.write_byte_data(self.i2c.address,
              self.MCP23008_IODIR, self.ddrb)


    # ----------------------------------------------------------------------
    # Utility methods

    def begin(self, cols, lines):
        self.currline = 0
        self.numlines = lines
        self.clear()

    # Puts the MCP23008 back in sequential write mode so
    # that other code using the 'classic' library can still work.
    # Any code using this newer version of the library should
    # consider adding an atexit() handler that calls this.
    def stop(self):
        # self.porta seems to be unused
        self.porta = 0b11000000  # Turn off LEDs on the way out

        self.gpio = 0b00000001
        sleep(0.0015)

        self.i2c.bus.write_byte_data(
          self.i2c.address, self.MCP23008_IOCON, 0)

        self.i2c.bus.write_i2c_block_data(
          self.i2c.address,
          0,
          [ 0b11111111,   #IODIR
            0b00000000,   #IOPOL
            0b00000000,   #GPINTEN
            0b00000000,   #DEFVAL
            0b00000000,   #INTCON
            0b00000000,   #IOCON
            0b00000000,   #GPPU
            0b00000000,   #INTF
            0b00000000,   #INTCAP
            0b00000000,   #GPIO
            0b00000000 ]) #OLAT

    def clear(self):
        self.write(self.LCD_CLEARDISPLAY)

    def home(self):
        self.write(self.LCD_RETURNHOME)

    row_offsets = ( 0x00, 0x40, 0x14, 0x54 )

    def setCursor(self, col, row):
        if row > self.numlines: row = self.numlines - 1
        elif row < 0:           row = 0
        self.write(self.LCD_SETDDRAMADDR | (col + self.row_offsets[row]))

    def display(self):
        """ Turn the display on (quickly) """
        self.displaycontrol |= self.LCD_DISPLAYON
        self.write(self.LCD_DISPLAYCONTROL | self.displaycontrol)

    def noDisplay(self):
        """ Turn the display off (quickly) """
        self.displaycontrol &= ~self.LCD_DISPLAYON
        self.write(self.LCD_DISPLAYCONTROL | self.displaycontrol)

    def cursor(self):
        """ Underline cursor on """
        self.displaycontrol |= self.LCD_CURSORON
        self.write(self.LCD_DISPLAYCONTROL | self.displaycontrol)

    def noCursor(self):
        """ Underline cursor off """
        self.displaycontrol &= ~self.LCD_CURSORON
        self.write(self.LCD_DISPLAYCONTROL | self.displaycontrol)

    def ToggleCursor(self):
        """ Toggles the underline cursor On/Off """
        self.displaycontrol ^= self.LCD_CURSORON
        self.write(self.LCD_DISPLAYCONTROL | self.displaycontrol)

    def blink(self):
        """ Turn on the blinking cursor """
        self.displaycontrol |= self.LCD_BLINKON
        self.write(self.LCD_DISPLAYCONTROL | self.displaycontrol)

    def noBlink(self):
        """ Turn off the blinking cursor """
        self.displaycontrol &= ~self.LCD_BLINKON
        self.write(self.LCD_DISPLAYCONTROL | self.displaycontrol)

    def ToggleBlink(self):
        """ Toggles the blinking cursor """
        self.displaycontrol ^= self.LCD_BLINKON
        self.write(self.LCD_DISPLAYCONTROL | self.displaycontrol)

    def scrollDisplayLeft(self):
        """ These commands scroll the display without changing the RAM """
        self.displayshift = self.LCD_DISPLAYMOVE | self.LCD_MOVELEFT
        self.write(self.LCD_CURSORSHIFT | self.displayshift)

    def scrollDisplayRight(self):
        """ These commands scroll the display without changing the RAM """
        self.displayshift = self.LCD_DISPLAYMOVE | self.LCD_MOVERIGHT
        self.write(self.LCD_CURSORSHIFT | self.displayshift)

    def leftToRight(self):
        """ This is for text that flows left to right """
        self.displaymode |= self.LCD_ENTRYLEFT
        self.write(self.LCD_ENTRYMODESET | self.displaymode)

    def rightToLeft(self):
        """ This is for text that flows right to left """
        self.displaymode &= ~self.LCD_ENTRYLEFT
        self.write(self.LCD_ENTRYMODESET | self.displaymode)

    def autoscroll(self):
        """ This will 'right justify' text from the cursor """
        self.displaymode |= self.LCD_ENTRYSHIFTINCREMENT
        self.write(self.LCD_ENTRYMODESET | self.displaymode)

    def noAutoscroll(self):
        """ This will 'left justify' text from the cursor """
        self.displaymode &= ~self.LCD_ENTRYSHIFTINCREMENT
        self.write(self.LCD_ENTRYMODESET | self.displaymode)

    def createChar(self, location, bitmap):
        self.write(self.LCD_SETCGRAMADDR | ((location & 7) << 3))
        self.write(bitmap, True)
        self.write(self.LCD_SETDDRAMADDR)

    def message(self, text):
        """ Send string to LCD. Newline wraps to second line"""
        lines = str(text).split('\n')    # Split at newline(s)

        for i, line in enumerate(lines): # For each substring...
            if i > 0:                    # If newline(s),
                self.write(0xC0)         #  set DDRAM address to 2nd line

            self.write(line, True)       # Issue substring

    # ----------------------------------------------------------------------
    # Test code

if __name__ == '__main__':

    lcd = Adafruit_CharLCDBackpack()
    lcd.begin(16, 2)
    lcd.clear()
    lcd.display()
    lcd.message("Adafruit LCD\nBackpack!")
    sleep(1)
    lcd.noDisplay()
    sleep(1)
    lcd.message("TEST")