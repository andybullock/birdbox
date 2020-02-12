#!/usr/local/bin/python
import sys
import getopt		 # Used for command line argument parsing
import subprocess	 # Used for system uptime function
import os
import datetime as dt	 # Used for file count function
import time
import urllib            # URL functions
import urllib2           # URL functions
import RPi.GPIO as GPIO  # light sensor
from picamera import PiCamera
from datetime import timedelta
import logging		 # used for output to log
#import mylib		 # used for output to log

# get script path, so we know where to write logs to
home_dir = os.path.dirname(sys.argv[0])
debug_log = home_dir+"/sensor.debug.log"

# logfile, for debugging purposes
logging.basicConfig(filename=debug_log, level=logging.INFO, format='%(asctime)s - %(levelname)8s() - %(funcName)15s() - %(message)s', datefmt='%d/%m/%Y %H:%M:%S')
logging.info('---------------------------------------------------------')
logging.info('Started.')

# ThingSpeak channel details and API key
THINGSPEAKKEY = 'AUCOM96GOU6KNC4N'
THINGSPEAKURL = 'https://api.thingspeak.com/update'

# default temperature scale (c/f)
temp_scale = "c"
# convert temp scale to lowercase otherwise comparison check will not work
temp_scale = temp_scale.lower()

# define light threshold activation value. Anything > than this value will turn irled's on
ldr_threshold = 3500

# command line arguments
# we always want the results to be uploaded to ThingSpeak, unless we override it on the command line (for testing)
# default = true (always upload results)
upload_results = True 
options, args = getopt.getopt(sys.argv[1:], "nu", ['noupdate'])
for opt, arg in options:
	if opt in ("--noupdate", "-nu"):
		# do not upload results if set as a command argument
		upload_results = False
		print "***** Detected '--noupdate' option *****"
		logging.info('%s command arguments specified - setting upload_results to false',options)

# set the GPIO mode to gpio.board
# this option specifies that you are referring to the pins by the number of the pin the the plug - i.e the numbers printed on the board
GPIO.setmode(GPIO.BOARD)
# disable warnings, otherwise the log will get lots of warnings.  This is because the irled ring function needs
# to stay 'on' at night.  If we clean up the gpio on exit, it will turn off.  So, we know that this channel is
# in use if the leds are on and hence need to ignore the messages as we know this is the case
GPIO.setwarnings(False)

# define the GPIO pins
# these are the physical pin numbers, GPIOs are translated to the right
ldr_gpio_pin = 11         #GPIO 17 - Used by the Light Dependent Resistor (to check ambient light level)
irled_ring_gpio_pin = 19  #GPIO 10 - Used by the Infrared LED ring (for night vision)

# load drivers for temperature sensors
# these are connected to pin 7 (gpio 4) but not initialised in this script
# as the readings are parsed from the output file defined below
os.system('modprobe w1-gpio')
os.system('modprobe w1-therm')

# temperature sensor paths, so we can parse the temperature
# need to make sure these are mapped to the cariables correctly, as hardware changes can affect the paths
temp_sensor_internal_path = '/sys/bus/w1/devices/28-80000003d485/w1_slave' # internal sensor
temp_sensor_external_path = '/sys/bus/w1/devices/28-80000003f262/w1_slave' # external sensor
temp_sensor_roof_path = '/sys/bus/w1/devices/28-0316620bf9ff/w1_slave' # roof space (internal) sensor

# set disk threshold as % free and disk partition to check
# we need to perform an action (such as archive off videos and images) if current free space drops below this
disk_threshold = 80
disk_partition = "/"




#------   function to check disk space   ------#  
def disk_usage(path):
  disk = os.statvfs(path)
  disk_percent_used = (disk.f_blocks - disk.f_bfree) * 100 / (disk.f_blocks -disk.f_bfree + disk.f_bavail) + 1
  
  if disk_percent_used < disk_threshold :
  	logging.info('OK - disk %s at %s%% used, threshold set at %s%%',disk_partition,disk_percent_used,disk_threshold)
	#print "OK - disk %s at %s%% free"% (partition,disk_percent)
  else :
  	logging.critical('CRITICAL - disk %s at %s%% used, threshold set at %s%%',disk_partition,disk_percent_used,disk_threshold)
	#print "CRITICAL - disk %s at %s%% free"% (partition,disk_percent)
	#print "Threshold set at: %s%%"%(threshold)
  return disk_percent_used


#------   function to count files in a directory   ------#
def count_files():
  now = dt.datetime.now()
  ## ago should be the same as the cron schedule for running this scipt
  ago = now-dt.timedelta(minutes=15)
  filecount = 0
  media_dir = "/var/www/html/media"
  
  for root,dirs,files in os.walk(media_dir):
  # apply a filter so that we only include *.mp4 files (otherwise it'll count the snapshot (*.jpg) and video (*.mp4) as 2 separate motion sensor activities, when it's only 1.
      files = [ fi for fi in files if not fi.endswith(".mp4") ]
      for fname in files:
          path = os.path.join(root, fname)
          st = os.stat(path)
          mtime = dt.datetime.fromtimestamp(st.st_ctime)
          if mtime > ago:
            filecount += 1
            #print('%s modified %s'%(path, mtime))
  logging.info('Found %s new files older than 15 minutes',filecount)
  return filecount


#------   funtion to send data to ThingSpeak   ------#
def sendData(url,key,field1,field2,field3,field4,field5,field6,field7,temp_int1,temp_ext1,temp_elec1,temp_cpu,amb_light,irled,video_captures):
  logging.info('Received arguments: %s',locals())
  """
  Send event to internet site
  """
  if (temp_int1 == 5000 or temp_ext1 == 5000 or temp_elec1 == 5000) :
  	logging.info('Skipping temperature sensor data due to 1 or more sensor issues. Generating remaining data to send...')
  	values = {'api_key' : key,'field4' : temp_cpu,'field5' : amb_light,'field6' : irled ,'field7' : video_captures}	
  else :
  	logging.info('All sensor readings look OK, generating data to send...')
  	values = {'api_key' : key,'field1' : temp_int1,'field2' : temp_ext1,'field3' : temp_elec1,'field4' : temp_cpu,'field5' : amb_light,'field6' : irled,'field7' : video_captures}
  
  logging.info('Values to send to THINGSPEAK:  %s',values)
  
  # if we've asked to not upload the results, quit the function
  if upload_results == False : 
  	logging.warning('Skipping upload to THINGSPEAK due to manual override')
    	return
    	
  # otherwise, upload data	
  postdata = urllib.urlencode(values)
  req = urllib2.Request(url, postdata)

  log = time.strftime("%d-%m-%Y,%H:%M:%S") + ","
  #log = log + "{:.1f}C".format(temp) + ","
  #log = log + "{:.2f}mBar".format(pres) + ","

  try:
    # Send data to Thingspeak
    logging.info('Attempting to send update to THINGSPEAK...')
    response = urllib2.urlopen(req, None, 5)
    html_string = response.read()
    response.close()
    log = log + 'Thingspeak Update ' + html_string

  except urllib2.HTTPError, e:
    log = log + 'Server could not fulfill the request. Error code: ' + e.code
  except urllib2.URLError, e:
    log = log + 'Failed to reach server. ' #Reason: ' + e.reason
  except:
    log = log + 'Unknown error'
  print log
  logging.info('Received:  %s',log)

#------   function to convert temperature scale from c to f   ------#
def calc_temp_scale(temp_c):	
  if temp_scale == "f" :
  # convert to f formula
	temp_f = float(temp_c) * 9.0 / 5.0 + 32.0
  logging.info('Converted %s degress c to %s degrees f',temp_c,temp_f)
  return temp_f


#------   function to toggle irled and return it's status   ------#		
# status is 0 for off and 1 for on
def irled(irled_ring_gpio_pin):
  GPIO.setup(irled_ring_gpio_pin, GPIO.OUT) # set irled_ring_gpio_pin channel as an output
   
  # get current status - is it on or off (high/low)?
  irled_status = GPIO.input(irled_ring_gpio_pin)
  logging.info('IRLED start status is: %s',irled_status)
  
  # need to validate whether this is a status change event (toggle) from on/off or off/on
  if light_reading >= ldr_threshold and irled_status == 0 or light_reading < ldr_threshold and irled_status == 1 :
  	status_change = 1 # the state has just changed
  	logging.info('State of the IRLED has just been changed in response to the light reading %s exceeding threshold %s',light_reading,ldr_threshold)
  else :
  	status_change = 0 # the state has not changeed
  	logging.info('State of the IRLED has not changed')
  	
  #if the status has changed, we need to toggle the leds
  if status_change == 1 :
  	run = os.system #convenience alias
	# need to stop the camera to prevent false motion recording when toggling the irleds
	logging.info('Stopping the RPi CAM web interface...')
	### IMPORTANT NOTE - Running the command below when we're just using timelapse causes the scheduling service to restart and re-enables
        ### motion detection.  WE DON'T WANT TO DO THIS for timelapse, so we need to comment out for now.
	### stop_result = run('/home/pi/RPi_Cam_Web_Interface/stop.sh')
	
  	if light_reading >= ldr_threshold :
  		# turn on leds and update status
  		logging.info('Setting the IRLED GPIO to HIGH (on)')
  		GPIO.output(irled_ring_gpio_pin, GPIO.HIGH)
		irled_status = 1	
  	else :
  		# turn off leds and update status
  		logging.info('Setting the IRLED GPIO to LOW (off)')
		GPIO.output(irled_ring_gpio_pin, GPIO.LOW)
		irled_status = 0
	# need to sleep for a bit so the image can stabilise after toggling the irleds and prevent false motion detection recordings
	time.sleep(5)
	# start the camera program.  without this, we have nothing (perhaps we should check the result!)
	logging.info('Slept for 5 seconds - now starting the RPi CAM web interface...')
	### IMPORTANT NOTE - Running the command below when we're just using timelapse causes the scheduling service to restart and re-enables
        ### motion detection.  WE DON'T WANT TO DO THIS for timelapse, so we need to comment out for now.
        ### start_result = run('/home/pi/RPi_Cam_Web_Interface/start.sh')
  logging.info('IRLED end status is: %s',irled_status)
  return irled_status
	

#------   function to open temperature sensor location and read data   ------#
def temp_raw(sensor_path):
  try :
        logging.info('Opening path:  %s',sensor_path)
	f = open(sensor_path, 'r')
	lines = f.readlines()
	f.close()
  except :
	#print "ERROR opening temperature sensor location!"
	logging.error('Error opening sensor path:  %s',sensor_path)
	lines = float(5000)
	# commentinmg out the line below, as it's unhelpful.  It terminates the script prematurely.
	# if it can continue, it should.
	# sys.exit()
	# os.system("sudo reboot") # ADDING THIS CAN CAUSE A REBOOT LOOP, AS REBOOTING DOESN'T SEEM TO RESET THE SENSORS, ONLY A POWER OFF/REMOVE POWER DOES
  return lines


#------   function to extract sensor temperatures   ------#
def read_temp_probe(device,attempt):
  lines = temp_raw(device)
  
  if lines == 5000 :#and attempt != 5: 
  	logging.error('Gave up after %s attempts.',attempt)
  	return lines


#  	if attempt != 5 :
#  		print attempt,device
#  		attempt += 1
#  		logging.error('Retry %s.  Returning "5000" as a temperature value due to an error!',attempt)
#  		read_temp_probe(device,attempt)
#  	elif attempt == 5 :
#  		print "end of retry"
#  		return lines

  
  while lines[0].strip()[-3:] != 'YES':
	time.sleep(0.2)
	lines = temp_raw()
  temp_output = lines[1].find('t=')
  if temp_output != -1:
	temp_string = lines[1].strip()[temp_output+2:]
	# convert to deg c first
	temp_c = float(temp_string) / 1000.0
	if temp_scale == "f" :
		temp_f = calc_temp_scale(temp_c)
		temp = round(temp_f,1)
	else :
		temp = round(temp_c,1)
       	logging.info('ATTEMPT %s, Temperature is %s for device:  %s',attempt,temp,device)
       	return float(temp)
  else :
       	# an error has occured, so return a silly value for now
       	temp = 5000
       	logging.error('ATTEMPT %s, Temperature is %s - error has occurred',attempt,temp)
       	return float(temp)


#------   function to get system uptime   ------#
def get_sys_uptime():
  raw = subprocess.check_output(["uptime"]).replace(',','')
  #days = int(raw.split()[2])
  s = subprocess.check_output(["uptime"])
  load_split = s.split('load average: ')
  load_five = float(load_split[1].split(',')[1])
  up = load_split[0]
  up_pos = up.rfind(',',0,len(up)-4)
  up = up[:up_pos].split('up ')[1]
  logging.info('System uptime is:  %s',up)
  #print "uptime",up," load ",load_five
  #print "s:",s
  #return (up,load_five)  
  return (up)


#------   function to get cpu temperature   ------#
def read_cpu_temp():
  # read in value and stip off whitespace for processing
  res = os.popen('vcgencmd measure_temp').readline().rstrip()
  logging.info('Running command and parsing output to get raw CPU TEMP:  %s',res)
  # value is already in degrees celcius
  #temp_c = (res.replace("temp=","").replace("'C\n",""))
  temp_c = (res.replace("temp=","").replace("'C",""))
  
  if temp_scale == "f" :
	temp_f = calc_temp_scale(temp_c)
	temp = temp_f
  else :
	temp = temp_c
  logging.info('Formatted CPU Temp is:  %s',temp)
  return temp


#------   function to get light reading   ------#
def ldr_time(ldr_gpio_pin,attempt):
  logging.info('ATTEMPT %s, Performing LDR reading....',attempt)
  count = 0
  # Output on the pin for
  GPIO.setup(ldr_gpio_pin, GPIO.OUT)
  GPIO.output(ldr_gpio_pin, GPIO.LOW)
  time.sleep(0.1)
  # Change the pin back to input
  GPIO.setup(ldr_gpio_pin, GPIO.IN)
  # Count until the pin goes high
  while (GPIO.input(ldr_gpio_pin) == GPIO.LOW):
  	count += 1
  logging.info('ATTEMPT %s, LDR reading is:  %s, threshold set at %s',attempt,count,ldr_threshold)
  return count
  #return 10
  

#------   function to get current time   ------#
def dt_now():
  now = time.strftime("%c")
  return (now)




#-/-/-/-/-   M A I N   -\-\-\-\-#
try:
	# get temperature probe readings
	# it's best to leave variables generic for now as the mappings could change if a new sensor was added, removed or changed
	# (as in, temp_sensor_internal_path is currently the internal sensor, but this could actually change if the hardware is changed
	# we send two parameters, the first is the sensor location and the second is the 'attempt' for debugging
	temp_internal = read_temp_probe(temp_sensor_internal_path,0) # internal temperature
	temp_external = read_temp_probe(temp_sensor_external_path,0) # external temperature
	temp_roof = read_temp_probe(temp_sensor_roof_path,0) # roof space (internal) temperature
	
	#logging.warning('internal %s, external %s, roof %s',temp_internal,temp_external,temp_roof)

	# if this is the first time the sensors have been probed, they give a value of 85 (no idead why)
	# this only happens if the pi has been booted from a 'clean/cold power on' (not a reboot)
	# need to probe them again to get an accurate value
	if temp_scale == "c" and temp_internal > 80 or temp_external > 80 or temp_roof > 80 :
		temp_internal = read_temp_probe(temp_sensor_internal_path,2) 
		temp_external = read_temp_probe(temp_sensor_external_path,2)
		temp_roof = read_temp_probe(temp_sensor_roof_path,2)
	elif temp_scale == "f" and temp_internal > 150 or temp_external > 150 or temp_roof > 150 :
		temp_internal = read_temp_probe(temp_sensor_internal_path,2) 
		temp_external = read_temp_probe(temp_sensor_external_path,2)
		temp_roof = read_temp_probe(temp_sensor_roof_path,2)
	
	#######if temp_scale == "c" and temp_internal > 80 :
	#######	temp_internal = read_temp_probe(temp_sensor_internal_path,2) 
	#######elif temp_scale == "c" and temp_external > 80 :
	#######	temp_external = read_temp_probe(temp_sensor_external_path,2)
	#######elif temp_scale == "c" and temp_roof > 80 :
	#######	temp_roof = read_temp_probe(temp_sensor_roof_path,2)
	#######elif temp_scale == "f" and temp_internal > 150 or temp_external > 150 or temp_roof > 150 :
	#######	temp_internal = read_temp_probe(temp_sensor_internal_path,2) 
	#######	temp_external = read_temp_probe(temp_sensor_external_path,2)
	#######	temp_roof = read_temp_probe(temp_sensor_roof_path,2)
	
	# get number of files created (effectively, we're checking how many files have been created in the media directory for the past 15 minutes
	video_captures = count_files()	

	# get CPU reading
	cpu_temp = read_cpu_temp()
	
	# get light reading
	light_reading = ldr_time(ldr_gpio_pin,1)
	# need to validate reading, as we don't really expect it to go over 50,000
	# however, if it does we'll try again, just in case it's spurious as it can happen from time to time (no idea why, but seems to happen after power up from cold boot)
	if light_reading > 50000 :
		light_reading = ldr_time(ldr_gpio_pin,2)
	
	# get irled status
	#this is just tremporary, as I don't want the irled on.  Need to uncomment the line below this 
	#to get it working as designed 
	#irled_status = 0
	irled_status = irled(irled_ring_gpio_pin)
		
	# upload data to THINGSPEAK website, unless we've specified the override not to as a command line argument
	#if upload_results == True:
	sendData(THINGSPEAKURL,THINGSPEAKKEY,'field1','field2','field3','field4','field5','field6','field7',temp_internal,temp_external,temp_roof,cpu_temp,light_reading,irled_status,video_captures)
		
	# get the system uptime, which can be useful for debugging
	uptime = get_sys_uptime()

	# check disk space 
	disk_space = disk_usage(disk_partition)

	
	# output to the screen
	print "\n",dt_now()
	#print "Light Reading;              ",light_reading,"(",ldr_threshold,")"#,dt_now()
	print "Light Reading (threshold);    " + str(light_reading) + " (" + str(ldr_threshold) + ")" #,")"#,dt_now()
	print "Temp Sensor 1, Internal;     ",("ERROR" if temp_internal == 5000 else temp_internal)#,dt_now()
	print "Temp Sensor 2, External;     ",("ERROR" if temp_external == 5000 else temp_external)#,dt_now()
	print "Temp Sensor 3, Electronics;  ",("ERROR" if temp_roof == 5000 else temp_roof)#,dt_now()
	print "CPU Temp;                    ",cpu_temp#,dt_now()
	print "Irled status;                ",("ON" if irled_status == 1 else "OFF" if irled_status == 0 else "ERROR"),"({})".format(irled_status)#,"\n"
	print "Uptime;                      ",uptime #,"\n"
	print "Video Captures;   	     ",video_captures #+ "files created in the last 15 minutes"
	print "Disk Usage;                  ",disk_space,"%"
	
	
	#timestr = time.strftime("%Y%m%d-%H%M%S")
	
	#imageFile = imageLoc+"/image-"+timestr+".jpg"
	#print imageFile
	#camera = PiCamera()
	#camera.start_preview()
	#time.sleep(5)
	
	#camera.capture(imageFile)
	#camera.stop_preview()
	
	# sleep required to free camera resources
	#time.sleep(1)
	
	# time for main to sleep
	#camera.close()	
	# time.sleep(900) # 15 minutes
	#time.sleep(300) # 5 minutes
	#time.sleep(60) 

except KeyboardInterrupt:
	GPIO.cleanup(11)
	logging.warning('KeyboardInterrupt:  Cleaning up GPIO 11')

finally:
	GPIO.cleanup(11)
	logging.info('FINALLY:  Cleaning up GPIO 11')

# end
logging.info('Completed.')
