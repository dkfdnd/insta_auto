"""Write cookie/session files without inheriting broad Windows permissions."""
from __future__ import annotations

import os
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def private_output_path(target: Path):
    """Publish a private file atomically; never change the parent directory ACL."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        import pywintypes
        import win32api
        import win32con
        import win32file
        import win32security

        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        finally:
            token.Close()
        user = win32security.ConvertSidToStringSid(sid)
        attributes = pywintypes.SECURITY_ATTRIBUTES()
        # Protect the DACL from inheritance. Keep normal SYSTEM/admin access.
        attributes.SECURITY_DESCRIPTOR = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            f"D:P(A;;FA;;;{user})(A;;FA;;;SY)(A;;FA;;;BA)", win32security.SDDL_REVISION_1,
        )
        temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        handle = win32file.CreateFile(
            str(temp), win32con.GENERIC_WRITE, 0, attributes,
            win32con.CREATE_NEW, win32con.FILE_ATTRIBUTE_NORMAL, None,
        )
        handle.Close()
    else:
        fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        os.close(fd)
        temp = Path(name)
    try:
        yield temp
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
