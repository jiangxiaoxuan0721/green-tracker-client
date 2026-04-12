"""
本地数据模型 - 支持离线存储和断网续传
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum
import uuid


class DataType(str, Enum):
    """数据类型枚举"""
    ENVIRONMENTAL = "environmental"
    SOIL = "soil"
    FILE = "file"


class DataSubType(str, Enum):
    """数据子类型枚举"""
    # FILE 类型
    RGB = "rgb"
    NIR = "nir"
    RED_EDGE = "red_edge"
    THERMAL = "thermal"
    MULTISPECTRAL = "multispectral"
    VIDEO = "video"

    # ENVIRONMENTAL 类型
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    CO2 = "co2"
    LIGHT = "light"
    PRESSURE = "pressure"

    # SOIL 类型
    MOISTURE = "moisture"
    PH = "ph"
    EC = "ec"
    TEMPERATURE_SOIL = "temperature_soil"


class DataUnit(str, Enum):
    """数据单位枚举"""
    CELSIUS = "°C"
    PERCENT = "%"
    PPM = "ppm"
    LUX = "lux"
    HPA = "hPa"
    KPA = "kPa"
    CM = "cm"
    M = "m"
    US_CM = "μS/cm"
    DS_M = "dS/m"
    PH = "pH"


SUBTYPE_UNIT_MAP = {
    DataSubType.TEMPERATURE: DataUnit.CELSIUS,
    DataSubType.HUMIDITY: DataUnit.PERCENT,
    DataSubType.CO2: DataUnit.PPM,
    DataSubType.LIGHT: DataUnit.LUX,
    DataSubType.PRESSURE: DataUnit.HPA,
    DataSubType.MOISTURE: DataUnit.PERCENT,
    DataSubType.PH: DataUnit.PH,
    DataSubType.EC: DataUnit.US_CM,
    DataSubType.TEMPERATURE_SOIL: DataUnit.CELSIUS,
}


class LocalDataRecord(BaseModel):
    """本地数字数据记录模型（含上传状态）"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="本地记录ID")
    session_id: str = Field(..., description="采集会话ID")
    data_type: DataType = Field(..., description="数据类型")
    data_subtype: DataSubType = Field(..., description="数据子类型")
    data_value: str = Field(..., description="数据值")
    capture_time: datetime = Field(default_factory=datetime.now, description="采集时间")
    location_geom: Optional[str] = Field(None, description="位置几何信息（WKT格式）")
    altitude_m: Optional[float] = Field(None, description="采集高度（米）")
    heading: Optional[float] = Field(None, description="朝向（度）")
    sensor_meta: Optional[Dict[str, Any]] = Field(None, description="传感器元数据")
    quality_score: Optional[float] = Field(None, description="质量评分（0-1）")
    is_valid: bool = Field(True, description="是否有效")
    validation_notes: Optional[str] = Field(None, description="验证备注")

    # 本地额外字段
    is_uploaded: bool = Field(False, description="是否已上传到服务器")
    upload_time: Optional[datetime] = Field(None, description="上传时间")
    server_data_id: Optional[str] = Field(None, description="服务器返回的数据ID")
    error_message: Optional[str] = Field(None, description="上传错误信息")

    model_config = {"from_attributes": True}


class LocalFileRecord(BaseModel):
    """本地文件记录模型（含上传状态）"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="本地记录ID")
    session_id: str = Field(..., description="采集会话ID")
    data_subtype: DataSubType = Field(..., description="数据子类型")
    local_path: str = Field(..., description="本地文件路径")
    file_size_bytes: int = Field(..., description="文件大小（字节）")
    capture_time: datetime = Field(default_factory=datetime.now, description="采集时间")
    location_geom: Optional[str] = Field(None, description="位置几何信息（WKT格式）")
    altitude_m: Optional[float] = Field(None, description="采集高度（米）")
    heading: Optional[float] = Field(None, description="朝向（度）")
    description: Optional[str] = Field(None, description="文件描述")

    # 本地额外字段
    is_uploaded: bool = Field(False, description="是否已上传到服务器")
    upload_time: Optional[datetime] = Field(None, description="上传时间")
    server_data_id: Optional[str] = Field(None, description="服务器返回的数据ID")
    server_object_key: Optional[str] = Field(None, description="MinIO对象路径")
    server_access_url: Optional[str] = Field(None, description="访问URL")
    error_message: Optional[str] = Field(None, description="上传错误信息")

    model_config = {"from_attributes": True}


class DataStore:
    """本地数据存储管理器（JSON文件存储）"""

    def __init__(self, store_file: str = "data_store.json"):
        import json
        import os
        self.store_file = store_file
        self._ensure_file()

    def _ensure_file(self):
        import json
        import os
        if not os.path.exists(self.store_file):
            os.makedirs(os.path.dirname(self.store_file) or ".", exist_ok=True)
            with open(self.store_file, "w") as f:
                json.dump({"numeric_data": [], "file_data": []}, f)

    def _load(self) -> dict:
        import json
        try:
            with open(self.store_file, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"numeric_data": [], "file_data": []}

    def _save(self, data: dict):
        import json
        with open(self.store_file, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def save_numeric_record(self, record: LocalDataRecord) -> str:
        data = self._load()
        record_dict = record.model_dump()
        data["numeric_data"].append(record_dict)
        self._save(data)
        return record.id

    def save_file_record(self, record: LocalFileRecord) -> str:
        data = self._load()
        record_dict = record.model_dump()
        data["file_data"].append(record_dict)
        self._save(data)
        return record.id

    def get_pending_uploads(self) -> tuple:
        """获取待上传的记录"""
        data = self._load()
        numeric_pending = [LocalDataRecord(**r) for r in data["numeric_data"] if not r.get("is_uploaded", False)]
        file_pending = [LocalFileRecord(**r) for r in data["file_data"] if not r.get("is_uploaded", False)]
        return numeric_pending, file_pending

    def mark_numeric_uploaded(self, local_id: str, server_data_id: str):
        """标记数字记录已上传"""
        data = self._load()
        for r in data["numeric_data"]:
            if r["id"] == local_id:
                r["is_uploaded"] = True
                r["upload_time"] = datetime.now().isoformat()
                r["server_data_id"] = server_data_id
                break
        self._save(data)

    def mark_file_uploaded(self, local_id: str, server_data_id: str, object_key: str, access_url: str):
        """标记文件记录已上传"""
        data = self._load()
        for r in data["file_data"]:
            if r["id"] == local_id:
                r["is_uploaded"] = True
                r["upload_time"] = datetime.now().isoformat()
                r["server_data_id"] = server_data_id
                r["server_object_key"] = object_key
                r["server_access_url"] = access_url
                break
        self._save(data)

    def get_all_records(self) -> dict:
        """获取所有记录"""
        data = self._load()
        return {
            "numeric_data": [LocalDataRecord(**r) for r in data["numeric_data"]],
            "file_data": [LocalFileRecord(**r) for r in data["file_data"]]
        }


__all__ = [
    "DataType",
    "DataSubType",
    "DataUnit",
    "LocalDataRecord",
    "LocalFileRecord",
    "DataStore",
]
