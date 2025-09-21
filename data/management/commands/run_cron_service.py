import logging
import signal
import sys
import time
from django.core.management.base import BaseCommand
from data.workers import pool_optimizer_worker

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Run the pool optimizer worker to find optimal fund allocations between protocols'

    def add_arguments(self, parser):
        parser.add_argument(
            '--daemon',
            action='store_true',
            help='Run as a daemon process',
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=300,  # 5 minutes by default
            help='Interval between optimization checks in seconds',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting pool optimizer worker...'))
        
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)
        
        try:
            # Configure the worker with the specified interval
            pool_optimizer_worker.set_interval(options['interval'])
            
            # Start the optimizer worker
            pool_optimizer_worker.start()
            
            # If running as a daemon, keep the process alive
            if options['daemon']:
                self.stdout.write(
                    self.style.SUCCESS(f'Pool optimizer worker running in daemon mode (checking every {options["interval"]} seconds). Press Ctrl+C to stop.')
                )
                while True:
                    time.sleep(1)
            else:
                # Run for a single iteration and exit
                self.stdout.write(self.style.SUCCESS('Pool optimizer executed. Exiting.'))
                pool_optimizer_worker.stop()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error running pool optimizer worker: {str(e)}'))
            pool_optimizer_worker.stop()
            sys.exit(1)

    def handle_shutdown(self, signum, frame):
        self.stdout.write(self.style.WARNING('\nShutting down pool optimizer worker...'))
        pool_optimizer_worker.stop()
        sys.exit(0)