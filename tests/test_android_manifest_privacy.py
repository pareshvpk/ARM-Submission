from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

# Android attributes in the manifest live in this namespace, so every
# lookup below uses the expanded "{namespace}name" form.
ANDROID_NS = "http://schemas.android.com/apk/res/android"
MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "android"
    / "app"
    / "src"
    / "main"
    / "AndroidManifest.xml"
)

# The complete permission set the app is allowed to request today.
# Adding any permission later fails test_permission_set_matches_allowed_set
# on purpose: update this set (and docs/privacy_proof.md) in the same
# change so the privacy proof stays true.
ALLOWED_PERMISSIONS = frozenset(
    {
        "android.permission.RECEIVE_SMS",
        "android.permission.RECEIVE_MMS",
        "android.permission.READ_SMS",
        "android.permission.POST_NOTIFICATIONS",
    }
)

# Network access would let message content leave the device.
FORBIDDEN_NETWORK_PERMISSIONS = frozenset(
    {
        "android.permission.INTERNET",
        "android.permission.ACCESS_NETWORK_STATE",
        "android.permission.ACCESS_WIFI_STATE",
    }
)

SMS_RECEIVED_ACTION = "android.provider.Telephony.SMS_RECEIVED"
BROADCAST_SMS_PERMISSION = "android.permission.BROADCAST_SMS"


def _android_attr(element: ET.Element, name: str) -> str | None:
    """Return an android-namespaced attribute, or None when absent."""
    return element.get(f"{{{ANDROID_NS}}}{name}")


@pytest.fixture(scope="module")
def manifest_root() -> ET.Element:
    """Parse the Android manifest once for all tests in this module."""
    assert MANIFEST_PATH.is_file(), f"manifest not found: {MANIFEST_PATH}"
    return ET.parse(MANIFEST_PATH).getroot()


def _permissions(root: ET.Element) -> set[str]:
    """Return every uses-permission name declared in the manifest."""
    names: set[str] = set()
    for element in root.iter("uses-permission"):
        name = _android_attr(element, "name")
        if name:
            names.add(name)
    return names


def test_no_network_permissions(manifest_root: ET.Element):
    permissions = _permissions(manifest_root)
    forbidden = permissions & FORBIDDEN_NETWORK_PERMISSIONS
    assert not forbidden, f"network permissions must not be requested: {sorted(forbidden)}"
    assert "android.permission.INTERNET" not in permissions


def test_allow_backup_is_false(manifest_root: ET.Element):
    application = manifest_root.find("application")
    assert application is not None, "manifest has no <application> element"
    # Backups can copy SMS-derived data off the device, so it stays off.
    assert _android_attr(application, "allowBackup") == "false"


def test_exported_sms_receivers_require_broadcast_sms(manifest_root: ET.Element):
    sms_receivers = []
    for receiver in manifest_root.iter("receiver"):
        if _android_attr(receiver, "exported") != "true":
            continue
        actions = {
            _android_attr(action, "name")
            for intent_filter in receiver.findall("intent-filter")
            for action in intent_filter.findall("action")
        }
        if SMS_RECEIVED_ACTION not in actions:
            continue
        sms_receivers.append(receiver)
        assert _android_attr(receiver, "permission") == BROADCAST_SMS_PERMISSION, (
            f"exported SMS receiver {_android_attr(receiver, 'name')!r} must be "
            f"protected by {BROADCAST_SMS_PERMISSION}"
        )
    # The app must actually receive SMS; an empty set would pass vacuously.
    assert sms_receivers, "no exported SMS_RECEIVED receiver found in the manifest"


def test_permission_set_matches_allowed_set(manifest_root: ET.Element):
    permissions = _permissions(manifest_root)
    assert permissions == ALLOWED_PERMISSIONS, (
        f"permission set changed: got {sorted(permissions)}, "
        f"allowed {sorted(ALLOWED_PERMISSIONS)}. "
        "If this change is intentional, update ALLOWED_PERMISSIONS in this "
        "test and docs/privacy_proof.md in the same change."
    )
