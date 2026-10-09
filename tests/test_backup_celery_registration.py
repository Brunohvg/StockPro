"""Tarefas de backup precisam estar registradas no worker Celery."""
def test_backup_tasks_are_discoverable():
    # Autodiscover importa este módulo, que deve carregar backup_task.
    import apps.tenants.tasks  # noqa: F401
    from stock_control.celery import app

    registered = app.tasks
    expected = (
        'apps.tenants.backup_task.daily_backup',
        'apps.tenants.backup_task.manual_backup',
        'apps.tenants.backup_task.verify_backup',
        'apps.tenants.backup_task.cleanup_old_exports',
    )
    for name in expected:
        assert name in registered, f'Tarefa não registrada pelo worker: {name}'
