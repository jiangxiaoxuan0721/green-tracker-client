"""数据记录模型（本地采集记录的数据结构）。"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
import uuid

from .data_types import DataType, DataSubType


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


__all__ = ["LocalDataRecord", "LocalFileRecord"]
