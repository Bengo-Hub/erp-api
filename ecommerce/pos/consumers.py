import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone

class POSConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Join POS group
        await self.channel_layer.group_add(
            'pos_updates',
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        # Leave POS group
        await self.channel_layer.group_discard(
            'pos_updates',
            self.channel_name
        )

    async def receive(self, text_data):
        # Handle incoming messages if needed
        pass

    async def sale_created(self, event):
        # Send sale created event to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'sale_created',
            'sale': event['sale']
        }))

    async def sale_updated(self, event):
        # Send sale updated event to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'sale_updated',
            'sale': event['sale']
        }))

    async def register_status_changed(self, event):
        # Send register status change event to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'register_status_changed',
            'register': event['register']
        }))

    async def payment_processed(self, event):
        # Send payment processed event to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'payment_processed',
            'payment': event['payment']
        }))

    async def stock_updated(self, event):
        # Send stock update event to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'stock_updated',
            'product': event['product']
        }))

    async def error_occurred(self, event):
        # Send error event to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'error',
            'message': event['message']
        })) 