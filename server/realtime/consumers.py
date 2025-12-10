"""WebSocket consumers for real-time scan data."""

import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer


class ScanConsumer(AsyncJsonWebsocketConsumer):
    """WebSocket consumer for live scan data.

    Clients connect to:
    - ws/scans/ - receive all scans from all scanners
    - ws/scans/{scanner_id}/ - receive scans from specific scanner
    """

    async def connect(self):
        self.scanner_id = self.scope['url_route']['kwargs'].get('scanner_id')

        # Join appropriate group(s)
        if self.scanner_id:
            # Subscribe to specific scanner
            self.group_name = f'scans_{self.scanner_id}'
        else:
            # Subscribe to all scans
            self.group_name = 'scans_all'

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        # Also join the 'all' group if subscribed to specific scanner
        # so we can still receive broadcasts
        if self.scanner_id:
            await self.channel_layer.group_add(
                'scans_all',
                self.channel_name
            )

        await self.accept()

        # Send connection confirmation
        await self.send_json({
            'type': 'connected',
            'scanner_id': self.scanner_id,
            'group': self.group_name,
        })

    async def disconnect(self, close_code):
        # Leave group(s)
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )
        if self.scanner_id:
            await self.channel_layer.group_discard(
                'scans_all',
                self.channel_name
            )

    async def receive_json(self, content):
        """Handle incoming messages from client."""
        message_type = content.get('type')

        if message_type == 'ping':
            await self.send_json({'type': 'pong'})

        elif message_type == 'subscribe':
            # Client wants to subscribe to additional scanner
            scanner_id = content.get('scanner_id')
            if scanner_id:
                await self.channel_layer.group_add(
                    f'scans_{scanner_id}',
                    self.channel_name
                )
                await self.send_json({
                    'type': 'subscribed',
                    'scanner_id': scanner_id,
                })

        elif message_type == 'unsubscribe':
            scanner_id = content.get('scanner_id')
            if scanner_id:
                await self.channel_layer.group_discard(
                    f'scans_{scanner_id}',
                    self.channel_name
                )
                await self.send_json({
                    'type': 'unsubscribed',
                    'scanner_id': scanner_id,
                })

    async def scan_data(self, event):
        """Send scan data to WebSocket client."""
        await self.send_json({
            'type': 'scan',
            'data': event['data'],
        })

    async def scanner_status(self, event):
        """Send scanner status update to WebSocket client."""
        await self.send_json({
            'type': 'status',
            'data': event['data'],
        })

    async def scanner_config(self, event):
        """Send scanner config update to WebSocket client."""
        await self.send_json({
            'type': 'config',
            'data': event['data'],
        })
