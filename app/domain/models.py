from pydantic import BaseModel
from typing import List, Dict

class RestartScheduleRequest(BaseModel):
    enabled: bool
    time: str

class PromoItem(BaseModel):
    id: int
    name: str
    cost: float
    minutes: int

class PointsConfigRequest(BaseModel):
    enabled: bool
    coin_map: Dict[str, float]
    promos: List[PromoItem]

class RenameRequest(BaseModel):
    mac: str
    name: str