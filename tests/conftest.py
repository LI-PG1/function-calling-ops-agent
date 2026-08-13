# -*- coding: utf-8 -*-
"""pytest 公共夹具：路径注入 + mock 服务状态隔离。

mock 服务状态存在 SQLite（data/vehicle.db、data/orders.db），每个用例前后按预设重置，
保证规则判定不依赖上一个用例的残留状态。
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def vehicle_parked():
    from mock_services import vehicle

    vehicle.reset("parked_home")
    yield vehicle
    vehicle.reset("parked_home")


@pytest.fixture()
def vehicle_driving():
    from mock_services import vehicle

    vehicle.reset("highway_driving")
    yield vehicle
    vehicle.reset("parked_home")


@pytest.fixture()
def vehicle_child_alone():
    from mock_services import vehicle

    vehicle.reset("child_alone")
    yield vehicle
    vehicle.reset("parked_home")


@pytest.fixture()
def orders_none():
    from mock_services import orders

    orders.reset("none")
    yield orders
    orders.reset("none")
