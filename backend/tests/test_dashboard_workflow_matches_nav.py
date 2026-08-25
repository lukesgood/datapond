"""The dashboard's workflow and the menu have to agree.

The dashboard opens with "Portable core workflow" — five numbered steps, each a link.
The sidebar is the same product organised a different way. When they drift, the first
thing a new user does is follow a step to a page the menu files somewhere else, or
under a different name.

Both drifted, and both from changes made in this branch. Step 04 "Serve" pointed at
/ai after AI Gateway moved out of Build AI, so the workflow described a menu layout
that no longer existed. And a new menu item was added called "Connect" — the name
step 01 already uses for connecting a data *source*, which is what the word means
everywhere else in a data platform. Two opposite ends of the pipeline cannot share a
name.

Read out of the TSX rather than duplicated here: a copy of the mapping in a test is
one more thing to drift.
"""
import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
STRIP = FRONTEND / "components/dashboard/journey-strip.tsx"
SIDEBAR = FRONTEND / "components/app-sidebar.tsx"


def _journey_steps():
    """(number, title, href) for each step, including conditional hrefs."""
    text = STRIP.read_text()
    steps = []
    for block in re.findall(r'n:\s*"(\d+)",(.*?)color:', text, re.S):
        number, body = block
        title = re.search(r'title:\s*"([^"]+)"', body)
        hrefs = re.findall(r'"(/[a-z-]*)"', body.split("href:", 1)[1].split("\n")[0]) \
            if "href:" in body else []
        steps.append((number, title.group(1) if title else "?", hrefs))
    return steps


def _nav_items():
    """{url: title} for every sidebar entry."""
    text = SIDEBAR.read_text()
    return {m.group(2): m.group(1) for m in
            re.finditer(r'title:\s*"([^"]+)",\s*url:\s*"([^"]+)"', text)}


def test_the_strip_still_has_five_steps():
    """Guards the parser: a regex that silently matched nothing would make every
    other test in this file pass while checking nothing."""
    assert len(_journey_steps()) == 5, _journey_steps()


def test_every_workflow_step_leads_somewhere_the_menu_has():
    nav = _nav_items()
    missing = [(n, t, h) for n, t, hrefs in _journey_steps()
               for h in hrefs if h not in nav]
    assert not missing, (
        "workflow steps link to pages with no menu item — a user following the "
        f"workflow lands somewhere they cannot find again: {missing}"
    )


def test_no_menu_item_takes_a_name_a_workflow_step_already_uses():
    """Step 01 is "Connect", meaning connect a data source. A menu item of the same
    name meaning connect an application put the same word on both ends of the
    pipeline."""
    step_titles = {t.lower() for _n, t, _h in _journey_steps()}
    clashes = [title for title in _nav_items().values()
               if title.lower() in step_titles]
    assert not clashes, f"menu items reuse a workflow step's name: {clashes}"


@pytest.mark.parametrize("step,expected_nav", [
    ("Ground", "Knowledge"),
    ("Serve", "API"),
    ("Govern", "Governance"),
])
def test_the_unconditional_steps_point_at_the_expected_page(step, expected_nav):
    """The three steps that do not branch on a capability. 01 and 02 deliberately
    lead somewhere different depending on which adapters a deployment has."""
    nav = _nav_items()
    href = next(h for _n, t, hrefs in _journey_steps() if t == step for h in hrefs)
    assert nav.get(href) == expected_nav, f"{step} → {href} → {nav.get(href)}"
