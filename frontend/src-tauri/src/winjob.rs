//! Windows Job Object management, process identity verification, and lifecycle diagnostics.

use serde_json::{json, Value};
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

#[cfg(windows)]
use std::{ffi::c_void, mem:: size_of, os::windows::io::RawHandle};

#[cfg(windows)]
const PROCESS_TERMINATE: u32 = 0x0001;
#[cfg(windows)]
const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;
#[cfg(windows)]
const SYNCHRONIZE: u32 = 0x0010_0000;

#[cfg(windows)]
pub const CREATE_NO_WINDOW: u32 = 0x0800_0000;
#[cfg(windows)]
pub const CREATE_SUSPENDED: u32 = 0x0000_0004;

#[cfg(windows)]
const HANDLE_FLAG_INHERIT: u32 = 0x0000_0001;
#[cfg(windows)]
const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: u32 = 0x0000_2000;
#[cfg(windows)]
const JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS: i32 = 1;
#[cfg(windows)]
const JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS: i32 = 9;
#[cfg(windows)]
const WAIT_TIMEOUT: u32 = 0x0000_0102;

#[cfg(windows)]
#[repr(C)]
#[derive(Clone, Copy, Default)]
struct FILETIME {
    dw_low_date_time: u32,
    dw_high_date_time: u32,
}

#[cfg(windows)]
#[repr(C)]
#[derive(Clone, Copy, Default)]
struct IO_COUNTERS {
    read_operation_count: u64,
    write_operation_count: u64,
    other_operation_count: u64,
    read_transfer_count: u64,
    write_transfer_count: u64,
    other_transfer_count: u64,
}

#[cfg(windows)]
#[repr(C)]
#[derive(Clone, Copy, Default)]
struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
    per_process_user_time_limit: i64,
    per_job_user_time_limit: i64,
    limit_flags: u32,
    minimum_working_set_size: usize,
    maximum_working_set_size: usize,
    active_process_limit: u32,
    affinity: usize,
    priority_class: u32,
    scheduling_class: u32,
}

#[cfg(windows)]
#[repr(C)]
#[derive(Clone, Copy, Default)]
struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
    basic_limit_information: JOBOBJECT_BASIC_LIMIT_INFORMATION,
    io_info: IO_COUNTERS,
    process_memory_limit: usize,
    job_memory_limit: usize,
    peak_process_memory_used: usize,
    peak_job_memory_used: usize,
}

#[cfg(windows)]
#[repr(C)]
#[derive(Clone, Copy, Default)]
struct JOBOBJECT_BASIC_ACCOUNTING_INFORMATION {
    total_user_time: i64,
    total_kernel_time: i64,
    this_period_total_user_time: i64,
    this_period_total_kernel_time: i64,
    total_page_fault_count: u32,
    total_processes: u32,
    active_processes: u32,
    total_terminated_processes: u32,
}

#[cfg(windows)]
#[link(name = "kernel32")]
extern "system" {
    fn GetLastError() -> u32;
    fn GetCurrentProcess() -> RawHandle;
    fn OpenProcess(desired_access: u32, inherit_handle: i32, process_id: u32) -> RawHandle;
    fn CloseHandle(object: RawHandle) -> i32;
    fn SetHandleInformation(object: RawHandle, mask: u32, flags: u32) -> i32;
    fn GetProcessTimes(
        process: RawHandle,
        creation_time: *mut FILETIME,
        exit_time: *mut FILETIME,
        kernel_time: *mut FILETIME,
        user_time: *mut FILETIME,
    ) -> i32;
    fn QueryFullProcessImageNameW(
        process: RawHandle,
        flags: u32,
        exe_name: *mut u16,
        size: *mut u32,
    ) -> i32;
    fn CreateJobObjectW(job_attributes: *const c_void, name: *const u16) -> RawHandle;
    fn SetInformationJobObject(
        job: RawHandle,
        info_class: i32,
        info: *const c_void,
        info_length: u32,
    ) -> i32;
    fn QueryInformationJobObject(
        job: RawHandle,
        info_class: i32,
        info: *mut c_void,
        info_length: u32,
        return_length: *mut u32,
    ) -> i32;
    fn AssignProcessToJobObject(job: RawHandle, process: RawHandle) -> i32;
    fn TerminateJobObject(job: RawHandle, exit_code: u32) -> i32;
    fn WaitForSingleObject(handle: RawHandle, milliseconds: u32) -> u32;
    fn TerminateProcess(process: RawHandle, exit_code: u32) -> i32;
}

#[cfg(windows)]
#[link(name = "ntdll")]
extern "system" {
    fn NtResumeProcess(process_handle: RawHandle) -> i32;
}

#[cfg(windows)]
pub fn process_filetime_from_handle(handle: RawHandle) -> Option<u64> {
    if handle.is_null() {
        return None;
    }
    let mut creation = FILETIME::default();
    let mut exit = FILETIME::default();
    let mut kernel = FILETIME::default();
    let mut user = FILETIME::default();
    let ok = unsafe { GetProcessTimes(handle, &mut creation, &mut exit, &mut kernel, &mut user) };
    if ok == 0 {
        return None;
    }
    Some(((creation.dw_high_date_time as u64) << 32) | (creation.dw_low_date_time as u64))
}

#[cfg(windows)]
pub fn current_process_filetime() -> Option<u64> {
    process_filetime_from_handle(unsafe { GetCurrentProcess() })
}

#[cfg(not(windows))]
pub fn current_process_filetime() -> Option<u64> {
    None
}

#[cfg(windows)]
pub fn resume_suspended_process(process_handle: RawHandle) -> Result<(), String> {
    let status = unsafe { NtResumeProcess(process_handle) };
    if status < 0 {
        return Err(format!(
            "NtResumeProcess failed with NTSTATUS 0x{:08x}",
            status as u32
        ));
    }
    Ok(())
}

#[cfg(windows)]
pub struct Job(RawHandle);

#[cfg(windows)]
unsafe impl Send for Job {}
#[cfg(windows)]
unsafe impl Sync for Job {}

#[cfg(windows)]
impl Job {
    pub fn create() -> Result<Self, String> {
        let handle = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
        if handle.is_null() {
            let err = unsafe { GetLastError() };
            return Err(format!("CreateJobObjectW failed (Win32 error {err})"));
        }
        let job = Self(handle);
        let ok_inherit = unsafe { SetHandleInformation(job.0, HANDLE_FLAG_INHERIT, 0) };
        if ok_inherit == 0 {
            let err = unsafe { GetLastError() };
            return Err(format!("SetHandleInformation failed (Win32 error {err})"));
        }
        let mut info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        info.basic_limit_information.limit_flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let ok_limit = unsafe {
            SetInformationJobObject(
                job.0,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                (&info as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast::<c_void>(),
                size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            )
        };
        if ok_limit == 0 {
            let err = unsafe { GetLastError() };
            return Err(format!("SetInformationJobObject failed (Win32 error {err})"));
        }
        Ok(job)
    }

    pub fn assign_process(&self, process_handle: RawHandle) -> Result<(), String> {
        let ok = unsafe { AssignProcessToJobObject(self.0, process_handle) };
        if ok == 0 {
            let err = unsafe { GetLastError() };
            return Err(format!(
                "AssignProcessToJobObject failed (Win32 error {err})"
            ));
        }
        Ok(())
    }

    pub fn active_processes(&self) -> Result<u32, String> {
        let mut info = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION::default();
        let mut ret_len: u32 = 0;
        let ok = unsafe {
            QueryInformationJobObject(
                self.0,
                JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS,
                (&mut info as *mut JOBOBJECT_BASIC_ACCOUNTING_INFORMATION).cast::<c_void>(),
                size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
                &mut ret_len,
            )
        };
        if ok == 0 {
            let err = unsafe { GetLastError() };
            return Err(format!(
                "QueryInformationJobObject failed (Win32 error {err})"
            ));
        }
        Ok(info.active_processes)
    }

    pub fn terminate(&self, exit_code: u32) -> Result<(), String> {
        let ok = unsafe { TerminateJobObject(self.0, exit_code) };
        if ok == 0 {
            let err = unsafe { GetLastError() };
            return Err(format!("TerminateJobObject failed (Win32 error {err})"));
        }
        Ok(())
    }
}

#[cfg(windows)]
impl Drop for Job {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe {
                CloseHandle(self.0);
            }
            self.0 = std::ptr::null_mut();
        }
    }
}

#[cfg(windows)]
fn normalize_win_path(p: &Path) -> String {
    let resolved = fs::canonicalize(p).unwrap_or_else(|_| p.to_path_buf());
    let s = resolved.to_string_lossy();
    let stripped = s.strip_prefix(r"\\?\").unwrap_or(&s);
    stripped.to_lowercase()
}

#[cfg(windows)]
fn query_image_path(handle: RawHandle) -> Option<PathBuf> {
    let mut buf = vec![0u16; 4096];
    let mut size = buf.len() as u32;
    let ok = unsafe { QueryFullProcessImageNameW(handle, 0, buf.as_mut_ptr(), &mut size) };
    if ok == 0 {
        return None;
    }
    Some(PathBuf::from(String::from_utf16_lossy(&buf[..size as usize])))
}

#[cfg(windows)]
pub struct VerifiedProcess {
    handle: RawHandle,
    pub pid: u32,
}

#[cfg(windows)]
unsafe impl Send for VerifiedProcess {}
#[cfg(windows)]
unsafe impl Sync for VerifiedProcess {}

#[cfg(windows)]
impl VerifiedProcess {
    pub fn open_verified(
        pid: u32,
        expected_filetime: Option<u64>,
        expected_exe: Option<&str>,
    ) -> Option<Self> {
        if pid == 0 {
            return None;
        }
        let handle = unsafe {
            OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE | PROCESS_TERMINATE,
                0,
                pid,
            )
        };
        if handle.is_null() {
            return None;
        }
        let proc_ref = Self { handle, pid };
        if proc_ref.is_exited() {
            return None;
        }
        if let Some(exp_ft) = expected_filetime {
            let actual_ft = process_filetime_from_handle(proc_ref.handle)?;
            if actual_ft != exp_ft {
                return None;
            }
        }
        if let Some(exp_exe) = expected_exe {
            if !exp_exe.is_empty() {
                let actual_path = query_image_path(proc_ref.handle)?;
                if normalize_win_path(&actual_path) != normalize_win_path(Path::new(exp_exe)) {
                    return None;
                }
            }
        }
        Some(proc_ref)
    }

    pub fn is_exited(&self) -> bool {
        let res = unsafe { WaitForSingleObject(self.handle, 0) };
        res != WAIT_TIMEOUT
    }

    pub fn terminate(&self, exit_code: u32) -> Result<(), String> {
        let ok = unsafe { TerminateProcess(self.handle, exit_code) };
        if ok == 0 {
            let err = unsafe { GetLastError() };
            return Err(format!("TerminateProcess failed (Win32 error {err})"));
        }
        Ok(())
    }
}

#[cfg(windows)]
impl Drop for VerifiedProcess {
    fn drop(&mut self) {
        if !self.handle.is_null() {
            unsafe {
                CloseHandle(self.handle);
            }
            self.handle = std::ptr::null_mut();
        }
    }
}

pub fn generate_instance_id() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let pid = std::process::id() as u128;
    let ft = current_process_filetime().unwrap_or(0) as u128;
    let combined = nanos ^ (pid << 64) ^ (ft << 16);
    format!("{:016x}{:016x}", (combined >> 64) as u64, combined as u64)
}

pub fn log_lifecycle(root: &Path, instance_id: &str, event: &str, details: Value) {
    let runtime_dir = root.join(".runtime");
    let _ = fs::create_dir_all(&runtime_dir);
    let ts_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    let mut record = json!({
        "ts_epoch_ms": ts_ms,
        "event": event,
        "source": "desktop",
        "version": env!("CARGO_PKG_VERSION"),
        "instance_id": instance_id,
        "desktop_pid": std::process::id(),
        "desktop_created_filetime": current_process_filetime(),
    });
    if let (Some(base), Some(extra)) = (record.as_object_mut(), details.as_object()) {
        for (k, v) in extra {
            base.insert(k.clone(), v.clone());
        }
    }
    if let Ok(mut file) = OpenOptions::new()
        .create(true)
        .append(true)
        .open(runtime_dir.join("lifecycle.log"))
    {
        if let Ok(line) = serde_json::to_string(&record) {
            let _ = writeln!(file, "{line}");
        }
    }
}
