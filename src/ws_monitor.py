import traceback
import os
import json 
from typing import List
from utils.logger import logger
from src.websocket import websocket_connect
from src.calls import AioHttpCalls
from src.converter import pubkey_to_consensus_hex

class WsConsensusMonitoring:
    def __init__(self,
                 ws: str,
                 ws_events: List[dict],
                 post_target_check_blocks: List[str],
                 target_height: str,
                 save_all: bool,
                 no_save: bool
                 ):
        self.target_height = target_height
        self.save_all = save_all
        self.no_save = no_save
        
        self.ws_events = ws_events
        self.check_blocks_list = post_target_check_blocks
        self.ws = ws
        self.validators = {}

    async def start(self):

        logger.info("------------------------------------------------------")
        logger.info("Fetching validators")
        await self.update_validators()

        if not self.validators:
            logger.error("Failed to fetch validators. Exiting")
            exit(0)

        await websocket_connect(ws=self.ws, events=self.ws_events, callback=self.process_new_event_callback)

    async def process_new_event_callback(self, data):
        try:
            event_data = data['result']['data']['value']
            event = data['result']['query'].split('=')[-1].strip("'")
            
            if event == 'Vote':
                await self.process_new_vote_entry(event_data=event_data)

            elif event == 'NewRoundStep':
                _step = event_data['step']
                _height = event_data['height']
                _round = event_data['round']
                logger.debug(f"{_step.ljust(29)} | Round: {_round}   | Height: {_height}")

            elif event == 'ValidatorSetUpdates':
                logger.info(f"{event} event received")
                await self.update_validators()

            elif event == 'NewBlock':
                await self.process_new_block_entry(event_data=event_data)
            
            else:
                logger.error(f"Received unknown event {event}. Skipping")

        except Exception as e:
            logger.error(f"An error occurred while parsing data {data}: {e}")
            traceback.print_exc()

    async def process_new_vote_entry(self, event_data):
        _height = event_data['Vote']['height']
        _round = str(event_data['Vote']['round'])
        _timestamp = event_data['Vote']['timestamp']
        _hash = event_data['Vote']['block_id']['hash']
        _vote_number_type = event_data['Vote']['type']
        _validator_hex = event_data['Vote']['validator_address']
        _signature = event_data['Vote']['signature']

        # CHECK IF EVENT IS KNOWN
        if _vote_number_type == 1:
            _vote_type = 'Prevote'
        elif _vote_number_type == 2:
            _vote_type = 'Precommit'
        else:
            logger.error(f"Received unknown vote type number {_vote_number_type}. Skipping")
            return
        
        # CHECK IF VALIDATOR EXISTS
        _validator_info = self.validators.get(_validator_hex)
        if not _validator_info:
            await self.update_validators()
            _validator_info = self.validators.get(_validator_hex)
        if not _validator_info:
            logger.error(f"Validator {_validator_hex} not found even after update")
            return

        if not self.no_save and (_height == self.target_height or self.save_all or _height in self.check_blocks_list):
            logger.debug(f"{f'Saving {_vote_type}'.ljust(18)}{_validator_info['moniker'][:11].ljust(12)}| Round: {_round}   | Height: {_height}")

            file_path = f"result/{_height}/ws_votes.json"

            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    try:
                        state = json.load(f)
                        logger.debug(f"Loaded {file_path} state")
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to load {file_path} {e}")
                        return
            else:
                state = {
                    'height': _height,
                    'rounds': {}
                    }
            state['height'] = _height
            

            if _round not in state['rounds']:
                state['rounds'][_round] = {
                    'Prevote': {},
                    'Precommit': {}
                }

            event = {
                'timestamp': _timestamp,
                'hash': _hash,
                'signature': _signature
            }
            if _validator_hex not in state['rounds'][_round][_vote_type]:
                state['rounds'][_round][_vote_type][_validator_hex] = []
            
            if event not in state['rounds'][_round][_vote_type][_validator_hex]:
                state['rounds'][_round][_vote_type][_validator_hex].append(event)

            os.makedirs(f"result/{_height}", exist_ok=True)
            with open(file_path, 'w') as f:
                json.dump(state, f, indent=4)

            logger.debug(f"{f'Saved {_vote_type}'.ljust(18)}{_validator_info['moniker'][:11].ljust(12)}| Round: {_round}   | Height: {_height}")
        else:
            logger.debug(f"Skipping {f'{_vote_type}'.ljust(18)}{_validator_info['moniker'][:11].ljust(12)}| Round: {_round}   | Height: {str(_height).ljust(7)} | Target: {self.target_height}")


    async def process_new_block_entry(self, event_data):

        _height = event_data['block']['last_commit']['height']
        _proposer = event_data['block']['header']['proposer_address']
        signatures = event_data['block']['last_commit']['signatures']

        parsed_signatures = {}
        for item in signatures:
            validator_address = item.get('validator_address')
            if validator_address:
                parsed_signatures[validator_address] = {
                    'timestamp': item['timestamp'],
                    'signature': item['signature']
                }

        _signed_validators = {}
        _missed_validators = {}

        for validator in self.validators:
            if validator in parsed_signatures:
                _signed_validators[validator] = self.validators[validator]
                _signed_validators[validator]['signature'] = parsed_signatures[validator]
            else:
                _missed_validators[validator] = self.validators[validator]
                _missed_validators[validator]['signature'] = None

        _total_signed = len(_signed_validators)
        _total_missed = len(_missed_validators)

        data = {
            'height': _height,
            'total_signed': _total_signed,
            'total_missed': _total_missed,
            'proposer': _proposer,
            'signed_validators': _signed_validators,
            'missed_validators': _missed_validators,
        }

        logger.info(f"{f'Finalized #{_height}'.ljust(19)}| Signatures: {f'{_total_signed}'.ljust(5)}/ {f'{len(self.validators)}'.ljust(5)}| Proposer: {_proposer} | Missing signatures: {[val['moniker'] for _,val in _missed_validators.items()]}")
        
        if not self.no_save and (_height == self.target_height or self.save_all or _height in self.check_blocks_list):

            file_path = f"result/{_height}/ws_signatures.json"
            os.makedirs(f"result/{_height}", exist_ok=True)
            if not os.path.exists(file_path):
                with open(file_path, 'w') as f:
                    json.dump(data, f, indent=4)

                logger.debug(f"Saved #{_height} signatures")
        else:
            logger.info(f"Skipping saving signatures for block #{_height}")

    async def update_validators(self):
        try:
            async with AioHttpCalls() as session:
                data = await session.get_validators(status='BOND_STATUS_BONDED')
                if data:
                    validators = {}
                    for validator  in data:
                        _consensus_pub_key = validator['consensus_pubkey']['key']
                        _moniker = validator.get('description',{}).get('moniker', 'N/A')
                        _valoper = validator.get('operator_address', '')

                        _hex = pubkey_to_consensus_hex(pub_key=_consensus_pub_key)
                        validators[_hex] = {
                            'moniker': _moniker,
                            'hex': _hex,
                            'valoper': _valoper,
                            'consensus_pubkey': _consensus_pub_key,
                            }
                
                    self.validators = validators
                    logger.info("------------------------------------------------------")
                    logger.info(f"Updated validators | Current active set: {len(self.validators)}")

        except Exception as e:
            logger.error(f"An error occurred while updating validators: {e}")
            traceback.print_exc()