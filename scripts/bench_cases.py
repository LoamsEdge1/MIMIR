"""
MIMIR benchmark cases.

Gold labels for the local classifier. Kept separate from the runner so the set
can grow without touching logic.

HOW TO USE THIS FILE
--------------------
When MIMIR misclassifies something in real use, add it here with the correct
label. The set is meant to get harder over time. A falling score after adding
cases means the benchmark is working, not that the model got worse.

DESIGN NOTE
-----------
The first version of this benchmark had 16 clean cases and qwen scored 100%.
That number was meaningless — the cases and the prompt were written by the same
author, so it measured prompt fit, not capability. This set deliberately
includes ambiguity, typos, missing context, and requests that SHOULD return
"unknown". Expect a lower score. That is the point.
"""

# (prompt, gold task_class)
CASES = [
    # --- chat: conversation and questions about MIMIR / the machine's own state
    ("hey", "chat"),
    ("what can you do", "chat"),
    ("what's my GPU doing right now", "chat"),
    ("how much disk space is left", "chat"),
    ("are you using the local model or the cloud", "chat"),
    ("how many escalations have I burned today", "chat"),
    ("whats ur status", "chat"),

    # --- file_op: a single operation on files or folders
    ("find every csv in downloads from this month", "file_op"),
    ("move those into a folder called sorted", "file_op"),
    ("delete the temp files in my documents folder", "file_op"),
    ("what's in my downloads folder", "file_op"),
    ("rename budget_final_FINAL_v2.xlsx to something sane", "file_op"),
    ("copy the thesis draft to my desktop", "file_op"),
    ("find that pdf i was looking at yesterday", "file_op"),
    ("how big is the volleyscout folder", "file_op"),

    # --- app_control
    ("open the orb console", "app_control"),
    ("close chrome", "app_control"),
    ("launch excel", "app_control"),
    ("bring up kratos", "app_control"),
    ("shut down every browser window", "app_control"),
    ("is ollama running", "app_control"),

    # --- code
    ("fix the bug in my router module", "code"),
    ("write a python script that parses this csv", "code"),
    ("why is this function returning none", "code"),
    ("refactor the gate logic to be testable", "code"),
    ("add type hints to chaining.py", "code"),
    ("explain what this regex does", "code"),

    # --- analysis: reasoning over content the user already has
    ("compare the last three quarters of revenue and tell me what changed", "analysis"),
    ("summarise this document and pull out the key risks", "analysis"),
    ("what are the main themes in these meeting notes", "analysis"),
    ("does this contract have anything unusual in it", "analysis"),
    ("read my thesis draft and tell me where the argument is weak", "analysis"),

    # --- financial: requires market data
    ("what's NVDA trading at", "financial"),
    ("screen for tickers with unusual volume today", "financial"),
    ("should I be watching AMD right now", "financial"),
    ("how did my portfolio do this week", "financial"),
    ("analyse TSLA for me", "financial"),          # 'analyse' + ticker -> still financial
    ("what's the market doing", "financial"),

    # --- multistep: chained, dependent actions
    ("download the report, rename it, and email it to my advisor", "multistep"),
    ("index my project folder then tell me what changed this week", "multistep"),
    ("move those files then commit the change", "multistep"),
    ("unzip the archive and install the package", "multistep"),
    ("save the file, then push it", "multistep"),
    ("export the data, clean it up, then build me a chart", "multistep"),
    ("back up my documents and then delete the originals", "multistep"),

    # --- unknown: gibberish, too vague to act on, or genuinely ambiguous
    ("asdkjh qwe", "unknown"),
    ("do the thing", "unknown"),
    ("fix it", "unknown"),
    ("you know what I mean", "unknown"),
    ("same as last time", "unknown"),
    ("...", "unknown"),
    ("handle that for me would you", "unknown"),

    # --- adversarial: typos, sloppy phrasing, near-miss boundaries
    ("opne chrmoe", "app_control"),
    ("delet teh temp files", "file_op"),
    ("whats nvda at", "financial"),
    ("can you look at my code", "code"),
    ("tell me about my files", "file_op"),
]

# Prompts with NO nameable target. Any target the model returns here was
# invented. This measures the failure mode that actually causes damage.
HALLUCINATION_PROBES = [
    "do the thing",
    "fix it",
    "open that file I was working on",
    "clean up the old stuff",
    "send it when you're done",
    "check on my project",
    "what happened to it",
    "handle that for me would you",
]
