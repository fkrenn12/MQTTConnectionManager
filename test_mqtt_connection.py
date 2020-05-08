import time
import mqtt_connection as mqtt
import datetime
import logging
import os
import sys
import threading
import logging
import platform


# -------------------------
log_enabled = True
mqtt_to_send = []
mqttclient = None

# -------------------------

time_of_start = time.time()
main_lock = threading.Lock()
stop = False

# -----------------------------------------------------------------
#  E X I T
# -----------------------------------------------------------------
def app_exit():
    global mqttclient
    # stopping mqtt client
    try:
        mqttclient.stop_request = True
        time.sleep(1)
        del mqttclient
    except:
        pass
    x = input("Press 'Enter' or close this console window to terminate!")
    sys.exit()

# -------------------------------------------------------------------------------
#                            S t a r t   -   M Q T T
# -------------------------------------------------------------------------------
try:
    '''
    # test with tunnel
    mqttclient = mqtt.Mqtt(host=config.ssh_tunnel["IP"],
                           ssh_user=config.ssh_tunnel["User"],
                           ssh_pass=config.ssh_tunnel["Password"],
                           mqtt_user=config.mqtt_broker["User"],
                           mqtt_pass=config.mqtt_broker["Password"])
    '''
    # test without tunnel
    mqttclient = mqtt.Mqtt(host="94.16.117.246",
                           # ssh_user=config.ssh_tunnel["User"],
                           # ssh_pass=config.ssh_tunnel["Password"],
                           mqtt_user="labor",
                           mqtt_pass="labor")

except:
    print("SSH tunnel could not be established or Mqtt-Broker not reachable.")
    app_exit()

# -------------------------------------------------------------------------------
#                           M A I N - L O O P
# -------------------------------------------------------------------------------
while True:
    if stop:
        raise Exception
    try:
        time.sleep(0.1)
        if not mqttclient.connected:
            print("MQTT - not connected")
    # except KeyboardInterrupt:  # Ctrl+C # FIXME: "raise error(EBADF, 'Bad file descriptor')"
    except Exception:
        print("Keyboard request to stop the script")
        app_exit()