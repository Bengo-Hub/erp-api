"""
Load testing utilities for Bengo ERP.
Provides tools for testing API endpoints, database performance, and system resources under load.
"""

import asyncio
import aiohttp
import time
import statistics
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Any, Optional, Callable
from django.conf import settings
from django.core.cache import cache
from django.db import connection
import psutil
import json

logger = logging.getLogger(__name__)

class LoadTester:
    """Load testing utility for API endpoints and system performance"""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or 'http://localhost:8000'
        self.results = {}
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def test_endpoint(self, endpoint: str, method: str = 'GET', 
                          headers: Dict = None, data: Dict = None,
                          concurrent_users: int = 10, duration: int = 30) -> Dict[str, Any]:
        """
        Test an API endpoint under load
        
        Args:
            endpoint: API endpoint to test
            method: HTTP method (GET, POST, PUT, DELETE)
            headers: Request headers
            data: Request data for POST/PUT requests
            concurrent_users: Number of concurrent users
            duration: Test duration in seconds
        
        Returns:
            Test results with performance metrics
        """
        if not self.session:
            raise RuntimeError("LoadTester must be used as async context manager")
        
        url = f"{self.base_url}{endpoint}"
        headers = headers or {}
        
        # Add authentication header if available
        if hasattr(settings, 'TEST_AUTH_TOKEN'):
            headers['Authorization'] = f"Bearer {settings.TEST_AUTH_TOKEN}"
        
        start_time = time.time()
        end_time = start_time + duration
        
        # Track metrics
        response_times = []
        status_codes = {}
        errors = []
        
        # Create tasks for concurrent requests
        tasks = []
        for _ in range(concurrent_users):
            task = asyncio.create_task(
                self._make_requests(url, method, headers, data, end_time, response_times, status_codes, errors)
            )
            tasks.append(task)
        
        # Wait for all tasks to complete
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Calculate metrics
        total_requests = len(response_times)
        total_duration = time.time() - start_time
        
        if response_times:
            avg_response_time = statistics.mean(response_times)
            min_response_time = min(response_times)
            max_response_time = max(response_times)
            p95_response_time = statistics.quantiles(response_times, n=20)[18]  # 95th percentile
            p99_response_time = statistics.quantiles(response_times, n=100)[98]  # 99th percentile
        else:
            avg_response_time = min_response_time = max_response_time = p95_response_time = p99_response_time = 0
        
        requests_per_second = total_requests / total_duration if total_duration > 0 else 0
        
        return {
            'endpoint': endpoint,
            'method': method,
            'concurrent_users': concurrent_users,
            'duration': duration,
            'total_requests': total_requests,
            'requests_per_second': round(requests_per_second, 2),
            'avg_response_time': round(avg_response_time * 1000, 2),  # Convert to ms
            'min_response_time': round(min_response_time * 1000, 2),
            'max_response_time': round(max_response_time * 1000, 2),
            'p95_response_time': round(p95_response_time * 1000, 2),
            'p99_response_time': round(p99_response_time * 1000, 2),
            'status_codes': status_codes,
            'errors': errors,
            'success_rate': round((total_requests - len(errors)) / total_requests * 100, 2) if total_requests > 0 else 0
        }
    
    async def _make_requests(self, url: str, method: str, headers: Dict, data: Dict,
                           end_time: float, response_times: List, status_codes: Dict, errors: List):
        """Make continuous requests until end time"""
        while time.time() < end_time:
            try:
                start = time.time()
                
                if method.upper() == 'GET':
                    async with self.session.get(url, headers=headers) as response:
                        response_time = time.time() - start
                        response_times.append(response_time)
                        status_codes[response.status] = status_codes.get(response.status, 0) + 1
                        
                        if response.status >= 400:
                            errors.append(f"HTTP {response.status}: {url}")
                
                elif method.upper() == 'POST':
                    async with self.session.post(url, headers=headers, json=data) as response:
                        response_time = time.time() - start
                        response_times.append(response_time)
                        status_codes[response.status] = status_codes.get(response.status, 0) + 1
                        
                        if response.status >= 400:
                            errors.append(f"HTTP {response.status}: {url}")
                
                # Small delay to prevent overwhelming the server
                await asyncio.sleep(0.01)
                
            except Exception as e:
                errors.append(f"Request error: {str(e)}")
                await asyncio.sleep(0.1)  # Longer delay on error


class DatabaseLoadTester:
    """Load testing utility for database operations"""
    
    def __init__(self):
        self.results = {}
    
    def test_query_performance(self, query_func: Callable, iterations: int = 1000,
                             concurrent_threads: int = 10) -> Dict[str, Any]:
        """
        Test database query performance under load
        
        Args:
            query_func: Function that executes the database query
            iterations: Number of iterations to run
            concurrent_threads: Number of concurrent threads
        
        Returns:
            Performance test results
        """
        start_time = time.time()
        
        # Track metrics
        response_times = []
        errors = []
        
        def execute_query():
            try:
                start = time.time()
                query_func()
                response_time = time.time() - start
                response_times.append(response_time)
            except Exception as e:
                errors.append(str(e))
        
        # Execute queries with thread pool
        with ThreadPoolExecutor(max_workers=concurrent_threads) as executor:
            futures = [executor.submit(execute_query) for _ in range(iterations)]
            
            # Wait for all futures to complete
            for future in futures:
                future.result()
        
        total_duration = time.time() - start_time
        
        # Calculate metrics
        if response_times:
            avg_response_time = statistics.mean(response_times)
            min_response_time = min(response_times)
            max_response_time = max(response_times)
            p95_response_time = statistics.quantiles(response_times, n=20)[18]
            p99_response_time = statistics.quantiles(response_times, n=100)[98]
        else:
            avg_response_time = min_response_time = max_response_time = p95_response_time = p99_response_time = 0
        
        queries_per_second = len(response_times) / total_duration if total_duration > 0 else 0
        
        return {
            'iterations': iterations,
            'concurrent_threads': concurrent_threads,
            'total_queries': len(response_times),
            'queries_per_second': round(queries_per_second, 2),
            'avg_response_time': round(avg_response_time * 1000, 2),
            'min_response_time': round(min_response_time * 1000, 2),
            'max_response_time': round(max_response_time * 1000, 2),
            'p95_response_time': round(p95_response_time * 1000, 2),
            'p99_response_time': round(p99_response_time * 1000, 2),
            'errors': errors,
            'success_rate': round((iterations - len(errors)) / iterations * 100, 2) if iterations > 0 else 0
        }


class SystemLoadTester:
    """Load testing utility for system resources"""
    
    def __init__(self):
        self.results = {}
    
    def monitor_system_resources(self, duration: int = 60, interval: float = 1.0) -> Dict[str, Any]:
        """
        Monitor system resources during load testing
        
        Args:
            duration: Monitoring duration in seconds
            interval: Monitoring interval in seconds
        
        Returns:
            System resource metrics
        """
        start_time = time.time()
        end_time = start_time + duration
        
        cpu_usage = []
        memory_usage = []
        disk_io = []
        network_io = []
        
        while time.time() < end_time:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=interval)
            cpu_usage.append(cpu_percent)
            
            # Memory usage
            memory = psutil.virtual_memory()
            memory_usage.append(memory.percent)
            
            # Disk I/O
            disk_io_counters = psutil.disk_io_counters()
            if disk_io_counters:
                disk_io.append({
                    'read_bytes': disk_io_counters.read_bytes,
                    'write_bytes': disk_io_counters.write_bytes,
                    'read_count': disk_io_counters.read_count,
                    'write_count': disk_io_counters.write_count
                })
            
            # Network I/O
            network_io_counters = psutil.net_io_counters()
            if network_io_counters:
                network_io.append({
                    'bytes_sent': network_io_counters.bytes_sent,
                    'bytes_recv': network_io_counters.bytes_recv,
                    'packets_sent': network_io_counters.packets_sent,
                    'packets_recv': network_io_counters.packets_recv
                })
        
        # Calculate metrics
        if cpu_usage:
            avg_cpu = statistics.mean(cpu_usage)
            max_cpu = max(cpu_usage)
            min_cpu = min(cpu_usage)
        else:
            avg_cpu = max_cpu = min_cpu = 0
        
        if memory_usage:
            avg_memory = statistics.mean(memory_usage)
            max_memory = max(memory_usage)
            min_memory = min(memory_usage)
        else:
            avg_memory = max_memory = min_memory = 0
        
        return {
            'duration': duration,
            'interval': interval,
            'cpu': {
                'avg_usage': round(avg_cpu, 2),
                'max_usage': round(max_cpu, 2),
                'min_usage': round(min_cpu, 2),
                'samples': len(cpu_usage)
            },
            'memory': {
                'avg_usage': round(avg_memory, 2),
                'max_usage': round(max_memory, 2),
                'min_usage': round(min_memory, 2),
                'samples': len(memory_usage)
            },
            'disk_io': {
                'samples': len(disk_io),
                'total_read_bytes': sum(sample['read_bytes'] for sample in disk_io) if disk_io else 0,
                'total_write_bytes': sum(sample['write_bytes'] for sample in disk_io) if disk_io else 0
            },
            'network_io': {
                'samples': len(network_io),
                'total_bytes_sent': sum(sample['bytes_sent'] for sample in network_io) if network_io else 0,
                'total_bytes_recv': sum(sample['bytes_recv'] for sample in network_io) if network_io else 0
            }
        }


class LoadTestManager:
    """Manager for comprehensive load testing"""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url
        self.api_tester = None
        self.db_tester = DatabaseLoadTester()
        self.system_tester = SystemLoadTester()
        self.test_results = {}
    
    async def run_comprehensive_test(self, test_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run comprehensive load testing
        
        Args:
            test_config: Configuration for load tests
        
        Returns:
            Comprehensive test results
        """
        results = {
            'timestamp': time.time(),
            'config': test_config,
            'api_tests': {},
            'database_tests': {},
            'system_tests': {},
            'summary': {}
        }
        
        # Start system monitoring
        system_monitoring_task = asyncio.create_task(
            self._monitor_system_async(test_config.get('system_monitoring_duration', 60))
        )
        
        # Run API tests
        if 'api_endpoints' in test_config:
            async with LoadTester(self.base_url) as api_tester:
                for endpoint_config in test_config['api_endpoints']:
                    endpoint = endpoint_config['endpoint']
                    method = endpoint_config.get('method', 'GET')
                    concurrent_users = endpoint_config.get('concurrent_users', 10)
                    duration = endpoint_config.get('duration', 30)
                    
                    test_result = await api_tester.test_endpoint(
                        endpoint, method, concurrent_users=concurrent_users, duration=duration
                    )
                    results['api_tests'][endpoint] = test_result
        
        # Run database tests
        if 'database_queries' in test_config:
            for query_config in test_config['database_queries']:
                query_name = query_config['name']
                query_func = query_config['function']
                iterations = query_config.get('iterations', 1000)
                concurrent_threads = query_config.get('concurrent_threads', 10)
                
                test_result = self.db_tester.test_query_performance(
                    query_func, iterations, concurrent_threads
                )
                results['database_tests'][query_name] = test_result
        
        # Stop system monitoring
        system_monitoring_task.cancel()
        try:
            await system_monitoring_task
        except asyncio.CancelledError:
            pass
        
        # Generate summary
        results['summary'] = self._generate_summary(results)
        
        return results
    
    async def _monitor_system_async(self, duration: int) -> Dict[str, Any]:
        """Monitor system resources asynchronously"""
        return self.system_tester.monitor_system_resources(duration)
    
    def _generate_summary(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate summary of test results"""
        summary = {
            'total_api_tests': len(results['api_tests']),
            'total_db_tests': len(results['database_tests']),
            'overall_success_rate': 0,
            'performance_issues': [],
            'recommendations': []
        }
        
        # Calculate overall success rate
        total_tests = summary['total_api_tests'] + summary['total_db_tests']
        if total_tests > 0:
            api_success_rates = [test['success_rate'] for test in results['api_tests'].values()]
            db_success_rates = [test['success_rate'] for test in results['database_tests'].values()]
            all_success_rates = api_success_rates + db_success_rates
            summary['overall_success_rate'] = round(statistics.mean(all_success_rates), 2)
        
        # Identify performance issues
        for endpoint, test_result in results['api_tests'].items():
            if test_result['avg_response_time'] > 1000:  # > 1 second
                summary['performance_issues'].append(f"Slow API response: {endpoint} ({test_result['avg_response_time']}ms)")
            
            if test_result['success_rate'] < 95:
                summary['performance_issues'].append(f"Low success rate: {endpoint} ({test_result['success_rate']}%)")
        
        for query_name, test_result in results['database_tests'].items():
            if test_result['avg_response_time'] > 100:  # > 100ms
                summary['performance_issues'].append(f"Slow database query: {query_name} ({test_result['avg_response_time']}ms)")
        
        # Generate recommendations
        if summary['performance_issues']:
            summary['recommendations'].append("Consider implementing caching for frequently accessed data")
            summary['recommendations'].append("Optimize database queries and add indexes where needed")
            summary['recommendations'].append("Consider using CDN for static assets")
        
        if summary['overall_success_rate'] < 95:
            summary['recommendations'].append("Investigate and fix failing requests")
        
        return summary


# Utility functions for common load testing scenarios
def create_api_load_test_config(endpoints: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create configuration for API load testing"""
    return {
        'api_endpoints': endpoints,
        'system_monitoring_duration': 60
    }

def create_database_load_test_config(queries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create configuration for database load testing"""
    return {
        'database_queries': queries,
        'system_monitoring_duration': 60
    }

def create_comprehensive_load_test_config(api_endpoints: List[Dict[str, Any]] = None,
                                        database_queries: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create configuration for comprehensive load testing"""
    config = {
        'system_monitoring_duration': 60
    }
    
    if api_endpoints:
        config['api_endpoints'] = api_endpoints
    
    if database_queries:
        config['database_queries'] = database_queries
    
    return config
