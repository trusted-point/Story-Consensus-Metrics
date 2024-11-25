import argparse
from argparse import Namespace

def str_to_bool(value: str) -> bool:
    if value.lower() in ['true', '1', 'yes']:
        return True
    elif value.lower() in ['false', '0', 'no']:
        return False
    else:
        raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")

def validate_log_level(value: str) -> str:
    levels = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}
    if value.upper() in levels:
        return value.upper()
    else:
        raise argparse.ArgumentTypeError(f"Invalid log level: {value}")

def parse_args() -> Namespace:
    parser = argparse.ArgumentParser(description="Global arguments for the application", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--log_lvl', default='INFO', type=validate_log_level, help='Set the logging level [DEBUG, INFO, WARNING, ERROR]')
    parser.add_argument('--log_path', type=str, default='logs/logs.log', help='Path to the log file')

    parser.add_argument(
        '--log_save',
        action='store_true',
        help='To save logs', default=True
    )

    parser.add_argument('--rpc', type=str, help='RPC server http/s', required=True)
    parser.add_argument('--ws', type=str, help='Websocket endpoint', required=False)
    parser.add_argument('--target_height', type=str, help='Block height to snapshot consensus prevotes & precommits', required=False)
    parser.add_argument('--post_target_check_blocks_num', type=str, help='How many blocks to keep snapshoting consensus prevotes & precommits after target_height is reached', required=False, default='10')

    parser.add_argument(
        '--save_all',
        action='store_true',
        help='Save all validators metrics for all blocks (signatures, prevotes, precommits etc.). Making target_height argument useless'
    )

    parser.add_argument(
        '--no_save',
        action='store_true',
        help='Do not save any metrics (signatures, prevotes, precommits etc.)'
    )

    parser.add_argument(
        '--dashboard_only',
        action='store_true',
        help='To open real-time consensus dashoard. No data will be saved no matter what flags and args you set'
    )
    
    parser.add_argument(
        '--dashboard_disable_emojis',
        action='store_true',
        help='Disable emojis in dashboard output (use in case emojis break the table)'
    )
    
    parser.add_argument('--dashboard_refresh_per_second', type=int, help='Refresh rate of the table', required=False, default=1)

    args = parser.parse_args()

    if not args.dashboard_only:
        if args.no_save:
            if args.save_all or args.target_height:
                parser.error("Arguments --save_all and --target_height cannot be used with --no_save.")
        elif not args.save_all and not args.target_height:
            parser.error("Argument --target_height is required unless --save_all or --no_save is set.")

    return args
flags = parse_args()
