import requests
from dotenv import load_dotenv
import os

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL")


def upload_file_data(
    file_path: str,
    session_id: str,
    data_subtype: str,
    description: str | None = None,
    location_geom: str | None = None,
    altitude_m: float | None = None,
    heading: float | None = None
) -> dict:
    """
    上传文件类型数据（图像、视频等）

    Args:
        file_path: 文件路径
        session_id: 采集会话ID
        data_subtype: 数据子类型 (rgb/nir/red_edge/thermal/multispectral/video)
        api_key: API密钥，默认从环境变量读取
        description: 文件描述（可选）
        location_geom: 位置几何信息，WKT格式（可选）
        altitude_m: 采集高度（米）（可选）
        heading: 朝向（度）（可选）

    Returns:
        上传结果
    """
    api_key = os.getenv("SECRET_KEY")

    # 检查文件是否存在
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")

    url = f"{API_BASE_URL}/api/raw-data/upload-file"
    headers = {
        "x-api-key": api_key,
        "accept": "application/json"
    }

    with open(file_path, "rb") as f:
        file_content = f.read()

    files = {"file": (os.path.basename(file_path), file_content)}
    data = {
        "session_id": session_id,
        "data_subtype": data_subtype
    }
    if description is not None:
        data["description"] = description
    if location_geom is not None:
        data["location_geom"] = location_geom
    if altitude_m is not None:
        data["altitude_m"] = altitude_m
    if heading is not None:
        data["heading"] = heading

    response = requests.post(url, headers=headers, files=files, data=data)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    api_key = os.getenv("SECRET_KEY")
    # 示例
    result = upload_file_data("abc.jpg", "422ebffa-77e7-4004-bc5c-e7d83da92e6d", "rgb", "a.jpg for test")
    # print("Usage: upload_file_data(file_path, session_id, data_subtype, api_key)")
    print(result)
