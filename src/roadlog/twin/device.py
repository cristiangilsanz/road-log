from __future__ import annotations

import json
import logging
import signal
import socket
import threading
import time

import paho.mqtt.client as mqtt

from roadlog import messages
from roadlog.messages import Assignment
from roadlog.settings import Broker, sim_speed
from roadlog.twin.tachograph import Tachograph

HELLO_RETRY = 5.0

log = logging.getLogger("roadlog.device")


def epoch_ms() -> float:
    return time.time() * 1000


class Device:
    def __init__(self, broker: Broker, hostname: str, speed: float) -> None:
        self.broker = broker
        self.hostname = hostname
        self.speed = speed
        self.stopped = threading.Event()
        self.assigned = threading.Event()
        self.lock = threading.Lock()
        self.tachograph: Tachograph | None = None
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"device-{hostname}")
        self.client.username_pw_set(broker.username, broker.password)
        self.client.will_set(
            messages.presence(hostname),
            json.dumps({"hostname": hostname, "status": "offline", "reason": "connection lost"}),
            qos=1,
        )
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        log.info("connected to %s:%s (%s)", self.broker.host, self.broker.port, reason_code)
        client.subscribe(messages.hello_reply(self.hostname), qos=1)
        if self.tachograph:
            client.subscribe(messages.config(self.tachograph.assignment.vehicle_id), qos=1)

    def on_message(self, client, userdata, message) -> None:
        try:
            payload = json.loads(message.payload)
        except json.JSONDecodeError:
            log.warning("ignored a malformed message on %s", message.topic)
            return
        if message.topic == messages.hello_reply(self.hostname):
            self.accept(payload)
        else:
            self.reconfigure(payload)

    def accept(self, payload: dict) -> None:
        if self.assigned.is_set():
            return
        if not payload.get("granted"):
            log.warning("access denied: %s", payload.get("reason", "no reason given"))
            return
        assignment = Assignment.parse(payload["assignment"])
        with self.lock:
            self.tachograph = Tachograph(assignment)
        self.client.subscribe(messages.config(assignment.vehicle_id), qos=1)
        log.info("now %s on %s as %s", assignment.vehicle_id, assignment.route, assignment.profile)
        self.assigned.set()

    def reconfigure(self, payload: dict) -> None:
        try:
            telemetry = messages.valid_interval(payload["telemetry_interval"])
            sampling = messages.valid_interval(payload["sampling_interval"])
        except (KeyError, TypeError, ValueError) as error:
            log.warning("rejected configuration %s: %s", payload, error)
            return
        with self.lock:
            if self.tachograph:
                self.tachograph.configure(telemetry, sampling)
        log.info("telemetry every %ss, sensors every %ss", telemetry, sampling)

    def publish(self, topic: str, payload: dict) -> None:
        self.client.publish(topic, json.dumps(payload), qos=1)

    def request_access(self) -> None:
        while not self.assigned.is_set() and not self.stopped.is_set():
            self.publish(messages.HELLO, {"hostname": self.hostname})
            log.info("asked for access as %s", self.hostname)
            self.assigned.wait(HELLO_RETRY)

    def simulate(self) -> None:
        tachograph = self.tachograph
        vehicle_id = tachograph.assignment.vehicle_id
        next_sample = next_telemetry = time.monotonic()
        while not self.stopped.is_set():
            now = time.monotonic()
            with self.lock:
                if now >= next_sample:
                    for event in tachograph.tick(tachograph.sampling_interval * self.speed):
                        self.publish(
                            messages.events(vehicle_id), tachograph.event(event, epoch_ms())
                        )
                    next_sample = max(next_sample + tachograph.sampling_interval, now)
                if now >= next_telemetry:
                    self.publish(messages.telemetry(vehicle_id), tachograph.telemetry(epoch_ms()))
                    next_telemetry = now + tachograph.telemetry_interval
                wake = min(next_sample, next_telemetry)
            self.stopped.wait(max(0.0, wake - time.monotonic()))

    def run(self) -> None:
        self.client.connect_async(self.broker.host, self.broker.port, keepalive=15)
        self.client.loop_start()
        try:
            self.request_access()
            if self.tachograph:
                self.simulate()
        finally:
            message = {"hostname": self.hostname, "status": "offline", "reason": "switched off"}
            info = self.client.publish(messages.presence(self.hostname), json.dumps(message), qos=1)
            try:
                info.wait_for_publish(3)
            except (RuntimeError, ValueError):
                log.warning("could not say goodbye, the broker will send the last will")
            self.client.disconnect()
            self.client.loop_stop()

    def stop(self, *_) -> None:
        self.stopped.set()


def main() -> None:
    device = Device(Broker.from_env("device"), socket.gethostname(), sim_speed())
    signal.signal(signal.SIGTERM, device.stop)
    signal.signal(signal.SIGINT, device.stop)
    device.run()
