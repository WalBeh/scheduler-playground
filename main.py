import logging
import icecream
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor, ProcessPoolExecutor
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from icecream import ic
import time
import uvicorn
import os
import pytz
import threading
from database import get_db, write_db
from halo import Halo

from jobstore_sqlalchemy import CrateDBSQLAlchemyJobStore
from scheduler import FileChangeHandler, my_job
from fastapi import FastAPI
from cronjob_routes import router as cronjob_router
from util import setup_logging

logger = logging.getLogger(__name__)

icecream.IceCreamDebugger.lineWrapWidth = 120


class Supertask:

    def __init__(self, job_store_address: str, pre_delete_jobs: bool = False):
        self.job_store_address = job_store_address
        self.pre_delete_jobs = pre_delete_jobs
        self.scheduler: BackgroundScheduler = None
        self.configure()

    def configure(self):
        """
        https://apscheduler.readthedocs.io/en/3.x/userguide.html#configuring-the-scheduler
        """
        logger.info("Configuring scheduler")

        # Initialize a job store.
        if self.job_store_address.startswith("memory://"):
            job_store = MemoryJobStore()
        elif self.job_store_address.startswith("postgresql://"):
            job_store = SQLAlchemyJobStore(url=self.job_store_address, engine_options={"echo": True})
        elif self.job_store_address.startswith("crate://"):
            job_store = CrateDBSQLAlchemyJobStore(url=self.job_store_address, engine_options={"echo": True})
        else:
            raise RuntimeError(f"Initializing job store failed. Unknown address: {self.job_store_address}")

        if self.pre_delete_jobs:
            try:
                job_store.remove_all_jobs()
            except:
                pass

        job_defaults = {
            'coalesce': False,
            'max_instances': 1
        }
        executors = {
            'default': ThreadPoolExecutor(20),
            'processpool': ProcessPoolExecutor(5)
        }
        job_stores = {
            'default': job_store,
        }

        # Create a timezone object for Vienna
        timezone = pytz.timezone('Europe/Vienna')
        self.scheduler = BackgroundScheduler(executors=executors, job_defaults=job_defaults, jobstores=job_stores, timezone=timezone)
        logger.info(f"Configured scheduler: "
                    f"executors={self.scheduler._executors}, "
                    f"jobstores={self.scheduler._jobstores}, "
                    f"timezone={self.scheduler.timezone}"
                    )
        return self

    def start(self):
        self.start_scheduler()
        self.start_filesystem_observer()
        self.start_http_service()
        return self

    def start_scheduler(self):
        logger.info("Starting scheduler")
        self.scheduler.start()
        start = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        ic('//======= START ======', start)

        # Get next run time for all jobs
        jobs = self.scheduler.get_jobs()
        for job in jobs:
            ic(job.id, job.next_run_time)
        return self

    def wait(self):
        print('Press Ctrl+{0} to exit'.format('Break' if os.name == 'nt' else 'C'))
        spinner = Halo(text='Waiting', spinner='dots')
        spinner.start()
        try:
            # This is here to simulate application activity (which keeps the main thread alive).
            while True:
                time.sleep(2)
        except (KeyboardInterrupt, SystemExit):
            # Not strictly necessary if daemonic mode is enabled but should be done if possible
            self.scheduler.shutdown()
        return self

    def seed_jobs(self):
        logger.info("Seeding jobs")
        # Initial load of jobs from cronjobs.json
        cronjobs = get_db()
        for cronjob in cronjobs:
            if cronjob.enabled:
                ic(cronjob)
                minute, hour, day, month, day_of_week = cronjob.crontab.split()
                self.scheduler.add_job(my_job, 'cron', minute=minute, hour=hour, day=day, month=month,
                                       day_of_week=day_of_week, id=str(cronjob.id), jobstore='default', args=[cronjob.job],
                                       max_instances=4)
        return self

    def start_filesystem_observer(self):
        logger.info("Starting filesystem observer")
        # Create an instance of FileChangeHandler with the scheduler
        file_change_handler = FileChangeHandler(self.scheduler)

        # Watch cronjobs.json for changes in scheduled jobs
        observer = Observer()
        # observer.schedule(FileChangeHandler(), path=os.path.dirname(os.path.abspath('cronjobs.json')))
        observer.schedule(file_change_handler, path=os.path.dirname(os.path.abspath('cronjobs.json')))
        observer.start()
        return self

    def start_http_service(self):
        logger.info("Starting HTTP service")
        app = FastAPI()
        app.include_router(cronjob_router)

        def run_server():
            uvicorn.run(app, host="127.0.0.1", port=8000)

        server_thread = threading.Thread(target=run_server)
        server_thread.start()
        return self


def run_supertask(job_store_address: str, pre_delete_jobs: bool = False):
    setup_logging()
    st = Supertask(job_store_address=job_store_address, pre_delete_jobs=pre_delete_jobs)
    st.seed_jobs()
    st.start()
    return st


if __name__ == "__main__":
    # TODO: Use only in sandbox mode, to have a fresh database canvas.
    pre_delete_jobs = True
    #main(job_store_address="memory://", pre_delete_jobs=pre_delete_jobs)
    #main(job_store_address="postgresql://postgres@localhost", pre_delete_jobs=pre_delete_jobs)
    st = run_supertask(job_store_address="crate://localhost", pre_delete_jobs=pre_delete_jobs)
    st.wait()
