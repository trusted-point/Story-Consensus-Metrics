import aiohttp
import traceback
import base64
import json
from typing import Literal
from utils.logger import logger
from utils.flags import flags
from src.protobuf.cosmos.base.query.v1beta1.pagination_pb2 import PageRequest
from src.protobuf.cosmos.staking.v1beta1.query_pb2 import (
    QueryValidatorsRequest,
    QueryValidatorsResponse,
)
from src.protobuf.cosmos.upgrade.v1beta1.query_pb2 import (
    QueryCurrentPlanRequest,
    QueryCurrentPlanResponse,
)

from google.protobuf.json_format import MessageToDict
from src.protobuf.cosmos.crypto.ed25519.keys_pb2 import PubKey as ed25519_pub_key
from src.protobuf.cosmos.crypto.secp256k1.keys_pb2 import PubKey as secp256k1_pub_key
from src.protobuf.cosmos.crypto.secp256r1.keys_pb2 import PubKey as secp256r1_pub_key

class AioHttpCalls:

    def __init__(self, timeout = 10):
        self.rpc = flags.rpc
        self.timeout = timeout
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.session.close()
    
    async def handle_request(self, url, callback):
        try:
            async with self.session.get(url, timeout=self.timeout) as response:
                
                if response.status == 200:
                    return await callback(response.json())
                else:
                    logger.error(f"Request to {url} failed with status code {response.status}")
                    return None
                
        except aiohttp.ClientError as e:
            logger.error(f"Issue with making request to {url}: {e}")
            return None
        
        except TimeoutError as e:
            logger.error(f"Issue with making request to {url}. TimeoutError: {e}")
            return None

        except Exception as e:
            logger.error(f"An unexpected error occurred while making request t {url}: {e}")
            traceback.print_exc()
            return None


    async def handle_abci_request(self, callback, hex_data, path, prove=False) -> bytes:
        try:
            payload = {
                "jsonrpc": "2.0",
                "method": "abci_query",
                "params": {
                    "path": path,
                    "data": hex_data,
                    "prove": prove
                },
                "id": -1
            }
            headers = {"Content-Type": "application/json", "Accept": "application/json"}

            async with self.session.get(self.rpc, timeout=self.timeout, headers=headers, data=json.dumps(payload)) as response:
                    
                if response.status == 200:
                    response_json = await response.json()

                    code = response_json.get('result', {}).get('response', {}).get('code', -1)
                    abci_error_log = response_json.get('result', {}).get('response', {}).get('log', '')
                    
                    if code == 0:
                        response_value = response_json.get('result', {}).get('response', {}).get('value', '')
                        if response_value:
                            return await callback(base64.b64decode(response_value))
                        else:
                            logger.error(f"ABCI returned 0 code, but with empty response [{payload}]")
                    else:
                        logger.error(f"ABCI retuned {code} code. Payload: {payload}. ABCI log: {abci_error_log}")
                else:
                    logger.error(f"Request to {self.rpc} failed with status code {response.status}. Payload: {payload}")
                    return None
                
        except aiohttp.ClientError as e:
            logger.error(f"Issue with making request to {self.rpc}. Payload: {payload}. {e}")
            return None
        
        except TimeoutError as e:
            logger.error(f"Issue with making request to {self.rpc}. Payload: {payload}. TimeoutError: {e}")
            return None

        except Exception as e:
            logger.error(f"An unexpected error occurred while making request to {self.rpc}: {e}")
            traceback.print_exc()
            return None

    def get_pagination_params(self, key, offset, limit, count_total, reverse) -> PageRequest:
        if key:
            try:
                key_bytes = base64.b64decode(key)
            except (TypeError, base64.binascii.Error) as e:
                logger.error(f"Invalid base64 encoding for pagination key: {e}")
                key_bytes = b''
        else:
            key_bytes = b''
        return PageRequest(key=key_bytes, offset=offset, limit=limit, count_total=count_total, reverse=reverse)

    async def get_validators(self, status: Literal["BOND_STATUS_BONDED", "BOND_STATUS_UNBONDED", "BOND_STATUS_UNBONDING", None],
                                    limit: int = 1000,
                                    offset = None,
                                    count_total = False,
                                    reverse = False):

        pagination = self.get_pagination_params(key=None, offset=offset, limit=limit, count_total=count_total, reverse=reverse)
        query = QueryValidatorsRequest(status=status, pagination=pagination)
        serialized_query = query.SerializeToString()
        hex_data = serialized_query.hex()

        async def process_response(response):
            query_response = QueryValidatorsResponse()
            query_response.ParseFromString(response)
            validators = MessageToDict(query_response, preserving_proto_field_name=True)
            return validators['validators']

        return await self.handle_abci_request(callback=process_response, hex_data=hex_data, path='/cosmos.staking.v1beta1.Query/Validators')

    async def get_rpc_status(self):
        url = f"{self.rpc}/status"

        async def process_response(response):
            data = await response
            return data['result']

        return await self.handle_request(url, process_response)

    async def get_consensus_state(self):
        url = f"{self.rpc}/consensus_state"

        async def process_response(response):
            data = await response
            return data['result']

        return await self.handle_request(url, process_response)

    async def get_upgrade_info(self):

        query = QueryCurrentPlanRequest()
        serialized_query = query.SerializeToString()
        hex_data = serialized_query.hex()

        async def process_response(response):
            query_response = QueryCurrentPlanResponse()
            query_response.ParseFromString(response)
            data = MessageToDict(query_response, preserving_proto_field_name=True)
            return data
        return await self.handle_abci_request(callback=process_response, hex_data=hex_data, path='/cosmos.upgrade.v1beta1.Query/CurrentPlan')
    