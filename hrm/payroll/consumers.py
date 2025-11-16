import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone

# Lazy import to avoid AppRegistryNotReady errors during ASGI initialization
def _get_user_model():
    """Lazy import of User model."""
    from django.contrib.auth import get_user_model
    return get_user_model()

class PayrollConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Get user from scope (already set by middleware)
        self.user = self.scope["user"]
        
        if self.user.is_authenticated:
            # Join user-specific group for personalized updates
            await self.channel_layer.group_add(
                f'payroll_user_{self.user.id}',
                self.channel_name
            )
            
            # Join general payroll group for system-wide updates
            await self.channel_layer.group_add(
                'payroll_updates',
                self.channel_name
            )
            
            await self.accept()
        else:
            await self.close()

    async def disconnect(self, close_code):
        if hasattr(self, 'user') and self.user.is_authenticated:
            # Leave user-specific group
            await self.channel_layer.group_discard(
                f'payroll_user_{self.user.id}',
                self.channel_name
            )
            
            # Leave general payroll group
            await self.channel_layer.group_discard(
                'payroll_updates',
                self.channel_name
            )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'subscribe_task':
                # Subscribe to specific task updates
                task_id = data.get('task_id')
                if task_id:
                    await self.channel_layer.group_add(
                        f'payroll_task_{task_id}',
                        self.channel_name
                    )
                    
            elif message_type == 'unsubscribe_task':
                # Unsubscribe from specific task updates
                task_id = data.get('task_id')
                if task_id:
                    await self.channel_layer.group_discard(
                        f'payroll_task_{task_id}',
                        self.channel_name
                    )
                    
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))

    # Task status events
    async def task_started(self, event):
        """Send task started event to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'task_started',
            'task_id': event['task_id'],
            'task_type': event['task_type'],
            'message': event['message'],
            'timestamp': event['timestamp']
        }))

    async def task_progress(self, event):
        """Send task progress event to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'task_progress',
            'task_id': event['task_id'],
            'task_type': event['task_type'],
            'progress': event['progress'],
            'current': event['current'],
            'total': event['total'],
            'message': event['message'],
            'timestamp': event['timestamp']
        }))

    async def task_completed(self, event):
        """Send task completed event to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'task_completed',
            'task_id': event['task_id'],
            'task_type': event['task_type'],
            'result': event['result'],
            'message': event['message'],
            'timestamp': event['timestamp']
        }))

    async def task_failed(self, event):
        """Send task failed event to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'task_failed',
            'task_id': event['task_id'],
            'task_type': event['task_type'],
            'error': event['error'],
            'message': event['message'],
            'timestamp': event['timestamp']
        }))

    # Payroll-specific events
    async def payroll_processing_started(self, event):
        """Send payroll processing started event"""
        await self.send(text_data=json.dumps({
            'type': 'payroll_processing_started',
            'task_id': event['task_id'],
            'employee_count': event['employee_count'],
            'payment_period': event['payment_period'],
            'message': event['message'],
            'timestamp': event['timestamp']
        }))

    async def payroll_processing_progress(self, event):
        """Send payroll processing progress event"""
        await self.send(text_data=json.dumps({
            'type': 'payroll_processing_progress',
            'task_id': event['task_id'],
            'processed': event['processed'],
            'total': event['total'],
            'current_employee': event['current_employee'],
            'message': event['message'],
            'timestamp': event['timestamp']
        }))

    async def payroll_processing_completed(self, event):
        """Send payroll processing completed event"""
        await self.send(text_data=json.dumps({
            'type': 'payroll_processing_completed',
            'task_id': event['task_id'],
            'result': event['result'],
            'payslips_created': event['payslips_created'],
            'message': event['message'],
            'timestamp': event['timestamp']
        }))

    async def payslip_rerun_completed(self, event):
        """Send payslip rerun completed event"""
        await self.send(text_data=json.dumps({
            'type': 'payslip_rerun_completed',
            'task_id': event['task_id'],
            'payslip_id': event['payslip_id'],
            'result': event['result'],
            'message': event['message'],
            'timestamp': event['timestamp']
        }))

    async def voucher_generated(self, event):
        """Send voucher generated event"""
        await self.send(text_data=json.dumps({
            'type': 'voucher_generated',
            'task_id': event['task_id'],
            'voucher_type': event['voucher_type'],
            'employee_id': event['employee_id'],
            'result': event['result'],
            'message': event['message'],
            'timestamp': event['timestamp']
        }))

    async def email_distribution_completed(self, event):
        """Send email distribution completed event"""
        await self.send(text_data=json.dumps({
            'type': 'email_distribution_completed',
            'task_id': event['task_id'],
            'emails_sent': event['emails_sent'],
            'total_emails': event['total_emails'],
            'message': event['message'],
            'timestamp': event['timestamp']
        }))

    async def error_occurred(self, event):
        """Send error event to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'error',
            'task_id': event.get('task_id'),
            'message': event['message'],
            'error_details': event.get('error_details'),
            'timestamp': event['timestamp']
        }))
