"""FastAPI 包装（可选）：把 mock 服务暴露为 HTTP 接口（v0.2：车控 / 订单 / 客服）。

启动：uvicorn mock_services.serve:app --port 8600
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from . import cs, orders, vehicle

app = FastAPI(title="ops-agent mock services (v0.2)")


# ---------- 车控 ----------
@app.get("/vehicle/status")
def get_vehicle_status(fail_mode: str = "off"):
    return vehicle.get_status(fail_mode)


class ClimateReq(BaseModel):
    action: str
    zone: str = "all"
    temp: int | None = None
    fail_mode: str = "off"


class SeatReq(BaseModel):
    action: str
    zone: str = "driver"
    fail_mode: str = "off"


class DoorReq(BaseModel):
    action: str
    door: str = "fl"
    fail_mode: str = "off"


class SafetyReq(BaseModel):
    action: str
    value: int | None = None
    fail_mode: str = "off"


class NavReq(BaseModel):
    destination: str
    fail_mode: str = "off"


@app.post("/vehicle/climate")
def post_climate(req: ClimateReq):
    return vehicle.control_climate(req.action, req.zone, req.temp, req.fail_mode)


@app.post("/vehicle/seat")
def post_seat(req: SeatReq):
    return vehicle.control_seat(req.action, req.zone, req.fail_mode)


@app.post("/vehicle/door")
def post_door(req: DoorReq):
    return vehicle.control_door(req.action, req.door, req.fail_mode)


@app.post("/vehicle/safety")
def post_safety(req: SafetyReq):
    return vehicle.control_safety(req.action, req.value, req.fail_mode)


@app.post("/vehicle/navigate")
def post_nav(req: NavReq):
    return vehicle.navigate(req.destination, req.fail_mode)


# ---------- 订单 ----------
@app.get("/orders/active")
def get_active_order():
    return orders.active_order() or {"active": False}


@app.get("/orders/query")
def query_order(order_id: str = "", fail_mode: str = "off"):
    return orders.query_order(order_id, fail_mode)


class PickupReq(BaseModel):
    order_id: str
    point: str
    fail_mode: str = "off"


class DestReq(BaseModel):
    order_id: str
    destination: str
    fail_mode: str = "off"


@app.post("/orders/pickup")
def post_pickup(req: PickupReq):
    return orders.modify_pickup_point(req.order_id, req.point, req.fail_mode)


@app.post("/orders/destination")
def post_dest(req: DestReq):
    return orders.change_destination(req.order_id, req.destination, req.fail_mode)


# ---------- 客服 ----------
class CSReq(BaseModel):
    reason: str
    priority: str = "normal"
    fail_mode: str = "off"


@app.post("/cs/tickets")
def post_cs(req: CSReq):
    return cs.create_ticket(req.reason, req.priority, req.fail_mode)


@app.get("/cs/tickets")
def list_cs():
    return cs.list_tickets()
