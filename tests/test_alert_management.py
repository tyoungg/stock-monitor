
import re
from playwright.sync_api import Page, expect

def test_alert_management(page: Page):
    page.set_viewport_size({"width": 1280, "height": 1024})
    page.goto("http://127.0.0.1:5000/")

    # Take a screenshot of the initial state
    page.screenshot(path="verification/alert_management_initial.png")

    # Re-enable the 'high' alert for AAPL
    page.get_by_role("button", name="Re-enable high").click()

    # Take a screenshot after re-enabling an alert
    page.screenshot(path="verification/alert_management_re_enabled.png")

    # Clear all silenced alerts
    page.get_by_role("button", name="Clear All Silenced Alerts").click()

    # Take a screenshot after clearing all alerts
    page.screenshot(path="verification/alert_management_cleared.png")
