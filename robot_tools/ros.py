"""Small rclpy helpers: one short-lived node per CLI call."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from .common import Unavailable


def _import_rclpy():
    try:
        import rclpy  # noqa: F401
        from rosidl_runtime_py.utilities import get_message
    except ImportError as exc:
        raise Unavailable(
            f"ROS 2 Python (rclpy) is not available: {exc}. Run tools through ./robot "
            "so /opt/ros/humble/setup.bash is sourced."
        ) from exc
    return rclpy, get_message


def message_type(type_name: str):
    _, get_message = _import_rclpy()
    try:
        return get_message(type_name)
    except (ModuleNotFoundError, AttributeError, ValueError) as exc:
        raise Unavailable(
            f"ROS message type {type_name} is not installed; source the workspace that "
            "provides it (see ros.setup_files in robot.yaml)."
        ) from exc


def to_dict(msg: Any) -> dict[str, Any]:
    from rosidl_runtime_py.convert import message_to_ordereddict

    return dict(message_to_ordereddict(msg))


class Ros:
    def __init__(self, node):
        self.node = node

    def spin_for(self, seconds: float) -> None:
        import rclpy

        end = time.monotonic() + seconds
        while time.monotonic() < end:
            rclpy.spin_once(self.node, timeout_sec=min(0.05, max(0.0, end - time.monotonic())))

    def topics(self, discovery: float = 1.5) -> dict[str, list[str]]:
        self.spin_for(discovery)
        return dict(self.node.get_topic_names_and_types())

    def nodes(self) -> list[str]:
        return sorted(
            f"{ns.rstrip('/')}/{name}" for name, ns in self.node.get_node_names_and_namespaces()
        )

    def wait_for(self, topic: str, type_name: str, timeout: float = 3.0):
        """Return the next message on ``topic`` or None after ``timeout`` seconds."""
        from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
        import rclpy

        received: list[Any] = []
        qos = QoSProfile(
            depth=1, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.BEST_EFFORT
        )
        sub = self.node.create_subscription(
            message_type(type_name), topic, lambda m: received.append(m), qos
        )
        try:
            end = time.monotonic() + timeout
            while not received and time.monotonic() < end:
                rclpy.spin_once(self.node, timeout_sec=0.05)
        finally:
            self.node.destroy_subscription(sub)
        return received[0] if received else None

    def call(self, request_topic: str, msg: Any, response_topic: str, response_type: str,
             timeout: float, match=None, resend: float = 1.0):
        """Publish a request and return the first matching response (or None on timeout).

        Used for Unitree request/response services (unitree_api Request/Response topics).
        """
        from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
        import rclpy

        received: list[Any] = []
        qos = QoSProfile(
            depth=10, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.BEST_EFFORT
        )

        def on_response(m):
            if match is None or match(m):
                received.append(m)

        sub = self.node.create_subscription(message_type(response_type), response_topic,
                                            on_response, qos)
        pub = self.node.create_publisher(type(msg), request_topic, 10)
        try:
            end = time.monotonic() + timeout
            wait_match = time.monotonic() + min(1.0, timeout)
            while pub.get_subscription_count() == 0 and time.monotonic() < wait_match:
                self.spin_for(0.05)
            next_send = 0.0
            while not received and time.monotonic() < end:
                if time.monotonic() >= next_send:
                    pub.publish(msg)
                    next_send = time.monotonic() + resend
                rclpy.spin_once(self.node, timeout_sec=0.05)
        finally:
            self.node.destroy_publisher(pub)
            self.node.destroy_subscription(sub)
        return received[0] if received else None

    def publish(self, topic: str, msg: Any, repeat: int = 1, period: float = 0.05,
                wait_subscribers: float = 1.0, stop: Callable[[], bool] | None = None) -> int:
        """Publish ``msg`` and return the number of matched subscribers.

        ``stop`` is checked before every repetition; publishing ends early once it returns True.
        """
        pub = self.node.create_publisher(type(msg), topic, 10)
        try:
            end = time.monotonic() + wait_subscribers
            while pub.get_subscription_count() == 0 and time.monotonic() < end:
                self.spin_for(0.05)
            for _ in range(max(1, repeat)):
                if stop is not None and stop():
                    break
                pub.publish(msg)
                self.spin_for(period)
            return pub.get_subscription_count()
        finally:
            self.node.destroy_publisher(pub)


@contextmanager
def session(name: str = "robot_agent_tool", signal_handlers: bool = True) -> Iterator[Ros]:
    """A node for one CLI call.

    With ``signal_handlers=False`` rclpy installs no SIGINT/SIGTERM handlers: its handlers shut
    the context down, so nothing could be published afterwards (e.g. a final stop command in a
    ``finally`` block). The caller then handles the signals itself.
    """
    rclpy, _ = _import_rclpy()
    if signal_handlers:
        rclpy.init()
    else:
        from rclpy.signals import SignalHandlerOptions

        rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = rclpy.create_node(f"{name}_{int(time.time() * 1000) % 100000}")
    try:
        yield Ros(node)
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
