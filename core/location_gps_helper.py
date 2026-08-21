"""Standalone script - always run as a subprocess (`sys.executable location_gps_helper.py`),
never imported. CoreLocation delegate callbacks only arrive on a thread whose Cocoa run loop
is actively pumped; running this as its own process gives it an unshared main thread for that,
which a ThreadPoolExecutor worker inside the main app (pywebview owns that thread's loop) can't
provide. On success prints {"lat": ..., "lon": ...} as JSON and exits 0; otherwise exits 1 with
no stdout (permission denied, Location Services off, or timed out waiting for a fix)."""
from __future__ import annotations

import json
import sys
import threading
import time

import CoreLocation
from Foundation import NSObject
from PyObjCTools import AppHelper

_DENIED = 2

_result: dict | None = None


class _Delegate(NSObject):
    def locationManager_didUpdateLocations_(self, manager, locations):
        global _result
        coord = locations[-1].coordinate()
        _result = {"lat": coord.latitude, "lon": coord.longitude}
        AppHelper.stopEventLoop()

    def locationManager_didFailWithError_(self, manager, error):
        AppHelper.stopEventLoop()

    def locationManager_didChangeAuthorizationStatus_(self, manager, status):
        if status == _DENIED:
            AppHelper.stopEventLoop()


def main() -> None:
    delegate = _Delegate.alloc().init()
    manager = CoreLocation.CLLocationManager.alloc().init()
    manager.setDelegate_(delegate)
    manager.requestWhenInUseAuthorization()
    manager.startUpdatingLocation()

    def watchdog() -> None:
        time.sleep(8.0)
        AppHelper.stopEventLoop()

    threading.Thread(target=watchdog, daemon=True).start()
    AppHelper.runConsoleEventLoop()
    manager.stopUpdatingLocation()

    if _result is not None:
        print(json.dumps(_result))
        sys.exit(0)
    sys.exit(1)


if __name__ == "__main__":
    main()
