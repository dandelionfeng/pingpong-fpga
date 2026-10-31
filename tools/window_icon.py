"""Keep this launcher's icon attached to the application window it opens."""
from pathlib import Path
import ctypes,json,os,time
from ctypes import wintypes as W

def api():
    u=ctypes.WinDLL('user32',use_last_error=True);k=ctypes.WinDLL('kernel32',use_last_error=True)
    callback=ctypes.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
    u.EnumWindows.argtypes=[callback,W.LPARAM];u.EnumWindows.restype=W.BOOL
    u.IsWindowVisible.argtypes=[W.HWND];u.IsWindowVisible.restype=W.BOOL
    u.IsWindow.argtypes=[W.HWND];u.IsWindow.restype=W.BOOL
    u.GetWindowTextW.argtypes=[W.HWND,W.LPWSTR,ctypes.c_int]
    u.GetClassNameW.argtypes=[W.HWND,W.LPWSTR,ctypes.c_int]
    u.GetWindowThreadProcessId.argtypes=[W.HWND,ctypes.POINTER(W.DWORD)]
    k.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];k.OpenProcess.restype=W.HANDLE
    k.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,ctypes.POINTER(W.DWORD)]
    k.CloseHandle.argtypes=[W.HANDLE]
    u.LoadImageW.argtypes=[W.HINSTANCE,W.LPCWSTR,W.UINT,ctypes.c_int,ctypes.c_int,W.UINT];u.LoadImageW.restype=W.HANDLE
    u.SendMessageTimeoutW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM,W.UINT,W.UINT,ctypes.POINTER(ctypes.c_size_t)];u.SendMessageTimeoutW.restype=W.LPARAM
    u.DestroyIcon.argtypes=[W.HANDLE]
    return u,k,callback

def owned_windows(edge):
    if os.name!='nt':return set()
    u,k,callback=api();found=set();expected=Path(edge).resolve()
    def visit(hwnd,_):
        if not u.IsWindowVisible(hwnd):return True
        title=ctypes.create_unicode_buffer(256);kind=ctypes.create_unicode_buffer(64)
        u.GetWindowTextW(hwnd,title,len(title));u.GetClassNameW(hwnd,kind,len(kind))
        if title.value!='发球测量系统' or kind.value!='Chrome_WidgetWin_1':return True
        pid=W.DWORD();u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid));handle=k.OpenProcess(0x1000,False,pid.value)
        if handle:
            try:
                name=ctypes.create_unicode_buffer(32768);size=W.DWORD(len(name))
                if k.QueryFullProcessImageNameW(handle,0,name,ctypes.byref(size)) and Path(name.value).resolve()==expected:found.add(hwnd)
            finally:k.CloseHandle(handle)
        return True
    u.EnumWindows(callback(visit),0)
    return found

def retain_window_icon(root,edge,previous):
    """Only touch a newly opened window of this app; retain HICONs until it closes."""
    if os.name!='nt':return
    u,_,_=api();icons=[];report={'icon':'app/ui/application.ico','applied':False}
    path=Path(root)/'logs/window-icon.json'
    def message(hwnd,kind,value):
        answer=ctypes.c_size_t()
        if not u.SendMessageTimeoutW(hwnd,kind,value[0],value[1],2,1000,ctypes.byref(answer)):raise ctypes.WinError(ctypes.get_last_error())
        return answer.value
    try:
        deadline=time.monotonic()+15;hwnd=None
        while time.monotonic()<deadline:
            candidates=owned_windows(edge)-previous
            if len(candidates)==1:hwnd=candidates.pop();break
            time.sleep(.15)
        if hwnd is None:raise RuntimeError('Application window was not identified')
        for size in [16,32]:
            icon=u.LoadImageW(None,str(Path(root)/report['icon']),1,size,size,0x10)
            if not icon:raise ctypes.WinError(ctypes.get_last_error())
            icons.append(icon)
        # Edge can update its window while the page and favicon load.
        for _ in range(12):
            if not u.IsWindow(hwnd):return
            for which,icon in enumerate(icons):message(hwnd,0x80,(which,icon))
            time.sleep(.2)
        report.update(applied=True,hwnd=hwnd,small_icon_matches=message(hwnd,0x7f,(0,0))==icons[0],large_icon_matches=message(hwnd,0x7f,(1,0))==icons[1])
        path.write_text(json.dumps(report,indent=2),encoding='utf-8')
        while u.IsWindow(hwnd):time.sleep(.5)
    except Exception as error:
        report['error']=str(error);path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    finally:
        for icon in icons:u.DestroyIcon(icon)
