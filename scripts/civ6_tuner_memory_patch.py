"""Inspect, apply, or restore an experimental Civ VI multiplayer Tuner patch.

Targets one verified Windows DX11 executable. Changes process memory only.
Run at the main menu with MCP and the SDK FireTuner disconnected.
"""

import argparse
import ctypes
import hashlib
import sys
from ctypes import wintypes
from pathlib import Path

EXE_SHA256 = "e7450823cc8e00468cff7b9d7b97c63140eae38ae1d774ba4efa437556c42d63"
IMAGE_SIZE = 0x3704000
FUNCTION_RVA = 0x4F7820
BRANCH_OFFSET = 0x18
ORIGINAL = bytes.fromhex(
    "40 53 48 83 ec 20 48 8b d9 e8 62 8b c0 ff 48 8b c8 "
    "e8 ba a7 c0 ff 84 c0 74 0d 48 8b cb 48 83 c4 20 5b "
    "e9 19 9c ff ff 48 83 c4 20 5b c3"
)
# JE -> JMP, retaining the displacement to the existing stack-cleanup/return.
# Only this Tuner callback skips shutdown; the game-mode predicate is unchanged.
PATCHED = ORIGINAL[:BRANCH_OFFSET] + b"\xeb" + ORIGINAL[BRANCH_OFFSET + 1 :]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pid", type=int,
        help="CivilizationVI.exe process ID (auto-detected when exactly one DX11 instance is running)",
    )
    parser.add_argument("--action", choices=("check", "apply", "restore"), default="check")
    args = parser.parse_args()
    if sys.platform != "win32" or ctypes.sizeof(ctypes.c_void_p) != 8:
        parser.error("Requires Windows and 64-bit Python")

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    size_t = ctypes.c_size_t
    pointer = ctypes.c_void_p

    class ModuleInfo(ctypes.Structure):
        _fields_ = [
            ("base", pointer),
            ("size", wintypes.DWORD),
            ("entry", pointer),
        ]

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    signatures = {
        "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
        "Process32FirstW": ([wintypes.HANDLE, ctypes.POINTER(ProcessEntry)], wintypes.BOOL),
        "Process32NextW": ([wintypes.HANDLE, ctypes.POINTER(ProcessEntry)], wintypes.BOOL),
        "QueryFullProcessImageNameW": (
            [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)],
            wintypes.BOOL,
        ),
        "K32EnumProcessModules": (
            [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
             ctypes.POINTER(wintypes.DWORD)],
            wintypes.BOOL,
        ),
        "K32GetModuleInformation": (
            [wintypes.HANDLE, wintypes.HMODULE, ctypes.POINTER(ModuleInfo), wintypes.DWORD],
            wintypes.BOOL,
        ),
        "ReadProcessMemory": (
            [wintypes.HANDLE, pointer, pointer, size_t, ctypes.POINTER(size_t)], wintypes.BOOL,
        ),
        "WriteProcessMemory": (
            [wintypes.HANDLE, pointer, pointer, size_t, ctypes.POINTER(size_t)], wintypes.BOOL,
        ),
        "VirtualProtectEx": (
            [wintypes.HANDLE, pointer, size_t, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)],
            wintypes.BOOL,
        ),
        "FlushInstructionCache": ([wintypes.HANDLE, pointer, size_t], wintypes.BOOL),
    }
    for name, (argtypes, restype) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes = argtypes
        function.restype = restype

    def require(result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        return result

    if args.pid is None:
        snapshot = kernel.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        if snapshot == pointer(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        candidates = []
        dx12_running = False
        try:
            entry = ProcessEntry()
            entry.dwSize = ctypes.sizeof(entry)
            require(kernel.Process32FirstW(snapshot, ctypes.byref(entry)))
            while True:
                if entry.szExeFile.lower() == "civilizationvi.exe":
                    candidates.append(entry.th32ProcessID)
                elif entry.szExeFile.lower() == "civilizationvi_dx12.exe":
                    dx12_running = True
                if not kernel.Process32NextW(snapshot, ctypes.byref(entry)):
                    if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                        raise ctypes.WinError(ctypes.get_last_error())
                    break
        finally:
            kernel.CloseHandle(snapshot)
        if not candidates:
            detail = " DX12 is running, but this patch supports DX11 only." if dx12_running else ""
            raise RuntimeError(f"No CivilizationVI.exe process found. Start Civ using DX11.{detail}")
        if len(candidates) != 1:
            raise RuntimeError(f"Multiple DX11 instances found: {candidates}. Select one with --pid.")
        args.pid = candidates[0]

    # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ; add write/operation only on request.
    rights = 0x0400 | 0x0010
    if args.action != "check":
        rights |= 0x0020 | 0x0008
    handle = require(kernel.OpenProcess(rights, False, args.pid))
    try:
        path_buffer = ctypes.create_unicode_buffer(32768)
        path_length = wintypes.DWORD(len(path_buffer))
        require(kernel.QueryFullProcessImageNameW(handle, 0, path_buffer, ctypes.byref(path_length)))
        path = Path(path_buffer.value)
        if path.name.lower() != "civilizationvi.exe":
            raise RuntimeError(f"Unsupported process: {path.name}; expected CivilizationVI.exe (DX11)")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != EXE_SHA256:
            raise RuntimeError(f"Unsupported executable SHA-256: {digest}. No memory written.")

        modules = (wintypes.HMODULE * 1024)()
        needed = wintypes.DWORD()
        require(kernel.K32EnumProcessModules(handle, modules, ctypes.sizeof(modules), ctypes.byref(needed)))
        if needed.value < ctypes.sizeof(wintypes.HMODULE):
            raise RuntimeError("Main module not found")
        info = ModuleInfo()
        require(kernel.K32GetModuleInformation(handle, modules[0], ctypes.byref(info), ctypes.sizeof(info)))
        if info.size != IMAGE_SIZE or not info.base:
            raise RuntimeError("Unexpected main-module layout")
        address = info.base + FUNCTION_RVA

        def read_function():
            buffer = ctypes.create_string_buffer(len(ORIGINAL))
            count = size_t()
            require(kernel.ReadProcessMemory(handle, address, buffer, len(ORIGINAL), ctypes.byref(count)))
            if count.value != len(ORIGINAL):
                raise RuntimeError("Incomplete instruction read")
            return buffer.raw

        current = read_function()
        if current not in (ORIGINAL, PATCHED):
            raise RuntimeError(f"Unexpected live instructions: {current.hex(' ')}. No memory written.")
        print(f"PID: {args.pid}; executable: {path}")
        print(f"SHA-256 verified: {digest}")
        print(f"Function: 0x{address:x}; branch: 0x{address + BRANCH_OFFSET:x}")
        print(f"Current state: {'original' if current == ORIGINAL else 'patched'}")
        if args.action == "check":
            print("Read-only check complete.")
            return 0

        target = PATCHED if args.action == "apply" else ORIGINAL
        if current == target:
            print("Already in requested state; no memory written.")
            return 0
        if read_function() != current:
            raise RuntimeError("Instructions changed during verification; no memory written")

        branch = address + BRANCH_OFFSET
        previous_protection = wintypes.DWORD()
        require(kernel.VirtualProtectEx(handle, branch, 1, 0x40, ctypes.byref(previous_protection)))
        try:
            value = ctypes.c_ubyte(target[BRANCH_OFFSET])
            count = size_t()
            require(kernel.WriteProcessMemory(handle, branch, ctypes.byref(value), 1, ctypes.byref(count)))
            if count.value != 1:
                raise RuntimeError("Incomplete instruction write")
            require(kernel.FlushInstructionCache(handle, branch, 1))
        finally:
            unused = wintypes.DWORD()
            require(kernel.VirtualProtectEx(handle, branch, 1, previous_protection.value, ctypes.byref(unused)))
        if read_function() != target:
            raise RuntimeError("Post-write verification failed; exit Civ to discard the memory patch")
        print(f"{'Applied' if args.action == 'apply' else 'Restored'} and verified one byte in memory.")
        print("Executable file unchanged. Exiting Civ discards the patch.")
        return 0
    finally:
        kernel.CloseHandle(handle)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
