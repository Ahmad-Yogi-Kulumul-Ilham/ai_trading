"""Penyimpanan API key sebagai environment variable pengguna Windows.

Key ditulis ke HKEY_CURRENT_USER\\Environment (sama seperti perintah `setx`) dan langsung dipasang di
proses aplikasi yang sedang berjalan, jadi tidak perlu membuka ulang aplikasi. Key tidak pernah ditulis ke
folder proyek, sehingga tidak ikut ter-commit ke git.
"""
from __future__ import annotations

import os
import sys

CLAUDE_KEY = "ANTHROPIC_API_KEY"
INDODAX_KEY = "INDODAX_API_KEY"
INDODAX_SECRET = "INDODAX_SECRET_KEY"


def get(name: str) -> str:
    return os.environ.get(name, "").strip()


def mask(value: str) -> str:
    value = value.strip()
    if not value:
        return "belum diisi"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _broadcast_env_change() -> None:
    """Beri tahu Windows bahwa environment berubah, supaya program yang dibuka berikutnya ikut membaca."""
    try:
        import ctypes
        HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
                                                 SMTO_ABORTIFHUNG, 2000, ctypes.byref(result))
    except Exception:  # noqa: BLE001
        pass


def save(name: str, value: str) -> None:
    """Simpan permanen untuk pengguna ini dan pasang di proses sekarang. Nilai kosong menghapus key."""
    value = value.strip()
    if value:
        os.environ[name] = value
    else:
        os.environ.pop(name, None)
    if sys.platform != "win32":
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        if value:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        else:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass
    _broadcast_env_change()


def test_claude(api_key: str) -> str:
    """Cek key Claude dengan memanggil daftar model (gratis, tidak memakai token)."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key.strip(), max_retries=0, timeout=20)
    try:
        page = client.models.list(limit=5)
    except anthropic.AuthenticationError:
        raise RuntimeError("API key Claude ditolak. Periksa kembali key-nya di console.anthropic.com.")
    except anthropic.PermissionDeniedError:
        raise RuntimeError("API key Claude tidak punya izin. Periksa workspace dan billing di console.anthropic.com.")
    except anthropic.APIConnectionError:
        raise RuntimeError("Tidak bisa terhubung ke API Claude. Cek koneksi internet.")
    names = [m.id for m in page.data]
    return "Key Claude valid. Model tersedia: " + (", ".join(names) if names else "-")


def test_indodax(api_key: str, secret: str) -> str:
    """Cek key Indodax dengan membaca saldo (tidak mengirim order)."""
    from app.live.indodax_v2 import IndodaxV2Client

    c = IndodaxV2Client(api_key, secret)
    c.load_markets()
    bal = c.fetch_balance()
    info = bal.get("info", {})
    trade = "aktif" if info.get("canTrade") else "TIDAK aktif"
    withdraw = "aktif" if info.get("canWithdraw") else "mati"
    return (f"Key Indodax valid. Saldo Rupiah Rp {bal['IDR']['free']:,.0f}. "
            f"Izin trading {trade}, izin penarikan {withdraw}.")
