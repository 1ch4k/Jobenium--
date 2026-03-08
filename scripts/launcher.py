import questionary

# Local imports
from hellowork import run as run_hellowork
from apec import run as run_apec
from jobteaser import run as run_jobteaser

# Dictionary of platforms
platforms = {
    "HelloWork": run_hellowork,
    "APEC": run_apec,
    "JobTeaser": run_jobteaser
}

# Show the selection menu
selected_run = questionary.select(
    "Choose a job platform to launch:",
    choices=[questionary.Choice(title=name, value=fn) for name, fn in platforms.items()]
).ask()

# Run the selected script
selected_run()