"""Public release identity; never expose arbitrary environment values."""
import os
import re


def release_identity():
    candidate = os.getenv("RAILWAY_GIT_COMMIT_SHA") or os.getenv("APP_COMMIT") or os.getenv("GITHUB_SHA") or ""
    return {"backend_commit": candidate if re.fullmatch(r"[0-9a-fA-F]{7,40}", candidate) else "unidentified",
            "schema": "accepted-facts-v5; investment-context-c211028a007"}
