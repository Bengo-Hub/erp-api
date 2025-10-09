from django.apps import AppConfig

class EmployeesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'hrm.employees'

    def ready(self):
        import hrm.employees.signals 
       
