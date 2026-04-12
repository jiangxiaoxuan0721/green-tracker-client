"""
模拟传感器采集程序
支持生成模拟数据并处理断网续传
"""
import random
import time
import os
import threading
from datetime import datetime
from typing import Optional, Dict, Any


from .data_models import (
    LocalDataRecord,
    LocalFileRecord,
    DataType,
    DataSubType,
    DataUnit,
    SUBTYPE_UNIT_MAP,
    DataStore,
)


class DataGenerator:
    """后台数据生成器 - 持续生成随机数据但不存储"""

    ENV_RANGES = {
        DataSubType.TEMPERATURE: (15.0, 35.0),
        DataSubType.HUMIDITY: (30.0, 90.0),
        DataSubType.CO2: (300.0, 800.0),
        DataSubType.LIGHT: (100.0, 50000.0),
        DataSubType.PRESSURE: (990.0, 1030.0),
    }

    SOIL_RANGES = {
        DataSubType.MOISTURE: (20.0, 80.0),
        DataSubType.PH: (5.0, 8.5),
        DataSubType.EC: (100.0, 2000.0),
        DataSubType.TEMPERATURE_SOIL: (10.0, 30.0),
    }

    def __init__(self, interval: float = 5.0):
        """
        初始化数据生成器

        Args:
            interval: 生成间隔（秒）
        """
        self.interval = interval
        self.running = False
        self.thread = None
        self.latest_data = None  # 只保存最新一条数据
        self._lock = threading.Lock()
        self.location_geom = "POINT(116.397428 39.90923)"
        self.altitude_m = 100.0
        self.heading = 0.0

    def set_location(self, geom: str, altitude: float = 100.0, heading: float = 0.0):
        """设置位置"""
        self.location_geom = geom
        self.altitude_m = altitude
        self.heading = heading

    def _generate_value(self, data_subtype: DataSubType) -> float:
        """生成随机数据值"""
        if data_subtype in self.ENV_RANGES:
            low, high = self.ENV_RANGES[data_subtype]
        elif data_subtype in self.SOIL_RANGES:
            low, high = self.SOIL_RANGES[data_subtype]
        else:
            return 0.0
        return round(random.uniform(low, high), 2)

    def _generate_one(self) -> Dict[str, Any]:
        """生成一条数据"""
        data_subtype = random.choice(
            list(self.ENV_RANGES.keys()) + list(self.SOIL_RANGES.keys())
        )
        return {
            "data_subtype": data_subtype,
            "data_value": str(self._generate_value(data_subtype)),
            "data_type": DataType.ENVIRONMENTAL if data_subtype in self.ENV_RANGES else DataType.SOIL,
            "unit": SUBTYPE_UNIT_MAP.get(data_subtype, DataUnit.PERCENT),
            "timestamp": datetime.now(),
            "location_geom": self.location_geom,
            "altitude_m": self.altitude_m,
            "heading": self.heading,
        }

    def _run(self):
        """后台运行 - 仅更新最新数据"""
        while self.running:
            data = self._generate_one()
            with self._lock:
                self.latest_data = data
            time.sleep(self.interval)

    def generate(self) -> Dict[str, Any]:
        """立即生成一条新数据（用于采集时调用）"""
        return self._generate_one()

    def start(self):
        """启动后台生成"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def stop(self):
        """停止生成"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)

    def get_latest(self) -> Optional[Dict[str, Any]]:
        """获取最新一条数据"""
        with self._lock:
            return self.latest_data


class SensorSimulator:
    """模拟传感器采集器"""

    # 环境数据正常范围
    ENV_RANGES = {
        DataSubType.TEMPERATURE: (15.0, 35.0),
        DataSubType.HUMIDITY: (30.0, 90.0),
        DataSubType.CO2: (300.0, 800.0),
        DataSubType.LIGHT: (100.0, 50000.0),
        DataSubType.PRESSURE: (990.0, 1030.0),
    }

    # 土壤数据正常范围
    SOIL_RANGES = {
        DataSubType.MOISTURE: (20.0, 80.0),
        DataSubType.PH: (5.0, 8.5),
        DataSubType.EC: (100.0, 2000.0),
        DataSubType.TEMPERATURE_SOIL: (10.0, 30.0),
    }

    def __init__(
        self,
        session_id: str,
        store_file: str = "sensor_data.json",
        auto_upload: bool = True,
    ):
        """
        初始化模拟传感器

        Args:
            session_id: 采集会话ID
            store_file: 本地存储文件路径
            auto_upload: 是否自动上传（联网时）
        """
        self.session_id = session_id
        self.store = DataStore(store_file)
        self.auto_upload = auto_upload
        self.location_geom = "POINT(116.397428 39.90923)"  # 默认位置
        self.altitude_m = 100.0
        self.heading = 0.0

    def set_location(self, geom: str, altitude: float = 100.0, heading: float = 0.0):
        """设置采集位置"""
        self.location_geom = geom
        self.altitude_m = altitude
        self.heading = heading

    def generate_value(self, data_subtype: DataSubType) -> float:
        """生成模拟数据值"""
        if data_subtype in self.ENV_RANGES:
            low, high = self.ENV_RANGES[data_subtype]
        elif data_subtype in self.SOIL_RANGES:
            low, high = self.SOIL_RANGES[data_subtype]
        else:
            raise ValueError(f"未知的数据子类型: {data_subtype}")

        # 添加随机波动
        value = random.uniform(low, high)
        # 偶尔添加异常值（用于测试）
        if random.random() < 0.05:
            value = value * random.uniform(1.2, 1.5)
        return round(value, 2)

    def collect_numeric_data(
        self,
        data_subtype: DataSubType,
        upload: bool = True,
    ) -> LocalDataRecord:
        """
        采集一条数字数据

        Args:
            data_subtype: 数据子类型
            upload: 是否立即上传

        Returns:
            本地数据记录
        """
        data_value = str(self.generate_value(data_subtype))
        data_type = self._get_data_type(data_subtype)

        record = LocalDataRecord(
            session_id=self.session_id,
            data_type=data_type,
            data_subtype=data_subtype,
            data_value=data_value,
            capture_time=datetime.now(),
            location_geom=self.location_geom,
            altitude_m=self.altitude_m,
            heading=self.heading,
            is_valid=True,
            quality_score=random.uniform(0.7, 1.0),
        ) # type: ignore

        # 保存到本地
        self.store.save_numeric_record(record)

        # 尝试上传
        if upload and self.auto_upload:
            self._upload_numeric_record(record)

        return record

    def _get_data_type(self, data_subtype: DataSubType) -> DataType:
        """根据数据子类型获取数据类型"""
        if data_subtype in [
            DataSubType.RGB, DataSubType.NIR, DataSubType.RED_EDGE,
            DataSubType.THERMAL, DataSubType.MULTISPECTRAL, DataSubType.VIDEO
        ]:
            return DataType.FILE
        elif data_subtype in self.ENV_RANGES:
            return DataType.ENVIRONMENTAL
        else:
            return DataType.SOIL

    def _upload_numeric_record(self, record: LocalDataRecord):
        """上传数字记录到服务器"""
        try:
            from api.upload_numeric_data import upload_numeric_data
            result = upload_numeric_data(
                session_id=record.session_id,
                data_subtype=record.data_subtype.value,
                data_value=record.data_value,
                location_geom=record.location_geom,
                altitude_m=record.altitude_m,
                heading=record.heading,
            )
            self.store.mark_numeric_uploaded(record.id, result.get("data_id", ""))
            print(f"[{record.data_subtype.value}] 上传成功: {record.data_value}")
        except Exception as e:
            record.error_message = str(e)
            print(f"[{record.data_subtype.value}] 上传失败: {e}")

    def _upload_file_record(self, record: LocalFileRecord):
        """上传文件记录到服务器"""
        try:
            from api.upload_file_data import upload_file_data
            result = upload_file_data(
                file_path=record.local_path,
                session_id=record.session_id,
                data_subtype=record.data_subtype.value,
                location_geom=record.location_geom,
                altitude_m=record.altitude_m,
                heading=record.heading,
            )
            self.store.mark_file_uploaded(
                record.id,
                result.get("data_id", ""),
                result.get("object_key", ""),
                result.get("access_url", ""),
            )
            print(f"[{record.data_subtype.value}] 文件上传成功: {record.local_path}")
        except Exception as e:
            print(f"[{record.data_subtype.value}] 文件上传失败: {e}")

    def collect_all_environmental(self, upload: bool = True) -> list:
        """采集所有环境数据"""
        records = []
        for subtype in self.ENV_RANGES.keys():
            record = self.collect_numeric_data(subtype, upload=upload)
            records.append(record)
        return records

    def collect_all_soil(self, upload: bool = True) -> list:
        """采集所有土壤数据"""
        records = []
        for subtype in self.SOIL_RANGES.keys():
            record = self.collect_numeric_data(subtype, upload=upload)
            records.append(record)
        return records

    def sync_pending(self) -> dict:
        """
        同步待上传数据（断网后重试）

        Returns:
            上传结果统计
        """
        numeric_pending, file_pending = self.store.get_pending_uploads()
        success_count = 0
        fail_count = 0

        for record in numeric_pending:
            try:
                from api.upload_numeric_data import upload_numeric_data
                result = upload_numeric_data(
                    session_id=record.session_id,
                    data_subtype=record.data_subtype.value,
                    data_value=record.data_value,
                    location_geom=record.location_geom,
                    altitude_m=record.altitude_m,
                    heading=record.heading,
                )
                self.store.mark_numeric_uploaded(record.id, result.get("data_id", ""))
                success_count += 1
                print(f"[同步] 数字数据上传成功: {record.data_subtype.value}")
            except Exception as e:
                fail_count += 1
                print(f"[同步] 数字数据上传失败: {e}")

        for record in file_pending:
            try:
                from api.upload_file_data import upload_file_data
                result = upload_file_data(
                    file_path=record.local_path,
                    session_id=record.session_id,
                    data_subtype=record.data_subtype.value,
                    location_geom=record.location_geom,
                    altitude_m=record.altitude_m,
                    heading=record.heading,
                )
                self.store.mark_file_uploaded(
                    record.id,
                    result.get("data_id", ""),
                    result.get("object_key", ""),
                    result.get("access_url", ""),
                )
                success_count += 1
                print(f"[同步] 文件上传成功: {record.local_path}")
            except Exception as e:
                fail_count += 1
                print(f"[同步] 文件上传失败: {e}")

        return {
            "success": success_count,
            "failed": fail_count,
            "total": success_count + fail_count,
        }

    def get_status(self) -> dict:
        """获取数据状态"""
        all_records = self.store.get_all_records()
        numeric = all_records["numeric_data"]
        files = all_records["file_data"]

        return {
            "session_id": self.session_id,
            "numeric": {
                "total": len(numeric),
                "uploaded": sum(1 for r in numeric if r.is_uploaded),
                "pending": sum(1 for r in numeric if not r.is_uploaded),
            },
            "files": {
                "total": len(files),
                "uploaded": sum(1 for r in files if r.is_uploaded),
                "pending": sum(1 for r in files if not r.is_uploaded),
            },
        }

    def simulate_continuous(
        self,
        duration: int = 60,
        interval: float = 5.0,
        data_types: Optional[list] = None,
    ):
        """
        模拟连续采集

        Args:
            duration: 持续时间（秒）
            interval: 采集间隔（秒）
            data_types: 要采集的数据类型列表 ["environmental", "soil"]
        """
        if data_types is None:
            data_types = ["environmental", "soil"]

        start_time = time.time()
        count = 0

        while time.time() - start_time < duration:
            if "environmental" in data_types:
                self.collect_all_environmental(upload=self.auto_upload)
            if "soil" in data_types:
                self.collect_all_soil(upload=self.auto_upload)

            count += 1
            print(f"--- 第 {count} 轮采集完成 ---")
            time.sleep(interval)

        print(f"采集完成，共 {count} 轮")


# 便捷函数
def quick_collect(session_id: str, data_type: str = "all", auto_upload: bool = True):
    """
    快速采集数据

    Args:
        session_id: 采集会话ID
        data_type: 数据类型 ("all", "environmental", "soil")
        auto_upload: 是否自动上传
    """
    simulator = SensorSimulator(session_id, auto_upload=auto_upload)

    if data_type == "all":
        simulator.collect_all_environmental()
        simulator.collect_all_soil()
    elif data_type == "environmental":
        simulator.collect_all_environmental()
    elif data_type == "soil":
        simulator.collect_all_soil()

    status = simulator.get_status()
    print(f"\n数据采集状态: {status}")
    return status


if __name__ == "__main__":
    # 测试示例
    session_id = "550e8400-e29b-41d4-a716-446655440000"

    # 创建模拟器
    sim = SensorSimulator(session_id, auto_upload=False)

    # 采集环境数据
    print("=== 采集环境数据 ===")
    sim.collect_all_environmental(upload=False)

    # 采集土壤数据
    print("\n=== 采集土壤数据 ===")
    sim.collect_all_soil(upload=False)

    # 查看状态
    print("\n=== 当前状态 ===")
    status = sim.get_status()
    print(f"数字数据: 总数={status['numeric']['total']}, 已上传={status['numeric']['uploaded']}, 待上传={status['numeric']['pending']}")

    # 模拟断网后同步（需要联网）
    # print("\n=== 尝试同步 ===")
    # result = sim.sync_pending()
    # print(f"同步结果: {result}")
