from celery import Celery

def make_celery():
    app = Celery("autovc", broker="redis://localhost:6379/0", backend="redis://localhost:6379/0")
    app.conf.update(task_serializer="json", accept_content=["json"], result_serializer="json", timezone="UTC", enable_utc=True)
    app.autodiscover_tasks(["autovc.workers"])
    return app

celery_app = make_celery()
