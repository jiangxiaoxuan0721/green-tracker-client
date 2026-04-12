import requests
from dotenv import load_dotenv
import os

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL")

# 数据子类型到数据类型的映射
SUBTYPE_TO_DATATYPE = {
    "temperature": "environmental",
    "humidity": "environmental",
    "co2": "environmental",
    "light": "environmental",
    "pressure": "environmental",
    "moisture": "soil",
    "ph": "soil",
    "ec": "soil",
    "temperature_soil": "soil",
}


def upload_numeric_data(
    session_id: str,
    data_subtype: str,
    data_value: str,
    description: str | None = None,
    location_geom: str | None = None,
    altitude_m: float | None = None,
    heading: float | None = None
) -> dict:
    """
    上传数字类型数据（环境数据、土壤数据等）

    Args:
        session_id: 采集会话ID
        data_subtype: 数据子类型
        data_value: 数值字符串
        api_key: API密钥，默认从环境变量读取
        description: 描述（可选）
        location_geom: 位置几何信息，WKT格式（可选）
        altitude_m: 采集高度（米）（可选）
        heading: 朝向（度）（可选）

    Returns:
        上传结果
    """
    api_key = os.getenv("SECRET_KEY")

    url = f"{API_BASE_URL}/api/raw-data/upload-data"
    headers = {
        "x-api-key": api_key,
        "accept": "application/json"
    }

    # 根据 data_subtype 推断 data_type
    data_type = SUBTYPE_TO_DATATYPE.get(data_subtype)
    if not data_type:
        raise ValueError(f"不支持的 data_subtype: {data_subtype}")

    payload = {
        "session_id": session_id,
        "data_type": data_type,
        "data_subtype": data_subtype,
        "data_value": data_value
    }

    if description is not None:
        payload["description"] = description
    if location_geom is not None:
        payload["location_geom"] = location_geom
    if altitude_m is not None:
        payload["altitude_m"] = altitude_m
    if heading is not None:
        payload["heading"] = heading

    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    result = upload_numeric_data("422ebffa-77e7-4004-bc5c-e7d83da92e6d", "temperature", "20.27")
    print(result)
