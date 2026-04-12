import requests
from dotenv import load_dotenv
import os

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


def get_active_sessions(api_key: str | None = None) -> list[dict]:
    """
    根据API密钥获取用户的活跃采集任务，只返回ID、名称和描述

    Args:
        api_key: API密钥，默认从环境变量读取

    Returns:
        活跃采集任务列表，每个任务包含 id, mission_name, description
    """
    if api_key is None:
        api_key = os.getenv("SECRET_KEY")

    url = f"{API_BASE_URL}/api/collection-sessions/active_sessions"
    headers = {"x-api-key": api_key}

    response = requests.post(url, headers=headers)
    response.raise_for_status()

    return response.json()

if __name__ == "__main__":
    print(get_active_sessions())
