import paho.mqtt.client as mqtt
from sshtunnel import SSHTunnelForwarder
import threading
import logging
import time
import datetime
import enum

SSH_TUNNEL_REMOTE_BIND_IP = '127.0.0.1'


class State(enum.Enum):
    INITIAL = enum.auto()
    CREATING_TUNNEL = enum.auto()
    WAIT = enum.auto()
    CONNECTING_MQTT = enum.auto()
    CONNECTED_MQTT = enum.auto()


class Mqtt:
    # ----------------------------------------------------------------
    # Class constructor
    # ----------------------------------------------------------------
    def __init__(self, host=None, ssh_user=None, ssh_pass=None, mqtt_user=None, mqtt_pass=None,
                 message_handler=None, log_enabled=True, mqtt_port=1883, init_subscribe=None):  # , main_lock=None):

        self.__log_enabled = log_enabled
        self.__message_handler = message_handler
        self.__host = host
        self.__ssh_user = ssh_user
        self.__ssh_pass = ssh_pass
        self.__mqtt_user = mqtt_user
        self.__mqtt_pass = mqtt_pass
        self.__mqtt_port = mqtt_port
        self.__stop_request = False
        self.__mqtt_connected_state = False
        self.__connection_manager_state = State.INITIAL
        self.__client = None
        self.__tunnel = None
        if init_subscribe is None:
            self.__subscriptions = []
        else:
            self.__subscriptions = init_subscribe
        self.__use_tunnel = False
        self.__lock = threading.Lock()
        # self.__log_lock = main_lock
        # starting the connection manager thread
        self.__thread_connection_manager = threading.Thread(target=self.__connection_manager)
        self.__thread_connection_manager.start()

    # ----------------------------------------------------------------
    # Class destructor
    # ----------------------------------------------------------------
    def __del__(self):
        timer = time.time()
        try:
            self.__stop_request = True
            # wait for close ot 2sec timout
            while self.__thread_connection_manager.is_alive() or time.time() - timer > 2:
                time.sleep(0.1)
        except:
            pass
        pass

    # ----------------------------------------------------------------
    # Connection Manager Thread
    # ----------------------------------------------------------------
    def __connection_manager(self):
        timer = time.time()
        # the manager loop
        while not self.__stop_request:
            # print(self.__connection_manager_state)
            time.sleep(0.01)
            # ----------------------------------------------
            # Initial
            # ----------------------------------------------
            if self.__connection_manager_state == State.INITIAL:
                # delete tunnel from previous connections if existing
                if self.__tunnel is not None:
                    try:
                        self.__tunnel.stop()
                        self.__tunnel.close()
                    finally:
                        del self.__tunnel
                # checking need of ssh tunnel
                if self.__ssh_pass is not "" and self.__ssh_pass is not None and \
                        self.__ssh_user is not "" and self.__ssh_user is not None:
                    self.__use_tunnel = True
                    self.__connection_manager_state = State.CREATING_TUNNEL
                else:
                    self.__use_tunnel = False
                    self.__connection_manager_state = State.CONNECTING_MQTT
            # ----------------------------------------------
            # Start creating tunnel
            # ----------------------------------------------
            elif self.__connection_manager_state == State.CREATING_TUNNEL:
                try:
                    self.__tunnel = SSHTunnelForwarder(ssh_address_or_host=self.__host,
                                                       # ssh_username="fool",  # self.__ssh_user,
                                                       ssh_username=self.__ssh_user,
                                                       ssh_password=self.__ssh_pass,
                                                       remote_bind_address=(SSH_TUNNEL_REMOTE_BIND_IP, self.__mqtt_port)
                                                       )
                    self.__tunnel.start()
                    if not self.__tunnel.is_active:
                        raise
                    self.__connection_manager_state = State.CONNECTING_MQTT
                    self.__log("SSH: Creating tunnel successful!")
                except:
                    # creating tunnel failed
                    self.__log("SSH: Creating tunnel failed!", "Error")
                    self.__connection_manager_state = State.WAIT
                    timer = time.time()

            # ----------------------------------------------
            # Creating tunnel failed
            # ----------------------------------------------
            elif self.__connection_manager_state == State.WAIT:
                # wait 1 seconds before retry
                if time.time() - timer > 5:
                    self.__connection_manager_state = State.INITIAL
            # ----------------------------------------------------------------
            # Creating tunnel success or even not needed -> connecting to mqtt
            # ----------------------------------------------------------------
            elif self.__connection_manager_state == State.CONNECTING_MQTT:
                try:
                    # delete client from previous connection if existing
                    if self.__client is not None:
                        del self.__client
                    self.__client = mqtt.Client()
                    self.__client.on_connect = self.on_connect
                    self.__client.on_disconnect = self.on_disconnect
                    self.__client.on_message = self.on_message
                    self.__client.username_pw_set(self.__mqtt_user, self.__mqtt_pass)
                    if self.__use_tunnel:
                        self.__client.connect(SSH_TUNNEL_REMOTE_BIND_IP, self.__tunnel.local_bind_port)
                    else:
                        self.__client.connect(self.__host, self.__mqtt_port)
                    self.__client.loop(0.1)
                    self.__connection_manager_state = State.CONNECTED_MQTT
                    self.__log("Client connected successful!")
                except:
                    # not connected to mqtt-broker
                    if self.__use_tunnel:
                        if not self.__tunnel.is_active:
                            # restart with new tunnel creating
                            self.__connection_manager_state = State.INITIAL
                            self.__log("Client connecting failed!", "Error")

            # ----------------------------------------------
            # Successfully connected to mqtt-broker
            # ----------------------------------------------
            elif self.__connection_manager_state == State.CONNECTED_MQTT:
                self.__client.loop(1)
                # check tunnel
                if self.__use_tunnel and not self.__tunnel.is_active:
                    # tunnel lost
                    # print("Tunnel lost")
                    try:
                        self.__client.disconnect()
                    except:
                        pass
                    self.__connection_manager_state = State.INITIAL
                else:
                    # tunnel ok or not used
                    if not self.__mqtt_connected_state:
                        # mqtt broker connection lost
                        # print("mqtt broker connection lost")
                        try:
                            self.__client.disconnect()
                        except:
                            pass
                        self.__connection_manager_state = State.CONNECTING_MQTT
        # stop request
        if self.__client is not None:
            try:
                self.__client.disconnect()
            finally:
                pass
        time.sleep(0.1)
        if self.__tunnel is not None:
            try:
                self.__tunnel.close()
            finally:
                del self.__tunnel
        # end of thread

    # ----------------------------------------------
    # mqtt - connection handler
    # ----------------------------------------------
    def on_connect(self, client, userdata, flags, rc):
        self.__log("Connected!", "Info")
        self.__mqtt_connected_state = True
        for subs in self.__subscriptions:
            if type(subs) is tuple:
                self.__client.subscribe(subs[0], qos=subs[1])
        # client.subscribe("#", qos=0)

    # ----------------------------------------------
    # mqtt - disconnection handler
    # ----------------------------------------------
    def on_disconnect(self, client, userdata, rc):
        self.__mqtt_connected_state = False
        if rc != 0:
            self.__log("Unexpected disconnection.", "Error")

    # ----------------------------------------------
    # mqtt - message handler
    # ----------------------------------------------
    def on_message(self, client, userdata, msg):
        # print(msg.topic, msg.payload)
        with self.__lock:
            if self.__message_handler is not None:
                self.__message_handler(msg)
        pass

    # ----------------------------------------------
    # logging
    # ----------------------------------------------
    def __log(self, log_text, level="Info"):
        if self.__log_enabled:
            # with self.__log_lock:
            print(str(datetime.datetime.now()) + " : MQTT: " + str(log_text))
            if "Info" in level:
                logging.info("MQTT: " + log_text)
            elif "Error" in level:
                logging.error("MQTT: " + log_text)

    # ----------------------------------------------
    # add subscription
    # ----------------------------------------------
    def add_subscription(self, subscription):
        if type(subscription) is not tuple:
            return
        subscription = list(subscription)
        if type(subscription[0]) is bytes:
            try:
                subscription[0] = subscription[0].decode("utf-8")
            except:
                return
        if type(subscription[1]) is not int:
            return
        subscription = tuple(subscription)
        if self.__subscriptions.count(subscription) == 0:
            self.__subscriptions.append(subscription)
            for subs in self.__subscriptions:
                try:
                    self.__client.subscribe(subs[0], qos=subs[1])
                except:
                    pass

    # ----------------------------------------------
    # Getter ans Setter for properties
    # ----------------------------------------------
    def __get_lock(self):
        return self.__lock

    def __get_client(self):
        return self.__client

    def __get_stop(self):
        return self.__stop_request

    def __set_stop(self, stop):
        self.__stop_request = stop

    def set_stop(self, stop):
        self.__stop_request = stop

    def __get_connected_state(self):
        return self.__mqtt_connected_state and \
               self.__connection_manager_state == State.CONNECTED_MQTT

    def __get_tunnel_state(self):
        res = False
        if self.__use_tunnel and self.__tunnel is not None:
            try:
                res = self.__tunnel.is_active
            except:
                res = False
        return res

    lock = property(__get_lock)
    stop_request = property(__get_stop, __set_stop)
    connected = property(__get_connected_state)
    client = property(__get_client)
    tunnel_active = property(__get_tunnel_state)
