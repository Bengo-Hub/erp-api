"""
Enhanced Background Job Management System for Bengo ERP.
Provides advanced job queuing, threading, and monitoring capabilities.
"""
import logging
import threading
import queue
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps
from typing import Dict, List, Any, Callable, Optional
from datetime import datetime, timedelta
from django.core.cache import cache
from django.conf import settings
from celery import shared_task, current_task
from celery.result import AsyncResult
import psutil

logger = logging.getLogger('ditapi_logger')

class JobQueue:
    """Advanced job queue with threading support"""
    
    def __init__(self, max_workers=10, queue_size=1000):
        self.max_workers = max_workers
        self.queue = queue.Queue(maxsize=queue_size)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.active_jobs = {}
        self.job_history = []
        self.stats = {
            'total_jobs': 0,
            'completed_jobs': 0,
            'failed_jobs': 0,
            'active_jobs': 0
        }
    
    def submit_job(self, job_func: Callable, *args, **kwargs) -> str:
        """Submit a job to the queue"""
        job_id = f"job_{int(time.time() * 1000)}"
        
        job_data = {
            'id': job_id,
            'function': job_func.__name__,
            'args': args,
            'kwargs': kwargs,
            'status': 'queued',
            'submitted_at': datetime.now(),
            'priority': kwargs.pop('priority', 'normal')
        }
        
        self.queue.put((job_id, job_func, args, kwargs))
        self.active_jobs[job_id] = job_data
        self.stats['total_jobs'] += 1
        self.stats['active_jobs'] += 1
        
        # Start processing if not already running
        if not hasattr(self, '_processing_thread') or not self._processing_thread.is_alive():
            self._processing_thread = threading.Thread(target=self._process_queue, daemon=True)
            self._processing_thread.start()
        
        return job_id
    
    def _process_queue(self):
        """Process jobs from the queue"""
        while True:
            try:
                job_id, job_func, args, kwargs = self.queue.get(timeout=1)
                
                # Update job status
                self.active_jobs[job_id]['status'] = 'running'
                self.active_jobs[job_id]['started_at'] = datetime.now()
                
                # Execute job
                try:
                    result = job_func(*args, **kwargs)
                    self.active_jobs[job_id]['status'] = 'completed'
                    self.active_jobs[job_id]['result'] = result
                    self.stats['completed_jobs'] += 1
                except Exception as e:
                    self.active_jobs[job_id]['status'] = 'failed'
                    self.active_jobs[job_id]['error'] = str(e)
                    self.stats['failed_jobs'] += 1
                    logger.error(f"Job {job_id} failed: {str(e)}")
                finally:
                    self.active_jobs[job_id]['completed_at'] = datetime.now()
                    self.stats['active_jobs'] -= 1
                    
                    # Move to history
                    self.job_history.append(self.active_jobs.pop(job_id))
                    
                    # Keep only last 1000 jobs in history
                    if len(self.job_history) > 1000:
                        self.job_history = self.job_history[-1000:]
                
                self.queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error processing job queue: {str(e)}")
                time.sleep(1)
    
    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get status of a specific job"""
        if job_id in self.active_jobs:
            return self.active_jobs[job_id]
        
        for job in self.job_history:
            if job['id'] == job_id:
                return job
        
        return {'error': 'Job not found'}
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        return {
            **self.stats,
            'queue_size': self.queue.qsize(),
            'active_jobs_count': len(self.active_jobs),
            'history_size': len(self.job_history)
        }

class ThreadedTaskManager:
    """Manager for threaded tasks with monitoring"""
    
    def __init__(self):
        self.thread_pools = {}
        self.task_monitors = {}
    
    def create_thread_pool(self, name: str, max_workers: int = 5) -> ThreadPoolExecutor:
        """Create a named thread pool"""
        if name not in self.thread_pools:
            self.thread_pools[name] = ThreadPoolExecutor(max_workers=max_workers)
            self.task_monitors[name] = {
                'active_tasks': 0,
                'completed_tasks': 0,
                'failed_tasks': 0,
                'total_tasks': 0
            }
        return self.thread_pools[name]
    
    def submit_task(self, pool_name: str, task_func: Callable, *args, **kwargs) -> str:
        """Submit a task to a specific thread pool"""
        if pool_name not in self.thread_pools:
            self.create_thread_pool(pool_name)
        
        pool = self.thread_pools[pool_name]
        task_id = f"{pool_name}_task_{int(time.time() * 1000)}"
        
        # Update monitor
        self.task_monitors[pool_name]['total_tasks'] += 1
        self.task_monitors[pool_name]['active_tasks'] += 1
        
        def wrapped_task():
            try:
                result = task_func(*args, **kwargs)
                self.task_monitors[pool_name]['completed_tasks'] += 1
                return result
            except Exception as e:
                self.task_monitors[pool_name]['failed_tasks'] += 1
                logger.error(f"Task {task_id} failed: {str(e)}")
                raise
            finally:
                self.task_monitors[pool_name]['active_tasks'] -= 1
        
        pool.submit(wrapped_task)
        return task_id
    
    def get_pool_stats(self, pool_name: str) -> Dict[str, Any]:
        """Get statistics for a specific thread pool"""
        if pool_name not in self.thread_pools:
            return {'error': 'Pool not found'}
        
        pool = self.thread_pools[pool_name]
        monitor = self.task_monitors[pool_name]
        
        return {
            **monitor,
            'max_workers': pool._max_workers,
            'threads_active': len(pool._threads),
            'queue_size': pool._work_queue.qsize()
        }
    
    def shutdown_pool(self, pool_name: str, wait: bool = True):
        """Shutdown a specific thread pool"""
        if pool_name in self.thread_pools:
            self.thread_pools[pool_name].shutdown(wait=wait)
            del self.thread_pools[pool_name]
            del self.task_monitors[pool_name]

# Global instances
job_queue = JobQueue()
thread_manager = ThreadedTaskManager()

def background_job(func: Callable) -> Callable:
    """Decorator for background jobs with monitoring"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        job_id = job_queue.submit_job(func, *args, **kwargs)
        return {'job_id': job_id, 'status': 'submitted'}
    return wrapper

def threaded_task(pool_name: str = 'default') -> Callable:
    """Decorator for threaded tasks"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            task_id = thread_manager.submit_task(pool_name, func, *args, **kwargs)
            return {'task_id': task_id, 'pool': pool_name, 'status': 'submitted'}
        return wrapper
    return decorator

# Enhanced Celery tasks with threading support
@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def process_background_job(self, job_type: str, data: Dict[str, Any], user_id: Optional[int] = None):
    """Enhanced background job processor with threading support"""
    try:
        # Update task status
        if current_task:
            current_task.update_state(
                state='PROGRESS',
                meta={'status': 'Processing', 'progress': 0}
            )
        
        # Process based on job type
        if job_type == 'data_import':
            result = _process_data_import(data, user_id)
        elif job_type == 'report_generation':
            result = _process_report_generation(data, user_id)
        elif job_type == 'bulk_operation':
            result = _process_bulk_operation(data, user_id)
        elif job_type == 'system_maintenance':
            result = _process_system_maintenance(data)
        else:
            raise ValueError(f"Unknown job type: {job_type}")
        
        # Cache result
        cache_key = f"background_job_{self.request.id}"
        cache.set(cache_key, {
            'status': 'completed',
            'result': result,
            'completed_at': datetime.now().isoformat()
        }, timeout=3600)
        
        return result
        
    except Exception as e:
        logger.error(f"Background job failed: {str(e)}")
        
        # Update cache with error
        cache_key = f"background_job_{self.request.id}"
        cache.set(cache_key, {
            'status': 'failed',
            'error': str(e),
            'failed_at': datetime.now().isoformat()
        }, timeout=3600)
        
        # Retry if possible
        try:
            raise self.retry(exc=e)
        except Exception:
            return {'status': 'failed', 'error': str(e)}

@shared_task
def monitor_system_resources():
    """Monitor system resources and trigger maintenance if needed"""
    try:
        # Get system metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        # Check thresholds
        if cpu_percent > 80:
            logger.warning(f"High CPU usage: {cpu_percent}%")
            # Trigger CPU optimization tasks
        
        if memory.percent > 85:
            logger.warning(f"High memory usage: {memory.percent}%")
            # Trigger memory cleanup tasks
        
        if disk.percent > 90:
            logger.warning(f"High disk usage: {disk.percent}%")
            # Trigger disk cleanup tasks
        
        # Cache metrics
        cache.set('system_metrics', {
            'cpu_percent': cpu_percent,
            'memory_percent': memory.percent,
            'disk_percent': disk.percent,
            'timestamp': datetime.now().isoformat()
        }, timeout=300)
        
        return {
            'cpu_percent': cpu_percent,
            'memory_percent': memory.percent,
            'disk_percent': disk.percent
        }
        
    except Exception as e:
        logger.error(f"Error monitoring system resources: {str(e)}")
        return {'error': str(e)}

# Helper functions for different job types
def _process_data_import(data: Dict[str, Any], user_id: Optional[int]) -> Dict[str, Any]:
    """Process data import jobs"""
    # Implementation for data import processing
    return {'status': 'completed', 'imported_records': 0}

def _process_report_generation(data: Dict[str, Any], user_id: Optional[int]) -> Dict[str, Any]:
    """Process report generation jobs"""
    # Implementation for report generation
    return {'status': 'completed', 'report_url': 'generated_report.pdf'}

def _process_bulk_operation(data: Dict[str, Any], user_id: Optional[int]) -> Dict[str, Any]:
    """Process bulk operations"""
    # Implementation for bulk operations
    return {'status': 'completed', 'processed_items': 0}

def _process_system_maintenance(data: Dict[str, Any]) -> Dict[str, Any]:
    """Process system maintenance tasks"""
    # Implementation for system maintenance
    return {'status': 'completed', 'maintenance_tasks': []}

# API functions for job management
def get_job_status(job_id: str) -> Dict[str, Any]:
    """Get status of a background job"""
    return job_queue.get_job_status(job_id)

def get_queue_statistics() -> Dict[str, Any]:
    """Get queue statistics"""
    return job_queue.get_queue_stats()

def get_thread_pool_stats(pool_name: str) -> Dict[str, Any]:
    """Get thread pool statistics"""
    return thread_manager.get_pool_stats(pool_name)

def submit_background_job(job_type: str, data: Dict[str, Any], user_id: Optional[int] = None) -> str:
    """Submit a background job"""
    return process_background_job.delay(job_type, data, user_id).id

def submit_threaded_task(pool_name: str, task_func: Callable, *args, **kwargs) -> str:
    """Submit a threaded task"""
    return thread_manager.submit_task(pool_name, task_func, *args, **kwargs)
