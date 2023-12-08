# -*- coding: utf-8 -*-

from __future__ import absolute_import, unicode_literals

import os
from celery import Celery
from celery.signals import setup_logging

# set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'trading_bot.settings')

app = Celery('trading_bot')
app.conf.task_default_queue = 'trading-bot-worker'

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

@setup_logging.connect
def config_loggers(*args, **kwags):
    from logging.config import dictConfig
    from django.conf import settings
    dictConfig(settings.LOGGING)

@app.task(bind=True)
def debug_task(self):
    print('Request: {0!r}'.format(self.request))
    
#@shared_task(bind=True)
#def task(self, params):
 #   self.backend.task_keyprefix = b'new-prefix'
