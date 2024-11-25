import re
import asyncio
from collections import deque
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from src.calls import AioHttpCalls
from src.converter import pubkey_to_consensus_hex

class ConsensusDashboard:
    def __init__(self, refresh_per_second: int, disable_emojis: bool):
        self.num_columns = 4
        self.layout = Layout()
        self.console = Console()
        self.log_lines = deque(maxlen=10)
        self.validators = []
        self.current_round_consensus_state = {
            'height': -1,
            'round': -1,
            'step': -1,
            'prevote_array': 0.0,
            'precommits_array': 0.0,
            'hex_prevote': {},
            'hex_precommit': {}
        }
        self.chain_id = None
        self.catching_up = False
        self.online_validators = 0
        self.ugrade_plan = False

        self.refresh_per_second = refresh_per_second
        self.disable_emojis = disable_emojis

        self.layout.split_column(
            Layout(name="header", ratio=1),
            Layout(name="footer", ratio=3)
        )

        self.layout["header"].split_row(
            Layout(name="logs"),
            Layout(name="votes_commits_bar"),
            Layout(name="network_info")

        )

        self.layout["footer"].update(self.generate_table())

    async def fetch_chain_data(self):
        async with AioHttpCalls() as session:
            rpc_status = await session.get_rpc_status()
            ugrade_plan = await session.get_upgrade_info()
        if rpc_status:
            self.catching_up = rpc_status['sync_info']['catching_up']
            self.chain_id = rpc_status['node_info']['network']
        if ugrade_plan:
            self.ugrade_plan = ugrade_plan['plan']

    def demojize(self, moniker):
        emoji_pattern = re.compile("[\U00010000-\U0010ffff]", flags=re.UNICODE)
        allowed_pattern = re.compile(r'[^a-zA-Z0-9_\-& ]')
        text_without_emojis = emoji_pattern.sub('', moniker)
        cleaned_text = allowed_pattern.sub('', text_without_emojis)
        return cleaned_text.strip()

    async def update_validators(self):
        try:
            async with AioHttpCalls() as session:
                data = await session.get_validators(status='BOND_STATUS_BONDED')
                if data:
                    sorted_vals = sorted(data, key=lambda x: int(x['tokens']), reverse=True)
                    validators = []
                    total_stake = sum(int(x['tokens']) for x in sorted_vals)
                    for validator  in sorted_vals:
                        _consensus_pub_key = validator.get('consensus_pubkey',{}).get('key')
                        if not _consensus_pub_key:
                            self.log_lines.append(f'Skipping validator due too missing consensus_pub_key: {validator}')
                            continue
                        _moniker = self.demojize(validator.get('description',{}).get('moniker', 'N/A'))
                        _tokens = int(validator['tokens'])

                        _hex = pubkey_to_consensus_hex(pub_key=_consensus_pub_key)
                        validators.append({
                            'moniker': _moniker,
                            'hex': _hex,
                            'vp': round((_tokens / total_stake) * 100, 4)
                            })

                    
                    self.validators = validators
                    self.log_lines.append(f"Updated validators | Current active set: {len(self.validators)}")
                    return True
        except Exception:
            self.log_lines.append(f"An error occurred while updating validators")

    async def update_current_consensus_state(self):
        try:
            async with AioHttpCalls() as session:
                data = await session .get_consensus_state()
            if not data:
                self.log_lines.append("Failed to fetch consensus_state. Will retry")
                return
            
            self.all_rounds_consensus_state = data
            height_round_step = data['round_state']['height/round/step'].split('/')
            _height = int(height_round_step[0])
            _round = int(height_round_step[1])

            self.current_round_consensus_state['round'] = _round
            self.current_round_consensus_state['height'] = _height
            self.current_round_consensus_state['step'] = int(height_round_step[2])

            consensus = data['round_state']['height_vote_set'][_round]

            _prevote_array = float(consensus['prevotes_bit_array'].split('=')[-1].strip()) * 100
            _precommits_array = float(consensus['precommits_bit_array'].split('=')[-1].strip()) * 100
            self.current_round_consensus_state['prevote_array'] = _prevote_array
            self.current_round_consensus_state['precommits_array'] = _precommits_array

            _online_precommit = 0
            _precommits_hex = {}
            for precommit in consensus['precommits']:
                if 'SIGNED_MSG_TYPE_PRECOMMIT(Precommit)' in precommit:
                    _online_precommit += 1
                    commit = precommit.split()[2]
                    hex = precommit.split()[0][-12:]
                    _precommits_hex[hex] = commit
                else:
                    continue
            self.current_round_consensus_state['hex_precommit'] = _precommits_hex
            
            _online_prevote = 0
            _prevotes_hex = {}
            for prevote in consensus['prevotes']:
                if 'SIGNED_MSG_TYPE_PREVOTE(Prevote)' in prevote:
                    _online_prevote += 1
                    vote = prevote.split()[2]
                    hex = prevote.split()[0][-12:]
                    _prevotes_hex[hex] = vote
                else:
                    continue
            self.current_round_consensus_state['hex_prevote'] = _prevotes_hex
            self.online_validators = _online_prevote if _online_prevote > _online_precommit else _online_precommit

            self.log_lines.append(f"Updated consensus state | {data['round_state']['height/round/step']}")

            return True
        except Exception as e:
            self.log_lines.append(f"An unexpected error occurred while processing consensus_state {e}")
            return
        
    def create_bar(self, label: str, value: float) -> str:
        bar_length = 40
        filled_length = int(value * bar_length // 100)
        bar = '█' * filled_length + '-' * (bar_length - filled_length)
        return f"[bold yellow]{label}[/bold yellow] {bar} {value:.1f}%"

    def generate_table(self) -> Table:
        table = Table(show_lines=False, expand=False, box=None)
        table.add_column("", justify="left")
        table.add_column("", justify="left")
        table.add_column("", justify="left")

        column_data = [[] for _ in range(self.num_columns)]
        for index, validator in enumerate(self.validators):
            column_index = index % self.num_columns
            moniker = validator['moniker'][:15].ljust(20)
            _hex_short = validator['hex'][:12]
            _voting_power = validator['vp']

            _prevoted = "[ V ]" if self.disable_emojis else "✅"
            _not_prevoted = "[ X ]" if self.disable_emojis else "❌"

            prevote_emoji = _prevoted if self.current_round_consensus_state['hex_prevote'].get(_hex_short) else _not_prevoted
            precommit_emoji = _prevoted if self.current_round_consensus_state['hex_precommit'].get(_hex_short) else _not_prevoted

            index_str = f"{index + 1}.".ljust(4)

            column_data[column_index].append(
                f"{index_str}{moniker}{prevote_emoji}{precommit_emoji.ljust(7)}{_voting_power:.1f}%"
            )

        max_rows = max(len(col) for col in column_data)
        for row_index in range(max_rows):
            row = [
                column_data[col_index][row_index] if row_index < len(column_data[col_index]) else ""
                for col_index in range(self.num_columns)
            ]
            table.add_row(*row)

        return table

    async def start(self):
        try:
            with Live(self.layout, refresh_per_second=self.refresh_per_second) as _:
                while True:

                    if not self.chain_id:
                        await self.fetch_chain_data()

                    if not hasattr(self, "_last_validators_update") or (asyncio.get_event_loop().time() - self._last_validators_update) >= 30:
                        upd_vals = await self.update_validators()
                        self._last_validators_update = asyncio.get_event_loop().time()

                    if not hasattr(self, "_last_consensus_update") or (asyncio.get_event_loop().time() - self._last_consensus_update) >= 1:
                        upd_cons = await self.update_current_consensus_state()
                        self._last_consensus_update = asyncio.get_event_loop().time()

                    if upd_vals or upd_cons:
                        self.layout["footer"].update(self.generate_table())

                        prevote_bar = self.create_bar("[ Prevotes ]", self.current_round_consensus_state['prevote_array'])
                        precommit_bar = self.create_bar("[Precommits]", self.current_round_consensus_state['precommits_array'])

                        votes_commits_renderable = f"{prevote_bar}\n{precommit_bar}"
                        votes_commits_panel = Panel(votes_commits_renderable, title="Prevotes & Precommits", border_style="yellow")

                        self.layout["header"]["votes_commits_bar"].update(votes_commits_panel)

                        network_info = (
                            f"[bold cyan]Node catching up:[/bold cyan] {self.catching_up}\n"
                            f"[bold cyan]Chain ID:[/bold cyan] {self.chain_id}\n"
                            f"[bold cyan]Height/Round/Step:[/bold cyan] {self.current_round_consensus_state['height']}/{self.current_round_consensus_state['round']}/{self.current_round_consensus_state['step']}\n"
                            f"[bold cyan]Online validators:[/bold cyan] {self.online_validators}\n"
                            f"[bold cyan]Offline validators:[/bold cyan] {len(self.validators) - self.online_validators}\n"
                            f"[bold cyan]Active validators:[/bold cyan] {len(self.validators)}\n"
                        )
                        if self.ugrade_plan:
                            network_info += f"[bold cyan]Upgrade plan:[/bold cyan] {self.ugrade_plan.get('name', 'N/A')} | Height: {self.ugrade_plan.get('height')}"

                        network_info_panel = Panel(network_info, title="Network Info", border_style="cyan")
                        self.layout["header"]["network_info"].update(network_info_panel)

                        log_renderable = "\n".join(self.log_lines)
                        log_panel = Panel(log_renderable, title="Logs", border_style="blue")
                        self.layout["header"]["logs"].update(log_panel)

                    await asyncio.sleep(1 / self.refresh_per_second)

        except asyncio.CancelledError:
            pass
        finally:
            self.console.clear()
