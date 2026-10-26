"""Railway Infrastructure as Code for the chartvf-discord-bot service.

Railway doesn't read this file during deploys. Preview with
`railway config plan`, apply with `railway config apply`; the settings then
live in the service. Replaces railway.toml (Config as Code ends 2026-12-01).
"""

from railway_sdk import define_railway, github, preserve, project, service

# This repo owns only the chartvf-discord-bot service in gallant-fascination.
PARTIAL = "chartvf-discord-bot"


@define_railway
def main(ctx=None):
    bot = service(
        "chartvf-discord-bot",
        source=github("feveromo/chartvf-discord-bot", checkSuites=False),
        build={
            "builder": "RAILPACK",
            # Only runtime inputs redeploy; tests, docs and CI changes don't.
            "watchPatterns": [
                "/*.py",
                "!/test_*.py",
                "/requirements.txt",
                "/.python-version",
                "/pyproject.toml",
            ],
        },
        start="python main.py",
        deploy={
            # Peaks near 150 MB and a fraction of a vCPU: the caps turn a
            # runaway into a restart instead of a bill.
            "limitOverride": {"containers": {"cpu": 1, "memoryBytes": 512 * 1024**2}},
        },
        replicas={"us-east4-eqdc4a": 1},
        env={"DISCORD_TOKEN": preserve()},
    )
    return project("gallant-fascination", resources=[bot])
