import sys
import subprocess
import click

def check_python_version():
    if sys.version_info < (3, 12):
        print(f"ERROR: Python 3.12+ required. You are on {sys.version}")
        print("Make sure Python 3.12 is accessible via 'python' command.")
        sys.exit(1)

check_python_version()

@click.group()
def cli():
    """SRE-AI: AI-assisted Root Cause Analysis tool."""
    pass

@cli.command()
def status():
    """Check environment status."""
    click.echo("Python version: OK")
    click.echo("Virtual env: jarvis")
    click.echo("Running environment check...\n")
    try:
        subprocess.run(
            "bash scripts/check_env.sh",
            shell=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        click.echo(f"\nERROR: Script failed with exit code {e.returncode}")
    # click.echo("Run 'bash scripts/check_env.sh' to verify full setup.")

if __name__ == "__main__":
    cli()
