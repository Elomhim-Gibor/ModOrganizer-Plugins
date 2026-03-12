import typing
import json
import logging
import os
import re
import shutil
import subprocess
import winreg
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger: logging.Logger = logging.getLogger("PageFileManager")


def get_base_path() -> str:
    """
    Returns the base path of the script.
    """
    return os.path.dirname(os.path.abspath(__file__))


def create_logger() -> None:
    """
    Creates a logger with a file handler and sets it to the DEBUG level.
    Removes all existing handlers from the logger.
    """
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    script_dir: str = get_base_path()
    logs_dir: str = os.path.abspath(os.path.join(script_dir, "..", "..", "logs"))
    Path(logs_dir).mkdir(parents=True, exist_ok=True)
    log_path: str = os.path.abspath(os.path.join(logs_dir, "PageFileManager.log"))
    with open(log_path, "w") as _:
        pass

    # Create a file handler that logs messages to "logs\PageFileManager.log"
    file_handler = logging.FileHandler(log_path, encoding="utf-8", mode="w")

    # Set the format of the log messages
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s")
    file_handler.setFormatter(formatter)

    # Add the file handler to the logger
    logger.addHandler(file_handler)

    # Set the logger to the DEBUG level
    logger.setLevel(logging.DEBUG)


def get_free_space_mb(drive_letter: typing.Optional[str] = None) -> float:
    """
    Returns the free disk space in megabytes available on the drive.

    Args:
        drive_letter (str | None): The drive letter of the drive to query. If None, the drive letter of the drive
            from which this script is run will be used.

    Returns:
        float: The free disk space in megabytes.
    """
    # Get the drive letter of the drive from which the script is run
    if drive_letter is None or not os.path.exists(drive_letter):
        drive_letter = os.path.splitdrive(os.path.abspath(__file__))[0]

    # Get the total, used, and free disk space using shutil.disk_usage
    # This function returns a named tuple with the attributes total, used, and free
    disk_usage: shutil._ntuple_diskusage = shutil.disk_usage(drive_letter)

    # Convert the free disk space from bytes to megabytes
    free_mb: float = disk_usage.free / (1024**2)

    return free_mb


def check_free_space(required_mb: int) -> typing.Tuple[bool, float]:
    """
    Checks if there is enough free space to allocate the pagefile.

    Args:
        required_mb (int): The required free disk space in megabytes.

    Returns:
        tuple[bool, float]: A tuple with a boolean indicating if there is enough free space available,
            and the available free space in megabytes.
    """
    free_mb: float = get_free_space_mb()
    if free_mb < required_mb:
        # If there is not enough free space return False
        return False, free_mb
    else:
        return True, free_mb


def get_pagefiles_size() -> List[Tuple[str, int, int]]:
    """
    Returns the pagefile sizes for all drives.

    This function reads the PagingFiles registry value and returns a list of tuples
    containing the drive letter, initial size, and maximum size of each pagefile.

    Returns:
        List[Tuple[str, int, int]]: A list of tuples with the drive letter, initial size, and maximum size in MB.
                                    If no pagefiles are found, the list is empty.
    """
    pagefile_sizes: List[Tuple[str, int, int]] = []

    try:
        # Open the registry key containing the PagingFiles value
        reg_key: winreg.HKEYType = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management")

        # Query the PagingFiles value from the registry
        paging_files, reg_type = winreg.QueryValueEx(reg_key, "PagingFiles")
        winreg.CloseKey(reg_key)

        # Iterate over the pagefiles
        for pagefile in paging_files:
            parts = pagefile.split(" ")
            path = parts[0].lower()
            drive_letter = os.path.splitdrive(path)[0]
            if len(parts) >= 3:
                # Extract the initial and maximum pagefile size from the parts
                initial_size = int(parts[1])
                max_size = int(parts[2])
                pagefile_sizes.append((drive_letter, initial_size, max_size))

        return pagefile_sizes

    except FileNotFoundError:
        # If the PagingFiles value is not found, log a warning and return an empty list
        logger.warning("PagingFiles value not found in registry.")
        return []


def get_current_pagefile_settings() -> typing.Optional[list]:
    """
    Returns the current pagefile settings from the registry.

    Returns:
        typing.Optional[list]: A list of pagefile settings, where each setting is a string
            containing the path to the pagefile and its initial and maximum size in
            megabytes, separated by spaces. If no pagefile is found, returns None.
    """
    try:
        # Open the registry key that contains the pagefile settings
        reg_key: winreg.HKEYType = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management")

        # Query the PagingFiles value from the registry
        paging_files, reg_type = winreg.QueryValueEx(reg_key, "PagingFiles")

        # Close the registry key
        winreg.CloseKey(reg_key)

        return paging_files

    except FileNotFoundError:
        # If the PagingFiles value is not found, return None
        logger.warning("PagingFiles value not found in registry.")
        return None


# utils.py

def set_pagefile_size(drive_letter: str, required_mb: int, maximum_mb: int) -> bool:
    """
    设置指定驱动器的页面文件大小。
    
    Args:
        drive_letter (str): 目标驱动器盘符，例如 'C:'。
        required_mb (int): 初始大小（MB）。
        maximum_mb (int): 最大大小（MB）。
    
    Returns:
        bool: 操作是否成功。
    """
    import winreg

    # 标准化驱动器格式，确保以冒号结尾
    if not drive_letter.endswith(':'):
        drive_letter += ':'
    pagefile_path = f"{drive_letter}\\pagefile.sys"

    try:
        # 打开虚拟内存设置的注册表项
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management",
            0,
            winreg.KEY_READ | winreg.KEY_WRITE
        )

        # 读取当前的 Pagefile 配置
        current_value, _ = winreg.QueryValueEx(key, "PagingFiles")
        
        # 将字节串解码为字符串列表，并过滤掉空字符串
        if isinstance(current_value, bytes):
            current_entries = [entry for entry in current_value.decode('utf-16le').strip('\x00').split('\x00') if entry]
        else:
            current_entries = []

        # --- 修复核心逻辑 ---
        # 创建一个新的条目列表，移除目标驱动器的旧条目
        new_entries = []
        target_found = False
        for entry in current_entries:
            parts = entry.split()
            if len(parts) >= 1 and parts[0].lower().startswith(drive_letter.lower()):
                # 找到目标驱动器的旧条目，跳过它（即移除）
                target_found = True
                continue
            new_entries.append(entry)
        
        # 添加新的 pagefile 条目: "C:\pagefile.sys <初始大小> <最大大小>"
        new_entry = f"{pagefile_path} {required_mb} {maximum_of_mb}"
        new_entries.append(new_entry)

        # 将列表重新编码为注册表所需的宽字符（UTF-16LE）格式
        new_value_str = '\x00'.join(new_entries) + '\x00\x00'  # 双空终止
        new_value_bytes = new_value_str.encode('utf-16le')

        # 写入注册表
        winreg.SetValueEx(key, "PagingFiles", 0, winreg.REG_MULTI_SZ, new_value_bytes)
        winreg.CloseKey(key)

        return True

    except Exception as e:
        print(f"设置页面文件时出错: {e}")
        return False


def reset_pagefile_to_system_managed() -> None:
    """
    Resets the pagefile to system managed size on all drives.
    """
    try:
        # Command to set pagefile to system managed on all drives
        # This command clears the PagingFiles registry value, which effectively
        # tells Windows to manage pagefile sizes automatically.
        subKey = "SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Memory Management"
        args: str = '\'remove "{}\\{}" /v "{}" /f\''.format("HKLM", subKey, "PagingFiles")
        cmd: list[str] = ["powershell", "Start-Process", "-Verb", "runAs", "reg", "-ArgumentList", args]
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        subprocess.check_call(cmd, startupinfo=si)
        logger.info("Pagefile has been reset to system managed.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Unable to reset pagefile to system managed: {e}")
    except Exception as e:
        logger.error(f"Unknown error when resetting pagefile: {e}")

def open_virtual_memory_settings() -> None:
    """
    Opens the system's virtual memory settings dialog.
    """
    try:
        # Command to open the System Properties -> Advanced -> Performance Options -> Virtual Memory dialog
        subprocess.run(["control", "sysdm.cpl,,3"], check=True, shell=True)
        logger.info("Opened system virtual memory settings.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to open system virtual memory settings: {e}")
    except Exception as e:
        logger.error(f"Unknown error when opening system settings: {e}")

def run_powershell_command(command: str) -> str:
    """
    Runs a PowerShell command and returns the output.

    Args:
        command (str): The PowerShell command to run.

    Returns:
        str: The output of the PowerShell command.
    """
    # Run the PowerShell command and capture the output
    result: subprocess.CompletedProcess[str] = subprocess.run(["powershell", "-Command", command], capture_output=True, text=True)

    # Return the output of the PowerShell command
    return result.stdout


def extract_disk_and_partition(device_id: str) -> typing.Optional[typing.Tuple[int, int]]:
    """从设备ID中提取磁盘号和分区号。"""
    import re
    match = re.search(r'Disk #(\d+), Partition #(\d+)', device_id)
    if match:
        disk_number = int(match.group(1))
        partition_number = int(match.group(2))
        return (disk_number, partition_number)
    # --- 修复：直接返回 None，而不是 (None, None) ---
    return None


class Disk(object):
    """
    Represents a disk.
    """

    def __init__(self, device_id: int, model: str, media_type: str, bus_type: str, size: int):
        """
        Initializes a new instance of the Disk class.

        Args:
            device_id (int): The device ID of the disk.
            model (str): The model of the disk.
            media_type (str): The media type of the disk (Unspecified, HDD, SSD, SCM).
            bus_type (str): The bus type of the disk (e.g. "SATA", "USB", etc.).
            size (int): The size of the disk in bytes.
        """
        self.DeviceID: int = device_id
        """The device ID of the disk."""
        self.Model: str = model
        """The model of the disk."""
        self.MediaType: str = media_type
        """The media type of the disk (Unspecified, HDD, SSD, SCM)."""
        self.BusType: str = bus_type
        """The bus type of the disk (e.g. "SATA", "USB", etc.)."""
        self.Size: int = size
        """The size of the disk in bytes."""


class Partition(object):
    """
    Represents a partition on a disk.

    Attributes:
        DeviceID (int): The device ID of the partition.
        Model (str): The model of the partition.
        Partition (str): The partition number.
        Volume (str): The volume letter of the partition.
        FreeSize (int): The free space on the partition in megabytes.
        PageFileSizes (List[Tuple[str, int, int]]): The initial and maximum pagefile size on the partitions in megabytes.
    """

    def __init__(self, device_id: int, model: str, partition: str, volume: str):
        """
        Initializes a new instance of the Partition class.

        Args:
            device_id (int): The device ID of the partition.
            model (str): The model of the partition.
            partition (str): The partition number.
            volume (str): The volume letter of the partition.
        """
        self.DeviceID: int = device_id
        """The device ID of the partition."""
        self.Model: str = model
        """The model of the partition."""
        self.Partition: str = partition
        """The partition number."""
        self.Volume: str = volume
        """The volume letter of the partition."""
        self.FreeSize: int = get_free_space_mb(self.Volume)
        """The free space on the partition in megabytes."""
        self.PageFileSize: List[Tuple[str, int, int]] = get_pagefiles_size()
        """The initial and maximum pagefile size on the partition in megabytes."""


def get_disks_data() -> Dict[int, Disk]:
    ps_command = "Get-PhysicalDisk | Select-Object DeviceId, Model, MediaType, BusType, Size | ConvertTo-Json"

    output: str = run_powershell_command(ps_command)
    disk_data: Any = json.loads(output)

    disks: Dict[int, Disk] = {}

    for disk in disk_data:
        disks[int(disk["DeviceId"])] = Disk(int(disk["DeviceId"]), disk["Model"], disk["MediaType"], disk["BusType"], int(disk["Size"]))

    return disks


def get_partitions_data() -> Dict[str, Partition]:
    ps_command = """
    Get-WmiObject -Query "SELECT * FROM Win32_DiskDrive" | ForEach-Object {
        $disk = $_
        $partitions = Get-WmiObject -Query "ASSOCIATORS OF {Win32_DiskDrive.DeviceID='$($disk.DeviceID)'} WHERE AssocClass=Win32_DiskDriveToDiskPartition"
        foreach ($partition in $partitions) {
            $volumes = Get-WmiObject -Query "ASSOCIATORS OF {Win32_DiskPartition.DeviceID='$($partition.DeviceID)'} WHERE AssocClass=Win32_LogicalDiskToPartition"
            foreach ($volume in $volumes) {
                [PSCustomObject]@{
                    DiskModel = $disk.Model
                    Partition = $partition.DeviceID
                    Volume = $volume.DeviceID
                }
            }
        }
    } | ConvertTo-Json
    """

    output: str = run_powershell_command(ps_command)
    disk_data = json.loads(output)

    partitions: Dict[str, Partition] = {}

    for entry in disk_data:
        disk, partition = extract_disk_and_partition(entry["Partition"])
        partitions[entry["Volume"]] = Partition(disk, entry["DiskModel"], partition, entry["Volume"])

    return partitions
