import traceback
import os
import json
import asyncio
from typing import List
from utils.logger import logger
from src.calls import AioHttpCalls
from src.converter import pubkey_to_consensus_hex

class FetchConsensusMonitoring:
    def __init__(self,
                 post_target_check_blocks: List[str],
                 target_height: str,
                 save_all: bool,
                 no_save: bool,
                 sleep_time_between: int
                 ):
        self.sleep_time_between = sleep_time_between
        self.target_height = target_height
        self.save_all = save_all
        self.no_save = no_save
        self.check_blocks_list = post_target_check_blocks

        self.validators = {}

        self.current_round_consensus_state = {
            'height': -1,
            'round': -1,
            'step': -1,
            'validators': {},
            'prevote_array': 0.0,
            'precommits_array': 0.0,
        }

        self.all_rounds_consensus_state = {}

    async def update_validators(self):
        try:
            async with AioHttpCalls() as session:
                data = await session.get_validators(status='BOND_STATUS_BONDED')
                if data:
                    validators = {}
                    for validator  in data:
                        _consensus_pub_key = validator['consensus_pubkey']['key']
                        if not _consensus_pub_key:
                            logger.warning(f'Skipping validator due too missing consensus_pub_key: {validator}')
                            continue
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

    async def start(self):
        logger.info("------------------------------------------------------")
        logger.info("Fetching validators")
        await self.update_validators()

        if not self.validators:
            logger.error("Failed to fetch validators. Exiting")
            exit()

        await self.update_current_consensus_state()

    async def update_current_consensus_state(self):
        while True:
            try:
                async with AioHttpCalls() as session:
                    consensus = await session .get_consensus_state()
                if not consensus:
                    logger.error(f"Failed to fetch consensus_state. Retrying")
                    continue

                self.all_rounds_consensus_state = consensus
                height_round_step = consensus['round_state']['height/round/step'].split('/')
                _height = int(height_round_step[0])
                _round = int(height_round_step[1])

                if not self.no_save and (_height == self.target_height or self.save_all or _height in self.check_blocks_list):
                    file_path = f"result/{_height}/fetch_votes.json"
                    os.makedirs(f"result/{_height}", exist_ok=True)
                    with open(file_path, 'w') as f:
                        json.dump(self.all_rounds_consensus_state, f, indent=4)
                    logger.debug(f"Saved fetched {file_path}")

                self.current_round_consensus_state['round'] = _round
                self.current_round_consensus_state['height'] = _height
                self.current_round_consensus_state['step'] = int(height_round_step[2])

                consensus = consensus['round_state']['height_vote_set'][_round]

                _prevote_array = float(consensus['prevotes_bit_array'].split('=')[-1].strip()) * 100
                _precommits_array = float(consensus['precommits_bit_array'].split('=')[-1].strip()) * 100
                self.current_round_consensus_state['prevote_array'] = _prevote_array
                self.current_round_consensus_state['precommits_array'] = _precommits_array

                _precommits_hex = {}
                for precommit in consensus['precommits']:
                    commit = precommit.split()[2] if 'SIGNED_MSG_TYPE_PRECOMMIT(Precommit)' in precommit else 'nil-Vote'
                    hex = precommit.split()[0][-12:] if 'SIGNED_MSG_TYPE_PRECOMMIT(Precommit)' in precommit else 'nil-Vote'
                    _precommits_hex[hex] = commit

                _prevotes_hex = {}
                for prevote in consensus['prevotes']:
                    vote = prevote.split()[2] if 'SIGNED_MSG_TYPE_PREVOTE(Prevote)' in prevote else 'nil-Vote'
                    hex = prevote.split()[0][-12:] if 'SIGNED_MSG_TYPE_PREVOTE(Prevote)' in prevote else 'nil-Vote'
                    _prevotes_hex[hex] = vote

                for _hex, validator in self.validators.items():
                    _hex_short = hex[:12]
                    _prevote = _prevotes_hex.get(_hex_short, 'nil-Vote')
                    _precommit = _precommits_hex.get(_hex_short, 'nil-Vote')

                    if _hex not in self.current_round_consensus_state['validators']:
                        self.current_round_consensus_state['validators'][_hex] = validator
                    self.current_round_consensus_state['validators'][_hex]['prevote'] = _prevote
                    self.current_round_consensus_state['validators'][_hex]['precommit'] = _precommit

                if self.sleep_time_between:
                    await asyncio.sleep(self.self.refresh_rate)

            except Exception as e:
                logger.error(f"An unexpected error occurred while processing consensus_state: {consensus} {e}")
                traceback.print_exc()