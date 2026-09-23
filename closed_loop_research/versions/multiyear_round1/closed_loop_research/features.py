"""Causal price/volume feature registry; no fitted or future-dependent transforms."""
import numpy as np
import pandas as pd

RAW_FIELDS = ("open", "close", "high", "low", "volume", "amount")
FEATURE_LOOKBACKS = {name: 0 for name in RAW_FIELDS}
FEATURE_LOOKBACKS.update({f"return_{w}": w for w in (1, 5, 10, 20, 60)})
FEATURE_LOOKBACKS.update({f"volatility_{w}": w for w in (5, 20, 60)})
FEATURE_LOOKBACKS.update({f"{name}_{w}": w-1 for name in ("volume_ratio", "ma_gap") for w in (5, 20, 60)})
FEATURE_LOOKBACKS.update(intraday_return=0, overnight_gap=1, range_relative=1, close_location=0)


def engineer_features(frame):
    required = {"date", "code", *RAW_FIELDS}
    if not required.issubset(frame):
        raise ValueError(f"missing raw features: {sorted(required-set(frame))}")
    data = frame.copy().sort_values(["date", "code"]).reset_index(drop=True)
    if data.duplicated(["date", "code"]).any():
        raise ValueError("duplicate feature date/code")
    groups = data.groupby("code", sort=False)
    def divide(a, b):
        return a / b.where(np.abs(b) > 1e-12)
    for window in (1, 5, 10, 20, 60):
        data[f"return_{window}"] = divide(data.close, groups.close.shift(window))-1
    for window in (5, 20, 60):
        data[f"volatility_{window}"] = data.groupby("code", sort=False).return_1.transform(
            lambda v: v.rolling(window, min_periods=window).std(ddof=0))
        volume_mean = groups.volume.transform(lambda v: v.rolling(window, min_periods=window).mean())
        close_mean = groups.close.transform(lambda v: v.rolling(window, min_periods=window).mean())
        data[f"volume_ratio_{window}"] = divide(data.volume, volume_mean)-1
        data[f"ma_gap_{window}"] = divide(data.close, close_mean)-1
    previous_close = groups.close.shift(1)
    data["intraday_return"] = divide(data.close, data.open)-1
    data["overnight_gap"] = divide(data.open, previous_close)-1
    data["range_relative"] = divide(data.high-data.low, previous_close)
    data["close_location"] = divide(2*data.close-data.high-data.low, data.high-data.low)
    data[list(FEATURE_LOOKBACKS)] = data[list(FEATURE_LOOKBACKS)].replace([np.inf, -np.inf], np.nan)
    return data


def feature_formula(name):
    if name in RAW_FIELDS:
        return f"source.{name}(t)"
    if name.startswith("return_"):
        return f"close(t)/close(t-{name[7:]})-1"
    if name.startswith("volatility_"):
        return f"rolling_std(return_1,{name[11:]},ddof=0)"
    if name.startswith("volume_ratio_"):
        return f"volume(t)/rolling_mean(volume,{name[13:]})-1"
    if name.startswith("ma_gap_"):
        return f"close(t)/rolling_mean(close,{name[7:]})-1"
    return {"intraday_return": "close(t)/open(t)-1", "overnight_gap": "open(t)/close(t-1)-1",
            "range_relative": "(high(t)-low(t))/close(t-1)",
            "close_location": "(2*close(t)-high(t)-low(t))/(high(t)-low(t))"}[name]
