"""Linux fail-closed parser sandbox. Inherited by renderer/OCR subprocesses."""

import ctypes
import errno
import os
from pathlib import Path
import resource
import socket


def restrict(
    directory: Path,
    *,
    read_paths=(),
    memory_bytes=1024**3,
    cpu_seconds=120,
    file_bytes=32 * 1024**2
):
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_bytes, file_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise RuntimeError("SANDBOX_UNAVAILABLE")

    # Landlock: parser sees its work directory and public runtime files only.
    # In particular, parent-process environments and application secrets are hidden.
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 1:
        raise RuntimeError("SANDBOX_UNAVAILABLE")
    access = (1 << 13) - 1
    if abi >= 2:
        access |= 1 << 13  # REFER
    if abi >= 3:
        access |= 1 << 14  # TRUNCATE

    class Ruleset(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64)]

    class PathRule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]

    attr = Ruleset(access)
    ruleset = libc.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    if ruleset < 0:
        raise RuntimeError("SANDBOX_UNAVAILABLE")
    try:
        paths = [(directory, access)]
        read = (1 << 0) | (1 << 2) | (1 << 3)  # execute/read_file/read_dir
        for path in (
            "/usr",
            "/lib",
            "/lib64",
            "/etc/fonts",
            "/etc/libreoffice",
            "/etc/ld.so.cache",
            "/etc/passwd",
            "/etc/group",
            "/var/cache/fontconfig",
            "/app/backend/.venv",
            "/app/backend/src",
            "/proc/self",
            *read_paths,
        ):
            if Path(path).exists():
                paths.append((Path(path), read))
        for path in ("/dev/null", "/dev/urandom", "/dev/random"):
            paths.append((Path(path), (1 << 1) | (1 << 2)))
        for path, allowed in paths:
            if not path.is_dir():
                allowed &= (1 << 0) | (1 << 1) | (1 << 2) | (1 << 14)
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = PathRule(allowed, fd)
                if libc.syscall(445, ruleset, 1, ctypes.byref(rule), 0) != 0:
                    raise RuntimeError("SANDBOX_UNAVAILABLE")
            finally:
                os.close(fd)
        if libc.syscall(446, ruleset, 0) != 0:
            raise RuntimeError("SANDBOX_UNAVAILABLE")
    finally:
        os.close(ruleset)

    seccomp = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    ctx = seccomp.seccomp_init(0x7FFF0000)  # ALLOW
    if not ctx:
        raise RuntimeError("SANDBOX_UNAVAILABLE")
    deny = 0x00050000 | errno.EPERM

    class ArgCompare(ctypes.Structure):
        _fields_ = [
            ("arg", ctypes.c_uint),
            ("op", ctypes.c_uint),
            ("a", ctypes.c_uint64),
            ("b", ctypes.c_uint64),
        ]

    try:
        syscall = seccomp.seccomp_syscall_resolve_name(b"socket")
        # SCMP_CMP_NE: only Unix-domain IPC is needed by headless LibreOffice.
        if seccomp.seccomp_rule_add(
            ctx, deny, syscall, 1, ArgCompare(0, 1, socket.AF_UNIX, 0)
        ):
            raise RuntimeError("SANDBOX_UNAVAILABLE")
        for name in (
            b"ptrace",
            b"process_vm_readv",
            b"process_vm_writev",
        ):
            number = seccomp.seccomp_syscall_resolve_name(name)
            if number >= 0 and seccomp.seccomp_rule_add(ctx, deny, number, 0):
                raise RuntimeError("SANDBOX_UNAVAILABLE")
        if seccomp.seccomp_load(ctx):
            raise RuntimeError("SANDBOX_UNAVAILABLE")
    finally:
        seccomp.seccomp_release(ctx)
