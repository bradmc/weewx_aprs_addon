# this should be at the top with the other import statements
import serial

# this new class should probably live underneath the CWOP class
#
#===============================================================================
#                             class APRS
#===============================================================================

class APRS(REST):
    """Upload using the APRS protocol. """

    def __init__(self, site, **kwargs):
        """Initialize for a post to APRS.
        
        site: The upload site ("APRS")
        
        port: Serial port to which the TNC is connected.

        baudrate: Serial port baudrate setting

        databits: Serial port databits setting

        parity: Serial port parity setting

        stopbits: Serial port stopbits steting

        unproto: the UNPROTO setting for the TNC (e.g., "aprs via wide2-2")

        status_message: Any status message that should be included in an additional packet
        without location or time.

        enabled: any value less than 1 will disable APRS packet transmissions.

        station: The name of the station (e.g., "CW1234") as a string [Required]
        
        latitude: Station latitude [Required]
        
        longitude: Station longitude [Required]

        hardware: Station hardware (eg, "VantagePro") [Required]
        
        interval: The interval in seconds between posts [Optional. 
        Default is 0 (send every post)]
        
        stale: How old a record can be before it will not be 
        used for a catchup [Optional. Default is 1800]
        
        max_tries: Max # of tries before giving up [Optional. Default is 3]

        APRS does not like heavy traffic on their servers, so they encourage
        posts roughly every 15 minutes and at most every 5 minutes. So,
        key 'interval' should be set to no less than 300, but preferably 900.
        Setting it to zero will cause every archive record to be posted.
        """
        self.site      = site
        self.port      = kwargs['port']
        self.baudrate  = int(kwargs['baudrate'])
        self.databits  = int(kwargs['databits'])
        self.parity    = kwargs['parity']
        self.stopbits  = int(kwargs['stopbits'])
        self.station   = kwargs['station'].upper()
        self.unproto   = kwargs['unproto']
        self.status_message   = kwargs['status_message']
        self.enabled   = int(kwargs['enabled'])
        self.latitude  = float(kwargs['latitude'])
        self.longitude = float(kwargs['longitude'])
        self.hardware  = kwargs['hardware']
        self.interval  = int(kwargs.get('interval', 0))
        self.stale     = int(kwargs.get('stale', 1800))
        self.max_tries = int(kwargs.get('max_tries', 3))
        
        self._lastpost = None
        
    def postData(self, archive, time_ts):
        """Post data to APRS, using the APRS protocol."""
        
        _last_ts = archive.lastGoodStamp()

        # There are a variety of reasons to skip a post to APRS.

        # APRS is turned off in config
        if self.enabled == 0:
            raise SkippedPost, "APRS: Turned off in configuration. (enabled = 0)"

        # 1. They do not allow backfilling, so there is no reason
        # to post anything other than the latest record:
        if time_ts != _last_ts:
            raise SkippedPost, "APRS: Record %s is not last record" %\
                    (weeutil.weeutil.timestamp_to_string(time_ts), )

        # 2. No reason to post an old out-of-date record.
        _how_old = time.time() - time_ts
        if _how_old > self.stale:
            raise SkippedPost, "APRS: Record %s is stale (%d > %d)." %\
                    (weeutil.weeutil.timestamp_to_string(time_ts), _how_old, self.stale)
        
        # 3. Finally, we don't want to post more often than the interval
        if self._lastpost and time_ts - self._lastpost < self.interval:
            raise SkippedPost, "APRS: Wait interval (%d) has not passed." %\
                    (self.interval, )
        
        # Get the data record for this time:
        _record = self.extractRecordFrom(archive, time_ts)

        # 4. Units must be US Customary. We could add code to convert, but for
        # now this will do:
        if _record['usUnits'] != weewx.US:
            raise SkippedPost, "APRS: Units must be US Customary."
        
        # Get the login and packet strings:
        _tnc_packet = self.getTNCPacket(_record)

        # Send packet to serial port
        _ser = serial.Serial(self.port)
        _ser.baudrate = self.baudrate
        _ser.bytesize = self.databits
        _ser.parity = self.parity
        _ser.stopbits = self.stopbits
        _ser.flushOutput()
        _ser.flushInput()
        # put the tnc in command mode, equivalent to ctrl-C
        _ser.write("\x03")
        time.sleep(1)
        _ser.write("mycall " + self.station + "\r")
        time.sleep(1)
        _ser.write("unproto " + self.unproto + "\r")
        time.sleep(1)
        _ser.write("conv\r")
        time.sleep(1)
        _ser.write(_tnc_packet + "\r")
        time.sleep(1)
        _ser.write(">" + self.status_message + "\r")
        _ser.write("\x03")
        _ser.flushInput()
        _ser.flushOutput()

        try:
            _ser.close()
        except:
            pass

        self._lastpost = time_ts
        

    def getTNCPacket(self, record):
        """Form the TNC2 packet used by APRS."""
        
        # TODO: Allow native metric units. Convert as necessary for APRS.
        
        # Time:
        time_tt = time.gmtime(record['dateTime'])
        time_str = time.strftime("@%d%H%Mz", time_tt)

        # Position:
        lat_str = weeutil.weeutil.latlon_string(self.latitude, ('N', 'S'), 'lat')
        lon_str = weeutil.weeutil.latlon_string(self.longitude, ('E', 'W'), 'lon')
        latlon_str = '%s%s%s/%s%s%s' % (lat_str + lon_str)

        # Wind and temperature
        wt_list = []
        for obs_type in ('windDir', 'windSpeed', 'windGust', 'outTemp'):
            wt_list.append("%03d" % record[obs_type] if record[obs_type] is not None else '...')
        wt_str = "_%s/%sg%st%s" % tuple(wt_list)

        # Rain
        rain_list = []
        for obs_type in ('rain', 'rain24', 'dailyrain'):
            rain_list.append("%03d" % (record[obs_type]*100.0) if record[obs_type] is not None else '...')
        rain_str = "r%sp%sP%s" % tuple(rain_list)
        
        # Barometer:
        if record['barometer'] is None:
            baro_str = "b....."
        else:
            # Figure out what unit type barometric pressure is in for this record:
            (u, g) = weewx.units.getStandardUnitType(record['usUnits'], 'barometer')
            # Convert to millibars:
            baro = weewx.units.convert((record['barometer'], u, g), 'mbar')
            baro_str = "b%5d" % (baro[0]*10.0)

        # Humidity:
        humidity = record['outHumidity']
        if humidity is None:
            humid_str = "h.."
        else:
            humid_str = ("h%2d" % humidity) if humidity < 100.0 else "h00"
            
        # Radiation:
        radiation = record['radiation']
        if radiation is None:
            radiation_str = ""
        elif radiation < 1000.0:
            radiation_str = "L%03d" % radiation
        elif radiation < 2000.0:
            radiation_str = "l%03d" % (radiation - 1000)
        else:
            radiation_str = ""

        # Station hardware:
        hardware_str = ".DsVP" if self.hardware=="VantagePro" else ".Unkn"
        
        tnc_packet = time_str + latlon_str + wt_str + rain_str +\
                     baro_str + humid_str + radiation_str + hardware_str

        return tnc_packet

