"""Run the calling thread at macOS QoS class utility, so recognition yields to the rest of the Mac."""

import ctypes

QOS_CLASS_UTILITY = 0x11


def set_background_priority() -> bool:
    """Lower the current thread to QOS_CLASS_UTILITY. False (never an exception) if that isn't possible."""
    try:
        libsystem = ctypes.CDLL(None)
        return libsystem.pthread_set_qos_class_self_np(QOS_CLASS_UTILITY, 0) == 0
    except (OSError, AttributeError):
        return False
