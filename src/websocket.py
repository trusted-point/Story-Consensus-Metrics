import json
import websockets
import asyncio
import socket
from typing import List
from utils.logger import logger

async def websocket_connect(ws: str, events: List, callback):
    while True:
        try:
            async with websockets.connect(ws, max_size=6250000) as websocket:
                for event in events:
                    logger.info(f"Connecting to WebSocket: {ws.ljust(15)}. Event: {event}")
                    await websocket.send(json.dumps(event))
                
                while True:
                    try:
                        response = await asyncio.wait_for(websocket.recv(), timeout=60.0)
                        data = json.loads(response)
                        if data.get('result') and 'query' in data['result']:
                            await callback(data)
                        else:
                            if data.get('error'):
                                logger.error(f"Unexpected message received from WebSocket {ws.ljust(15)}: {data}")
                                logger.info(f"Reconnecting due to unexpected message from WebSocket {ws.ljust(15)}.")
                                break

                    except asyncio.TimeoutError:
                        logger.error(f"No message received for 60+ seconds from WebSocket: {ws.ljust(15)}.")
                        await asyncio.sleep(1)

            await asyncio.sleep(1)
        except websockets.ConnectionClosed as e:
            logger.error(f"Connection to WebSocket lost: {ws.ljust(15)}. Reconnecting.")
        except socket.gaierror as e:
            logger.error(f"Network error during DNS lookup. Could not resolve WebSocket: {ws.ljust(15)}. Trying again in 5 seconds.")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"An unexpected error occurred in WebSocket: {ws.ljust(15)}. Reconnecting. {e}")
