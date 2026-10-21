"""
Concept drift monitoring built on the River library.

The monitor receives ONE value per processed record:
    1 -> the model's prediction was wrong
    0 -> the prediction was correct
and reports one of three states:
    STABLE   "No significant drift detected."
    WARNING  "Possible change detected."
    DRIFT    "Concept Drift Detected — Model Adaptation Triggered."

Default detector: DDM (Drift Detection Method, Gama et al. 2004)
  p = error rate so far, s = sqrt(p(1-p)/n)
  It remembers the best (lowest) p_min + s_min.
  WARNING when p + s > p_min + 2 * s_min
  DRIFT   when p + s > p_min + 3 * s_min
It is the easiest detector to explain because it works directly on the error rate
and has a built-in warning zone.
"""
from __future__ import annotations

import math
from collections import deque

from src import config

STABLE, WARNING, DRIFT = "STABLE", "WARNING", "DRIFT"
STATUS_TEXT = {
    STABLE: "No significant drift detected.",
    WARNING: "Possible change detected.",
    DRIFT: "Concept Drift Detected — Model Adaptation Triggered.",
}

try:  # River >= 0.19
    from river.drift import ADWIN as _RiverADWIN
    from river.drift import PageHinkley as _RiverPH
    from river.drift.binary import DDM as _RiverDDM
    RIVER_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on installed version
    try:  # older River versions exposed DDM at top level
        from river.drift import ADWIN as _RiverADWIN
        from river.drift import DDM as _RiverDDM
        from river.drift import PageHinkley as _RiverPH
        RIVER_AVAILABLE = True
    except ImportError:
        RIVER_AVAILABLE = False


class _FallbackDDM:
    """Same algorithm as River's DDM, used only if River is not installed."""

    def __init__(self, warm_start=30, warning_threshold=2.0, drift_threshold=3.0):
        self.warm_start = warm_start
        self.warning_threshold = warning_threshold
        self.drift_threshold = drift_threshold
        self._reset()

    def _reset(self):
        self.n = 0
        self.p = 0.0
        self.p_min = float("inf")
        self.s_min = float("inf")
        self.ps_min = float("inf")
        self.drift_detected = False
        self.warning_detected = False

    def update(self, x):
        if self.drift_detected:
            self._reset()
        self.n += 1
        self.p += (float(x) - self.p) / self.n
        s = math.sqrt(self.p * (1 - self.p) / self.n)
        self.warning_detected = False
        if self.n > self.warm_start:
            if self.p + s <= self.ps_min:
                self.p_min, self.s_min, self.ps_min = self.p, s, self.p + s
            if self.p + s > self.p_min + self.drift_threshold * self.s_min:
                self.drift_detected = True
            elif self.p + s > self.p_min + self.warning_threshold * self.s_min:
                self.warning_detected = True
        return self


def _make_river_ddm():
    kwargs = dict(warning_threshold=config.DDM_WARNING_THRESHOLD,
                  drift_threshold=config.DDM_DRIFT_THRESHOLD)
    try:
        return _RiverDDM(warm_start=config.DDM_WARM_START, **kwargs)
    except TypeError:  # older signature
        return _RiverDDM(min_num_instances=config.DDM_WARM_START, **kwargs)


def _make_river_adwin():
    try:
        return _RiverADWIN(delta=0.002, clock=4, grace_period=config.DDM_WARM_START)
    except TypeError:
        return _RiverADWIN(delta=0.002)


def _make_river_ph():
    kwargs = dict(min_instances=config.DDM_WARM_START, delta=0.005, threshold=12.0, alpha=0.9999)
    try:
        return _RiverPH(mode="up", **kwargs)
    except TypeError:
        return _RiverPH(**kwargs)


DETECTOR_INFO = {
    "DDM": "Drift Detection Method — watches the error rate and its standard deviation; "
           "has a warning zone (2σ) and a drift zone (3σ).",
    "ADWIN": "ADaptive WINdowing — keeps a variable-size window of recent errors and "
             "signals drift when two sub-windows have significantly different means.",
    "PageHinkley": "Page-Hinkley test — accumulates how much the error exceeds its running "
                   "mean and signals drift when that sum passes a threshold.",
}


def available_detectors() -> list[str]:
    return ["DDM", "ADWIN", "PageHinkley"] if RIVER_AVAILABLE else ["DDM"]


class DriftMonitor:
    """Wraps a River detector and converts its output into STABLE / WARNING / DRIFT."""

    def __init__(self, name: str = config.DEFAULT_DETECTOR):
        if name not in available_detectors():
            name = "DDM"
        self.name = name
        self.backend = "River" if RIVER_AVAILABLE else "built-in (River not installed)"
        self.reset()

    # ------------------------------------------------------------------
    def reset(self) -> None:
        if self.name == "DDM":
            self._detector = _make_river_ddm() if RIVER_AVAILABLE else _FallbackDDM(
                config.DDM_WARM_START, config.DDM_WARNING_THRESHOLD, config.DDM_DRIFT_THRESHOLD)
        elif self.name == "ADWIN":
            self._detector = _make_river_adwin()
        else:
            self._detector = _make_river_ph()
        self._errors: deque[int] = deque(maxlen=400)
        self.n_seen = 0
        self.status = STABLE

    # ------------------------------------------------------------------
    def _heuristic_warning(self) -> bool:
        """ADWIN / Page-Hinkley have no warning zone, so we flag a *possible* change when
        the last 20 errors are clearly worse than the long-run error rate."""
        if len(self._errors) < 40:
            return False
        errs = list(self._errors)
        recent = sum(errs[-20:]) / 20
        base = sum(errs[:-20]) / (len(errs) - 20)
        return recent > base + 0.2

    def update(self, is_error: bool) -> str:
        x = 1 if is_error else 0
        self._errors.append(x)
        self.n_seen += 1
        self._detector.update(x)

        if getattr(self._detector, "drift_detected", False):
            self.status = DRIFT
        elif self.name == "DDM":
            self.status = WARNING if getattr(self._detector, "warning_detected", False) else STABLE
        else:
            self.status = WARNING if self._heuristic_warning() else STABLE
        return self.status

    @property
    def description(self) -> str:
        return DETECTOR_INFO.get(self.name, "")
