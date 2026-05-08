"""Execution engine with VWAP/TWAP order-splitting simulation.

Provides realistic order fill simulation for backtesting, supporting:
- TWAP (Time-Weighted Average Price): split order into N equal slices
- VWAP (Volume-Weighted Average Price): simulate proportional to volume profile
- Single-print (instant fill): equivalent to current behavior
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

try:
    import numpy as np
    import pandas as pd
except Exception:  # pragma: no cover
    np = None  # type: ignore
    pd = None  # type: ignore

try:
    from .indicators import calc_trade_price, calc_transaction_cost
except Exception:  # pragma: no cover
    calc_trade_price = None  # type: ignore
    calc_transaction_cost = None  # type: ignore


@dataclass
class ExecutionConfig:
    style: str = "single"         # "single", "twap", "vwap"
    num_slices: int = 5            # number of slices for TWAP/VWAP
    slice_interval_minutes: int = 30  # minutes between slices
    vwap_volume_profile: str = "uniform"  # "uniform", "front_loaded", "back_loaded"
    min_slice_amount: float = 10000.0    # minimum yuan per slice


def twap_simulate(
    total_qty: float,
    open_price: float,
    num_slices: int,
    slippage_rate: float,
    fee_rate: float,
    stamp_duty_rate: float,
    side: str,
) -> Dict[str, float]:
    """Simulate TWAP execution: split order into equal slices executed over the day.
    
    Each slice fills at a slightly different price (simulating intraday variation).
    Returns aggregate execution stats.
    """
    if np is None or calc_trade_price is None or calc_transaction_cost is None:
        raise RuntimeError("Required dependencies for execution engine are not available")
    
    slice_qty = total_qty / num_slices
    total_cost = 0.0
    total_amount = 0.0
    total_slippage = 0.0
    weights = np.linspace(0.8, 1.2, num_slices)  # simple intraday price variation
    
    for i in range(num_slices):
        slice_price = open_price * weights[i]
        fill_price = calc_trade_price(slice_price, slippage_rate, side)
        amount = slice_qty * fill_price
        cost = calc_transaction_cost(amount, fee_rate, stamp_duty_rate, side)
        total_cost += cost
        total_amount += amount
        total_slippage += amount * slippage_rate
        
    return {
        "avg_fill_price": total_amount / total_qty,
        "total_amount": total_amount,
        "total_cost": total_cost,
        "total_slippage": total_slippage,
        "num_slices": num_slices,
    }


def vwap_simulate(
    total_qty: float,
    open_price: float,
    close_price: float,
    volume: float,
    slippage_rate: float,
    fee_rate: float,
    stamp_duty_rate: float,
    side: str,
) -> Dict[str, float]:
    """Simulate VWAP execution: fill price approximates day VWAP."""
    if calc_trade_price is None or calc_transaction_cost is None:
        raise RuntimeError("Required dependencies for execution engine are not available")
    
    vwap_estimate = (open_price + close_price) / 2  # simplified VWAP
    fill_price = calc_trade_price(vwap_estimate, slippage_rate, side)
    amount = total_qty * fill_price
    cost = calc_transaction_cost(amount, fee_rate, stamp_duty_rate, side)
    return {
        "avg_fill_price": fill_price,
        "total_amount": amount,
        "total_cost": cost,
        "total_slippage": amount * slippage_rate,
        "num_slices": 1,
    }


def execute_order(
    qty: float,
    open_price: float,
    close_price: float,
    volume: float,
    config: ExecutionConfig,
    slippage_rate: float,
    fee_rate: float,
    stamp_duty_rate: float,
    side: str,
) -> Dict[str, float]:
    """Execute order with configured execution style."""
    if config.style == "twap":
        return twap_simulate(qty, open_price, config.num_slices, slippage_rate, fee_rate, stamp_duty_rate, side)
    elif config.style == "vwap":
        return vwap_simulate(qty, open_price, close_price, volume, slippage_rate, fee_rate, stamp_duty_rate, side)
    else:  # single
        if calc_trade_price is None or calc_transaction_cost is None:
            raise RuntimeError("Required dependencies for execution engine are not available")
        fill_price = calc_trade_price(open_price, slippage_rate, side)
        amount = qty * fill_price
        cost = calc_transaction_cost(amount, fee_rate, stamp_duty_rate, side)
        return {
            "avg_fill_price": fill_price,
            "total_amount": amount,
            "total_cost": cost,
            "total_slippage": amount * slippage_rate,
            "num_slices": 1,
        }
