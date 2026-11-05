from .amount_anomaly import AmountAnomalyRule
from .card_testing import CardTestingRule
from .device_sharing import DeviceSharingRule
from .new_device import NewDeviceRule
from .velocity import VelocityRule


def default_rules():
    """Rules we implement and ship. Order is informational — budget trimming
    uses per-rule severity + priority, not list order."""
    return [
        VelocityRule(),
        NewDeviceRule(),
        AmountAnomalyRule(),
        CardTestingRule(),
        DeviceSharingRule(),
    ]


__all__ = [
    "AmountAnomalyRule",
    "CardTestingRule",
    "DeviceSharingRule",
    "NewDeviceRule",
    "VelocityRule",
    "default_rules",
]
