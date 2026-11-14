import os

import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Set SMOKE_SHOTS=/some/folder to get a screenshot of the page of every failing smoke test (handy when debugging)."""
    out = yield
    rep = out.get_result()
    folder = os.environ.get("SMOKE_SHOTS")
    if folder and rep.when == "call" and rep.failed and "page" in item.funcargs:
        os.makedirs(folder, exist_ok=True)
        try:
            item.funcargs["page"].screenshot(path=os.path.join(folder, item.name + ".png"), full_page=True)
        except Exception:
            pass
