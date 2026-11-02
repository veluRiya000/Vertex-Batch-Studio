"""Process identity verification, Windows Job Object management, and lifecycle diagnostics."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

from . import __version__

PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000

CREATE_SUSPENDED = 0x00000004
HANDLE_FLAG_INHERIT = 0x00000001
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectBasicAccountingInformation = 1
JobObjectExtendedLimitInformation = 9
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102


if os.name == "nt":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)

    class _FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_int64),
            ("TotalKernelTime", ctypes.c_int64),
            ("ThisPeriodTotalUserTime", ctypes.c_int64),
            ("ThisPeriodTotalKernelTime", ctypes.c_int64),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    kernel32.SetHandleInformation.restype = wintypes.BOOL

    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL

    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE

    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL

    kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryInformationJobObject.restype = wintypes.BOOL

    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL

    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL

    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD

    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL

    ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    ntdll.NtResumeProcess.restype = ctypes.c_int32


def _filetime_to_u64(ft: _FILETIME) -> int:
    return (int(ft.dwHighDateTime) << 32) | int(ft.dwLowDateTime)


def process_creation_filetime(pid: int | None = None) -> int | None:
    """Return the exact Win32 64-bit FILETIME creation timestamp for a process."""
    if os.name != "nt":
        return None
    if pid is None or pid == os.getpid():
        handle = kernel32.GetCurrentProcess()
        close_after = False
    else:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return None
        close_after = True
    try:
        creation = _FILETIME()
        exit_time = _FILETIME()
        kernel_time = _FILETIME()
        user_time = _FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None
        return _filetime_to_u64(creation)
    finally:
        if close_after:
            kernel32.CloseHandle(handle)


def process_executable_path(pid: int | None = None) -> str | None:
    """Return the resolved executable path of a process."""
    if pid is None or pid == os.getpid():
        try:
            return str(Path(sys.executable).resolve())
        except OSError:
            return sys.executable
    if os.name != "nt":
        return None
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return None
    try:
        size = wintypes.DWORD(4096)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        try:
            return str(Path(buf.value).resolve())
        except OSError:
            return buf.value
    finally:
        kernel32.CloseHandle(handle)


def is_process_alive_with_identity(
    pid: int | None,
    expected_filetime: int | None = None,
    expected_exe: str | None = None,
) -> bool:
    """Verify that a PID is still running and matches its recorded creation time and image."""
    if not pid or pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, int(pid))
    if not handle:
        return False
    try:
        wait_res = kernel32.WaitForSingleObject(handle, 0)
        if wait_res != WAIT_TIMEOUT:
            return False
        if expected_filetime is not None:
            creation = _FILETIME()
            exit_time = _FILETIME()
            kernel_time = _FILETIME()
            user_time = _FILETIME()
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            ):
                return False
            if _filetime_to_u64(creation) != int(expected_filetime):
                return False
        if expected_exe:
            size = wintypes.DWORD(4096)
            buf = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return False
            try:
                actual_norm = os.path.normcase(str(Path(buf.value).resolve()))
                expected_norm = os.path.normcase(str(Path(expected_exe).resolve()))
            except OSError:
                actual_norm = os.path.normcase(buf.value)
                expected_norm = os.path.normcase(expected_exe)
            if actual_norm != expected_norm:
                return False
        return True
    finally:
        kernel32.CloseHandle(handle)


def resume_process_handle(process_handle: int) -> None:
    """Resume a process created with CREATE_SUSPENDED."""
    if os.name != "nt":
        return
    status = ntdll.NtResumeProcess(wintypes.HANDLE(process_handle))
    if status < 0:
        raise OSError(f"NtResumeProcess failed with NTSTATUS 0x{status & 0xFFFFFFFF:08x}")


class WindowsJobObject:
    """Non-inheritable kill-on-close Windows Job Object for a managed child tree."""

    def __init__(self, handle: int):
        self.handle: int | None = handle

    @classmethod
    def create(cls) -> WindowsJobObject:
        if os.name != "nt":
            raise RuntimeError("WindowsJobObject requires Windows")
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            err = ctypes.get_last_error()
            raise OSError(err, f"CreateJobObjectW failed (Win32 error {err})")
        try:
            if not kernel32.SetHandleInformation(handle, HANDLE_FLAG_INHERIT, 0):
                err = ctypes.get_last_error()
                raise OSError(err, f"SetHandleInformation failed (Win32 error {err})")
            info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel32.SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            ):
                err = ctypes.get_last_error()
                raise OSError(err, f"SetInformationJobObject failed (Win32 error {err})")
            return cls(int(handle))
        except Exception:
            kernel32.CloseHandle(handle)
            raise

    def assign_process_handle(self, process_handle: int) -> None:
        if self.handle is None:
            raise RuntimeError("Job handle is closed")
        if not kernel32.AssignProcessToJobObject(wintypes.HANDLE(self.handle), wintypes.HANDLE(process_handle)):
            err = ctypes.get_last_error()
            raise OSError(err, f"AssignProcessToJobObject failed (Win32 error {err})")

    def active_processes(self) -> int:
        if self.handle is None or os.name != "nt":
            return 0
        info = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        ret_len = wintypes.DWORD(0)
        if not kernel32.QueryInformationJobObject(
            wintypes.HANDLE(self.handle),
            JobObjectBasicAccountingInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
            ctypes.byref(ret_len),
        ):
            err = ctypes.get_last_error()
            raise OSError(err, f"QueryInformationJobObject failed (Win32 error {err})")
        return int(info.ActiveProcesses)

    def terminate(self, exit_code: int = 1) -> int | None:
        """Terminate all processes in the Job Object; returns None on success or Win32 error code."""
        if self.handle is None or os.name != "nt":
            return None
        if not kernel32.TerminateJobObject(wintypes.HANDLE(self.handle), wintypes.UINT(exit_code)):
            return ctypes.get_last_error()
        return None

    def close(self) -> None:
        if self.handle is not None and os.name == "nt":
            handle = self.handle
            self.handle = None
            kernel32.CloseHandle(wintypes.HANDLE(handle))


_REDACTED_WORDS = ("TOKEN", "KEY", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if any(word in str(k).upper() for word in _REDACTED_WORDS):
                out[k] = "[redacted]"
            else:
                out[k] = _scrub(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    return value


def log_lifecycle_event(root: Path, event: str, **fields: Any) -> None:
    """Append a structured diagnostic record to .runtime/lifecycle.log without leaking secrets."""
    try:
        runtime = Path(root) / ".runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "component": "backend",
            "version": __version__,
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "process_created_filetime": process_creation_filetime(),
            "event": event,
            **_scrub(fields),
        }
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with (runtime / "lifecycle.log").open("a", encoding="utf-8") as handle:
            handle.write(line)
    except Exception:
        pass


def find_locking_processes(paths: list[Path]) -> list[dict[str, Any]]:
    """Use Windows Restart Manager (rstrtmgr.dll) to identify processes holding target files."""
    if os.name != "nt":
        return []
    existing = [str(Path(p).resolve()) for p in paths if Path(p).exists()]
    if not existing:
        return []

    rstrtmgr = ctypes.WinDLL("rstrtmgr", use_last_error=True)
    ERROR_MORE_DATA = 234

    class _RM_UNIQUE_PROCESS(ctypes.Structure):
        _fields_ = [
            ("dwProcessId", wintypes.DWORD),
            ("ProcessStartTime", _FILETIME),
        ]

    class _RM_PROCESS_INFO(ctypes.Structure):
        _fields_ = [
            ("Process", _RM_UNIQUE_PROCESS),
            ("strAppName", wintypes.WCHAR * 256),
            ("strServiceShortName", wintypes.WCHAR * 64),
            ("ApplicationType", ctypes.c_int),
            ("AppStatus", wintypes.ULONG),
            ("TSSessionId", wintypes.DWORD),
            ("bRestartable", wintypes.BOOL),
        ]

    rstrtmgr.RmStartSession.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.LPWSTR]
    rstrtmgr.RmStartSession.restype = wintypes.DWORD
    rstrtmgr.RmRegisterResources.argtypes = [
        wintypes.DWORD,
        wintypes.UINT,
        ctypes.POINTER(wintypes.LPCWSTR),
        wintypes.UINT,
        ctypes.c_void_p,
        wintypes.UINT,
        ctypes.c_void_p,
    ]
    rstrtmgr.RmRegisterResources.restype = wintypes.DWORD
    rstrtmgr.RmGetList.argtypes = [
        wintypes.DWORD,
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(_RM_PROCESS_INFO),
        ctypes.POINTER(wintypes.DWORD),
    ]
    rstrtmgr.RmGetList.restype = wintypes.DWORD
    rstrtmgr.RmEndSession.argtypes = [wintypes.DWORD]
    rstrtmgr.RmEndSession.restype = wintypes.DWORD

    session = wintypes.DWORD(0)
    session_key = ctypes.create_unicode_buffer(33)
    if rstrtmgr.RmStartSession(ctypes.byref(session), 0, session_key) != 0:
        return []
    try:
        arr_type = wintypes.LPCWSTR * len(existing)
        res_array = arr_type(*existing)
        if rstrtmgr.RmRegisterResources(session, len(existing), res_array, 0, None, 0, None) != 0:
            return []
        needed = wintypes.UINT(0)
        count = wintypes.UINT(0)
        reasons = wintypes.DWORD(0)
        rc = rstrtmgr.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reasons))
        if rc == 0 and needed.value == 0:
            return []
        if rc not in (0, ERROR_MORE_DATA):
            return []
        capacity = max(1, int(needed.value) + 4)
        info_array = (_RM_PROCESS_INFO * capacity)()
        count.value = capacity
        rc = rstrtmgr.RmGetList(
            session,
            ctypes.byref(needed),
            ctypes.byref(count),
            info_array,
            ctypes.byref(reasons),
        )
        if rc != 0:
            return []
        results: list[dict[str, Any]] = []
        seen: set[tuple[int, int]] = set()
        for idx in range(int(count.value)):
            entry = info_array[idx]
            pid = int(entry.Process.dwProcessId)
            created_ft = _filetime_to_u64(entry.Process.ProcessStartTime)
            if pid == os.getpid() or (pid, created_ft) in seen:
                continue
            seen.add((pid, created_ft))
            exe_path = process_executable_path(pid)
            if is_process_alive_with_identity(pid, created_ft):
                results.append(
                    {
                        "pid": pid,
                        "process_created_filetime": created_ft,
                        "app_name": entry.strAppName,
                        "executable": exe_path,
                    }
                )
        return results
    finally:
        rstrtmgr.RmEndSession(session)


def terminate_verified_process(
    pid: int,
    expected_filetime: int,
    expected_exe: str | None = None,
    timeout: float = 3.0,
) -> bool:
    """Terminate a process only after verifying its kernel creation timestamp and image path on the open HANDLE."""
    if os.name != "nt" or not pid or pid <= 0 or pid == os.getpid():
        return False
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE | SYNCHRONIZE,
        False,
        int(pid),
    )
    if not handle:
        return True
    try:
        if kernel32.WaitForSingleObject(handle, 0) != WAIT_TIMEOUT:
            return True
        creation = _FILETIME()
        exit_time = _FILETIME()
        kernel_time = _FILETIME()
        user_time = _FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return False
        if _filetime_to_u64(creation) != int(expected_filetime):
            return False
        if expected_exe:
            size = wintypes.DWORD(4096)
            buf = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return False
            try:
                actual_norm = os.path.normcase(str(Path(buf.value).resolve()))
                expected_norm = os.path.normcase(str(Path(expected_exe).resolve()))
            except OSError:
                actual_norm = os.path.normcase(buf.value)
                expected_norm = os.path.normcase(expected_exe)
            if actual_norm != expected_norm:
                return False
        kernel32.TerminateProcess(handle, wintypes.UINT(1))
        wait_ms = max(100, int(timeout * 1000))
        return kernel32.WaitForSingleObject(handle, wintypes.DWORD(wait_ms)) == WAIT_OBJECT_0
    finally:
        kernel32.CloseHandle(handle)

