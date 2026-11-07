"""首次引导套用新手侧栏: 未自定义才写入, 已有隐藏项不覆盖。"""
from __future__ import annotations

import pytest

from app.api import settings as settings_api
from app.services import preferences


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    path = tmp_path / "preferences.json"
    monkeypatch.setattr(preferences, "_path", lambda: path)
    preferences._invalidate_cache()
    yield path
    preferences._invalidate_cache()


def test_complete_onboarding_applies_beginner_nav_when_empty():
    result = settings_api.complete_onboarding()
    assert result["onboarding_completed"] is True
    assert result["nav_hidden"] == preferences.BEGINNER_NAV_HIDDEN
    assert preferences.get_nav_hidden() == preferences.BEGINNER_NAV_HIDDEN


def test_complete_onboarding_keeps_existing_nav_hidden():
    preferences.set_nav_hidden(["/mining"])
    result = settings_api.complete_onboarding()
    assert result["nav_hidden"] == ["/mining"]
    assert preferences.get_nav_hidden() == ["/mining"]


def test_apply_beginner_nav_if_unset_is_idempotent_on_existing():
    preferences.set_nav_hidden(["/review", "/monitor"])
    assert preferences.apply_beginner_nav_if_unset() == ["/review", "/monitor"]
