"""Tes penyimpanan API key. Registry Windows tidak disentuh (platform dipalsukan)."""
from app import secrets_store as ss


def test_mask_hides_middle():
    assert ss.mask("") == "belum diisi"
    assert ss.mask("sk-ant-abcdef123456") == "sk-a...3456"
    assert "abcdef" not in ss.mask("sk-ant-abcdef123456")


def test_save_sets_and_clears_process_env(monkeypatch):
    monkeypatch.setattr(ss.sys, "platform", "linux")
    monkeypatch.delenv("TAI_TEST_KEY", raising=False)
    ss.save("TAI_TEST_KEY", "  nilai-rahasia  ")
    assert ss.get("TAI_TEST_KEY") == "nilai-rahasia"
    ss.save("TAI_TEST_KEY", "")
    assert ss.get("TAI_TEST_KEY") == ""
