"""枚举定义：数据类型、子类型、单位。"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum
import uuid


# ============================================================
# 枚举
# ============================================================

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
    CELSIUS = "\u00b0C"
    PERCENT = "%"
    PPM = "ppm"
    LUX = "lux"
    HPA = "hPa"
    KPA = "kPa"
    CM = "cm"
    M = "m"
    US_CM = "\u03bcS/cm"
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


__all__ = ["DataType", "DataSubType", "DataUnit", "SUBTYPE_UNIT_MAP"]
