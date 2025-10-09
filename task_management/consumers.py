"""
Centralized WebSocket consumers for task management across all ERP modules
"""
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
import logging

logger = logging.getLogger('ditapi_logger')


class TaskConsumer(AsyncWebsocketConsumer):
    """
    Centralized WebSocket consumer for task updates across all ERP modules
    """
    
    async def connect(self):
        self.user = self.scope["user"]
        self.user_id = str(self.user.id) if self.user.is_authenticated else None

        # Join general task updates group
        await self.channel_layer.group_add(
            'task_updates',
            self.channel_name
        )

        # Join user-specific group if authenticated
        if self.user_id:
            await self.channel_layer.group_add(
                f'task_user_{self.user_id}',
                self.channel_name
            )
        
        await self.accept()
        logger.info(f"WebSocket connected for user {self.user_id or 'anonymous'} to task_updates")

    async def disconnect(self, close_code):
        # Leave general task updates group
        await self.channel_layer.group_discard(
            'task_updates',
            self.channel_name
        )
        
        # Leave user-specific group
        if self.user_id:
            await self.channel_layer.group_discard(
                f'task_user_{self.user_id}',
                self.channel_name
            )
        
        logger.info(f"WebSocket disconnected for user {self.user_id or 'anonymous'}")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            task_id = data.get('task_id')
            module = data.get('module')

            if message_type == 'subscribe_task' and task_id:
                await self.channel_layer.group_add(
                    f'task_{task_id}',
                    self.channel_name
                )
                logger.info(f"User {self.user_id} subscribed to task {task_id}")
                
            elif message_type == 'unsubscribe_task' and task_id:
                await self.channel_layer.group_discard(
                    f'task_{task_id}',
                    self.channel_name
                )
                logger.info(f"User {self.user_id} unsubscribed from task {task_id}")
                
            elif message_type == 'subscribe_module' and module:
                await self.channel_layer.group_add(
                    f'task_module_{module}',
                    self.channel_name
                )
                logger.info(f"User {self.user_id} subscribed to module {module}")
                
            elif message_type == 'unsubscribe_module' and module:
                await self.channel_layer.group_discard(
                    f'task_module_{module}',
                    self.channel_name
                )
                logger.info(f"User {self.user_id} unsubscribed from module {module}")
                
            else:
                logger.warning(f"Received unknown message type or missing parameters: {data}")
                
        except json.JSONDecodeError:
            logger.error("Invalid JSON received")
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")

    # Task lifecycle events
    async def task_created(self, event):
        await self.send(text_data=json.dumps(event))

    async def task_started(self, event):
        await self.send(text_data=json.dumps(event))

    async def task_progress(self, event):
        await self.send(text_data=json.dumps(event))

    async def task_completed(self, event):
        await self.send(text_data=json.dumps(event))

    async def task_failed(self, event):
        await self.send(text_data=json.dumps(event))

    async def task_cancelled(self, event):
        await self.send(text_data=json.dumps(event))

    # Module-specific events (for backward compatibility)
    async def payroll_processing_started(self, event):
        await self.send(text_data=json.dumps(event))

    async def payroll_processing_progress(self, event):
        await self.send(text_data=json.dumps(event))

    async def payroll_processing_completed(self, event):
        await self.send(text_data=json.dumps(event))

    async def payslip_rerun_completed(self, event):
        await self.send(text_data=json.dumps(event))

    async def voucher_generated(self, event):
        await self.send(text_data=json.dumps(event))

    async def email_distribution_completed(self, event):
        await self.send(text_data=json.dumps(event))

    # Generic error handling
    async def error(self, event):
        await self.send(text_data=json.dumps(event))

    # System events
    async def system_notification(self, event):
        await self.send(text_data=json.dumps(event))

    async def maintenance_notification(self, event):
        await self.send(text_data=json.dumps(event))