import glob
import os

import yaml

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def test_every_github_workflow_file_is_valid_yaml_and_has_jobs():
    files = glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml"))
    assert files
    for f in files:
        data = yaml.safe_load(open(f))                         # a broken file makes GitHub fail every push with no jobs at all
        assert data.get("jobs"), f
        assert data.get(True) or data.get("on"), f             # 'on' is read as True by YAML 1.1


def test_the_render_job_workflow_only_starts_for_job_branches_and_may_publish_releases():
    data = yaml.safe_load(open(os.path.join(ROOT, ".github", "workflows", "render-job.yml")))
    trigger = data.get(True) or data.get("on")
    assert trigger["push"]["tags"] == ["send-*"] and "branches" not in trigger["push"]
    assert data["permissions"]["contents"] == "write"
