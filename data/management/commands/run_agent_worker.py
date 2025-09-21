import logging
import signal
import sys
import time
from django.core.management.base import BaseCommand
from data.workers.agent_worker import AgentRunner

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Run the agent worker to execute trading agents based on their trade frequency'

    def add_arguments(self, parser):
        parser.add_argument(
            '--daemon',
            action='store_true',
            help='Run as a daemon process',
        )
        parser.add_argument(
            '--single-run',
            action='store_true',
            help='Run once and exit (for cron jobs)',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting agent worker...'))
        
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)
        
        try:
            if options['single_run']:
                # Run once and exit (for cron jobs)
                self.stdout.write(self.style.SUCCESS('Running agent worker in single-run mode...'))
                
                # Create an agent runner and run it once
                runner = AgentRunner()
                success = runner.run()
                
                if success:
                    self.stdout.write(self.style.SUCCESS('Agent worker single run completed successfully. Exiting.'))
                else:
                    self.stdout.write(self.style.ERROR('Agent worker single run failed. Exiting.'))
                    sys.exit(1)
                    
            elif options['daemon']:
                # Start the agent worker in daemon mode
                self.stdout.write(self.style.SUCCESS('Running agent worker in daemon mode...'))
                runner = AgentRunner()
                
                self.stdout.write(self.style.SUCCESS('Agent worker running in daemon mode. Press Ctrl+C to stop.'))
                while True:
                    try:
                        success = runner.run()
                        if success:
                            self.stdout.write(self.style.SUCCESS('Agent run completed successfully'))
                        else:
                            self.stdout.write(self.style.WARNING('Agent run completed with issues'))
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f'Error in agent run: {str(e)}'))
                    
                    # Wait 5 minutes before next run
                    time.sleep(300)
            else:
                # Run for a single iteration and exit
                self.stdout.write(self.style.SUCCESS('Running agent worker once...'))
                runner = AgentRunner()
                success = runner.run()
                
                if success:
                    self.stdout.write(self.style.SUCCESS('Agent worker executed successfully. Exiting.'))
                else:
                    self.stdout.write(self.style.ERROR('Agent worker execution failed. Exiting.'))
                    sys.exit(1)
                    
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error running agent worker: {str(e)}'))
            sys.exit(1)

    def handle_shutdown(self, signum, frame):
        self.stdout.write(self.style.WARNING('\nShutting down agent worker...'))
        sys.exit(0)
