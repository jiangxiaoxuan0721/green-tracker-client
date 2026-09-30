import os

import requests

# 导入 config 的同时就会加载配置目录里的 .env（见 config.py），
# 基地址必须在**调用时**解析：模块级常量会在 import 那一刻被冻结，
# 若那时 .env 还没加载，就会拿到默认的 localhost:8000。
from config import api_base_url


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

    url = f"{api_base_url()}/api/collection-sessions/active_sessions"
    headers = {"x-api-key": api_key}

    response = requests.post(url, headers=headers)
    response.raise_for_status()

    return response.json()

if __name__ == "__main__":
    print(get_active_sessions())
