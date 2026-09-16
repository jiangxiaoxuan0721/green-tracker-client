"""数据枚举与单位映射测试。"""
from device.models.data_types import (
    DataType,
    DataSubType,
    DataUnit,
    SUBTYPE_UNIT_MAP,
)

# 数值型子类型（非文件类型）
NUMERIC_SUBTYPES = [
    DataSubType.TEMPERATURE,
    DataSubType.HUMIDITY,
    DataSubType.CO2,
    DataSubType.LIGHT,
    DataSubType.PRESSURE,
    DataSubType.MOISTURE,
    DataSubType.PH,
    DataSubType.EC,
    DataSubType.TEMPERATURE_SOIL,
]


def test_data_type_values():
    assert DataType.ENVIRONMENTAL.value == "environmental"
    assert DataType.SOIL.value == "soil"
    assert DataType.FILE.value == "file"


def test_data_subtype_grouping():
    assert DataSubType.RGB.value == "rgb"
    assert DataSubType.VIDEO.value == "video"
    assert DataSubType.TEMPERATURE.value == "temperature"
    assert DataSubType.TEMPERATURE_SOIL.value == "temperature_soil"


def test_data_unit_symbols():
    assert DataUnit.CELSIUS.value == "\u00b0C"
    assert DataUnit.PERCENT.value == "%"
    assert DataUnit.PPM.value == "ppm"
    assert DataUnit.US_CM.value == "\u03bcS/cm"


def test_subtype_unit_map_covers_all_numeric_subtypes():
    for subtype in NUMERIC_SUBTYPES:
        assert subtype in SUBTYPE_UNIT_MAP, f"缺少单位映射: {subtype}"


def test_subtype_unit_map_specific_mappings():
    assert SUBTYPE_UNIT_MAP[DataSubType.CO2] == DataUnit.PPM
    assert SUBTYPE_UNIT_MAP[DataSubType.PH] == DataUnit.PH
    assert SUBTYPE_UNIT_MAP[DataSubType.EC] == DataUnit.US_CM
    assert SUBTYPE_UNIT_MAP[DataSubType.HUMIDITY] == DataUnit.PERCENT


def test_file_subtypes_not_in_unit_map():
    for subtype in (DataSubType.RGB, DataSubType.NIR, DataSubType.VIDEO):
        assert subtype not in SUBTYPE_UNIT_MAP


def test_string_enum_coercion():
    # 因为是 (str, Enum)，可与字符串比较
    assert DataSubType.PH == "ph"
    assert DataType.SOIL == "soil"
