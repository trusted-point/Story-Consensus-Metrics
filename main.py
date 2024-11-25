import asyncio
import multiprocessing
import signal
import traceback
from src.ws_monitor import WsConsensusMonitoring
from src.fetch_monitor import FetchConsensusMonitoring
from src.dashboard import ConsensusDashboard
from src.calls import AioHttpCalls
from utils.flags import flags
from utils.logger import logger


WS_EVENTS = [
    {"jsonrpc": "2.0", "method": "subscribe", "params": ["tm.event='Vote'"], "id": 1},
    {"jsonrpc": "2.0", "method": "subscribe", "params": ["tm.event='NewRoundStep'"], "id": 2},
    {"jsonrpc": "2.0", "method": "subscribe", "params": ["tm.event='ValidatorSetUpdates'"], "id": 3},
    {"jsonrpc": "2.0", "method": "subscribe", "params": ["tm.event='NewBlock'"], "id": 4}
]

class App:
    def __init__(self, rpc, ws, ws_events, target_height, post_target_check_blocks_num, save_all, no_save):
        self.rpc = rpc
        self.ws = ws
        self.ws_events = ws_events
        self.target_height = target_height
        self.post_target_check_blocks_num = post_target_check_blocks_num
        self.save_all = save_all
        self.no_save = no_save
        self.check_blocks_list = []

        # Parse WebSocket URL if not provided
        if not self.ws:
            logger.info(f"Websocket is not provided. Trying to parse from {self.rpc}")
            if 'http' in self.rpc:
                ws_url = self.rpc.replace('http', 'ws')
            elif 'https' in self.rpc:
                ws_url = self.rpc.replace('https', 'wss')
            else:
                logger.error(f"Failed to parse ws/wss endpoint from {self.rpc}. Ensure RPC URL format is correct. Consider providing websocket URL with --ws flag")
                exit()
            self.ws = ws_url + '/websocket'
            logger.info(f"Using websocket endpoint: {self.ws}")

        # Generate list of blocks to save signatures post target height
        if self.target_height and self.post_target_check_blocks_num:
            for i in range(int(self.post_target_check_blocks_num) + 1):
                self.check_blocks_list.append(str(int(self.target_height) + i))

        asyncio.run(self.check_rpc_connection())

    async def check_rpc_connection(self):
        """Checks the RPC connection to ensure it is online."""
        async with AioHttpCalls() as session:
            rpc_status = await session.get_rpc_status()

        if not rpc_status:
            logger.error(f"Failed to connect to {self.rpc}. Ensure the RPC URL format is correct and the node is online.")
            exit()

        catching_up = rpc_status['sync_info']['catching_up']
        latest_block_height = rpc_status['sync_info']['latest_block_height']
        latest_block_time = rpc_status['sync_info']['latest_block_time']
        chain_id = rpc_status['node_info']['network']

        logger.info(f"""
---------------------RPC STATUS----------------------
URL: {self.rpc}
CHAIN_ID: {chain_id}
CATCHING_UP: {catching_up}
LATEST BLOCK: {latest_block_height} | {latest_block_time}
------------------------------------------------------
""")

        if catching_up:
            logger.warning(f"Provided RPC node is catching up. Check {self.rpc}/status. Ignoring.")

    async def ws_monitor_task(self):
        try:
            ws_monitor = WsConsensusMonitoring(
                ws=self.ws,
                ws_events=self.ws_events,
                target_height=self.target_height,
                post_target_check_blocks=self.check_blocks_list,
                save_all=self.save_all,
                no_save=self.no_save
            )
            await ws_monitor.start()
        except asyncio.CancelledError:
            logger.info("ws_monitor_task interrupted.")

    async def fetch_monitor_task(self):
        try:
            fetch_monitor = FetchConsensusMonitoring(
                target_height=self.target_height,
                post_target_check_blocks=self.check_blocks_list,
                save_all=self.save_all,
                no_save=self.no_save,
                sleep_time_between=0
            )
            await fetch_monitor.start()
        except asyncio.CancelledError:
            logger.info("fetch_monitor_task interrupted.")

    def start_app(self):
        """Starts the main application."""

        ws_process = multiprocessing.Process(target=self.run_in_process, args=(self.ws_monitor_task,))
        fetch_process = multiprocessing.Process(target=self.run_in_process, args=(self.fetch_monitor_task,))

        ws_process.start()
        fetch_process.start()

        try:
            ws_process.join()
            fetch_process.join()

        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received. Terminating subprocesses...")
            ws_process.terminate()
            fetch_process.terminate()

            ws_process.join()
            fetch_process.join()
        finally:
            logger.info("------------------------------------------------------")
            logger.info("Exiting main process")

    def run_in_process(self, func):
        """Run an asyncio coroutine in a subprocess with cancellation handling."""
        try:
            signal.signal(signal.SIGINT, self.signal_handler)
            if asyncio.iscoroutinefunction(func):
                asyncio.run(func())
            else:
                func()
        except asyncio.CancelledError:
            logger.info(f"{func.__name__} cancelled.")
        except KeyboardInterrupt:
            logger.info(f"Terminating {func.__name__}.")
        except Exception as e:
            logger.error(f"Error in subprocess: {e}")
            traceback.print_exc()
        finally:
            logger.info(f"{func.__name__} finished.")

    def signal_handler(self, signum, frame):
        logger.info("------------------------------------------------------")
        logger.info("Signal received: terminating process gracefully...")
        raise KeyboardInterrupt()

async def dashboard(dashboard_refresh_per_second, dashboard_disable_emojis):
    try:
        dashboard = ConsensusDashboard(refresh_per_second=dashboard_refresh_per_second, disable_emojis=dashboard_disable_emojis)
        await dashboard.start()
    except asyncio.CancelledError:
        logger.info("Dashboard interrupted.")

if __name__ == "__main__":
    if not flags.dashboard_only:
        app = App(
            rpc=flags.rpc,
            ws=flags.ws,
            ws_events=WS_EVENTS,
            target_height=flags.target_height,
            post_target_check_blocks_num=flags.post_target_check_blocks_num,
            save_all=flags.save_all,
            no_save=flags.no_save,
        )
        app.start_app()
    else:
        asyncio.run(dashboard(
            dashboard_refresh_per_second = flags.dashboard_refresh_per_second,
            dashboard_disable_emojis = flags.dashboard_disable_emojis
        ))
