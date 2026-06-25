import sys

import requests
import typer
from rich import print
import player_cli.exploit
import player_cli.flags
import player_cli.service
import player_cli.auth
import player_cli.ctfconfig_wrapper
import player_cli.util

state = {
    'host': '',
    'bypass_tools': False,
    'debug': False
}

app = typer.Typer(no_args_is_help=True)

app.add_typer(player_cli.exploit.app,
              name='exploit', help='Manage exploits.')
app.add_typer(player_cli.flags.app,
              name='flag', help='Manage flags.')
app.add_typer(player_cli.service.app,
              name='service', help='Show services (legacy).')


DEFAULT_HOST = player_cli.auth.DEFAULT_ATAKA_BASE_URL or player_cli.ctfconfig_wrapper.ATAKA_HOST


@app.callback()
def main(
        host: str = typer.Option(DEFAULT_HOST, '--host', '-h',
                                 help='Ataka web API host or base URL.'),
        bypass_tools: bool = typer.Option(False, '--bypass-tools', '-b', help=
        'Interact directly with the gameserver instead of using our tools. '
        'Use only in emergencies!'),
        debug: bool = typer.Option(False, '--debug', '-d', help='Turn on debug logging')
):
    """
    Player command-line interface to Ataka.
    """
    state['host'] = host
    state['bypass_tools'] = bypass_tools
    state['debug'] = debug


@app.command('reload', help='Reload offline ctfconfig')
def reload_config(
        host: str = typer.Option(None, '--host', '-h',
                                 help='Ataka web API host.'),
    ):
    if host is not None:
        state['host'] = host

    SANITY_CHECK_STR = b'#!/usr/bin/env python3\nPK'

    cli_path = sys.argv[0]
    resp = requests.get(f"{player_cli.util.base_url(player_cli.state['host'])}/", auth=player_cli.auth.get_basic_auth())

    if resp.status_code != 200:
        print(f"{player_cli.state['host']} returned {resp.status_code}")
        return

    if not resp.content.startswith(SANITY_CHECK_STR):
        print(f"Invalid Response from {player_cli.state['host']}")
        return

    print(f"Writing player-cli at {cli_path}")
    with open(cli_path, 'wb') as f:
        f.write(resp.content)
