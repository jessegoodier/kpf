import os
import sys

import kpf.display

sys.path.insert(0, os.path.abspath("src"))
from kpf.display import ServiceSelector
from kpf.kubernetes import ServiceInfo


class MockK8sClient:
    pass


# Patch _check_kubectl so it doesn't fail if kubectl is missing or erroring out


kpf.display.ServiceSelector._check_kubectl = lambda self: None

selector = ServiceSelector(MockK8sClient())

ports = [{"port": 80}, {"port": 443}] + [{"port": i} for i in range(8000, 8020)]

fake_services = [
    ServiceInfo("short-svc", "default", [{"port": 80, "protocol": "TCP"}], True),
    ServiceInfo(
        "my-very-long-service-name-with-lots-of-characters-and-even-more", "default", ports, True
    ),
]

print("Testing table output:")
selector._display_services_table(fake_services)
