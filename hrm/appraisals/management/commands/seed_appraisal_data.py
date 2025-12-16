from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from hrm.appraisals.models import *
from hrm.employees.models import Employee
from core.models import Regions
from datetime import datetime, timedelta

User = get_user_model()

class Command(BaseCommand):
    help = 'Seeds the database with sample appraisal data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--minimal',
            action='store_true',
            help='Seed a minimal set of appraisal data (1 cycle, 1 template, 1 employee)',
        )

    def handle(self, *args, **kwargs):
        self.stdout.write('Seeding appraisal data...')
        minimal = kwargs.get('minimal')
        
        # Create locations
        locations = Regions.objects.all()

        # Ensure at least one user exists for created_by
        creator = User.objects.first()
        if creator is None:
            creator = User.objects.create_superuser(username='admin', email='admin@example.com', password='admin123')

        # Create appraisal cycles (idempotent)
        cycles = [
            AppraisalCycle.objects.get_or_create(
                name='Annual Review 2024',
                defaults={
                    'description': 'Annual performance review for 2024',
                    'start_date': datetime.now(),
                    'end_date': datetime.now() + timedelta(days=30),
                    'due_date': datetime.now() + timedelta(days=20),
                    'status': 'created',
                    'created_by': creator,
                }
            )[0],
            AppraisalCycle.objects.get_or_create(
                name='Q1 Review 2024',
                defaults={
                    'description': 'First quarter review for 2024',
                    'start_date': datetime.now() - timedelta(days=30),
                    'end_date': datetime.now(),
                    'due_date': datetime.now() - timedelta(days=10),
                    'status': 'closed',
                    'created_by': creator,
                }
            )[0],
        ]

        # Add locations to cycles
        for cycle in cycles:
            cycle.locations.add(*locations)

        # Create appraisal templates
        templates = [
            AppraisalTemplate.objects.get_or_create(
                name='Standard Performance Review',
                defaults={
                    'description': 'Standard template for performance reviews',
                    'is_active': True,
                    'created_by': creator,
                }
            )[0],
            AppraisalTemplate.objects.get_or_create(
                name='Manager Review',
                defaults={
                    'description': 'Template for manager reviews',
                    'is_active': True,
                    'created_by': creator,
                }
            )[0],
        ]

        # Create questions for templates
        questions = []
        for template in templates:
            questions.extend([
                AppraisalQuestion.objects.create(
                    template=template,
                    question_text='How well did the employee meet their goals?',
                    question_type='rating',
                    is_required=True,
                    order=1
                ),
                AppraisalQuestion.objects.create(
                    template=template,
                    question_text='What are the employee\'s key strengths?',
                    question_type='text',
                    is_required=True,
                    order=2
                ),
                AppraisalQuestion.objects.create(
                    template=template,
                    question_text='What areas need improvement?',
                    question_type='text',
                    is_required=True,
                    order=3
                )
            ])

        # Create goals
        employees = Employee.objects.all()[: (1 if minimal else 3)]  # Get first N employees based on minimal
        goals = []
        for employee in employees:
            goals.extend([
                Goal.objects.create(
                    employee=employee,
                    title='Complete Project X',
                    description='Finish the implementation of Project X',
                    start_date=datetime.now(),
                    end_date=datetime.now() + timedelta(days=90),
                    status='in_progress',
                    progress=50,
                    is_template=False,
                    created_by=User.objects.first()
                ),
                Goal.objects.create(
                    employee=employee,
                    title='Improve Team Collaboration',
                    description='Enhance team communication and collaboration',
                    start_date=datetime.now(),
                    end_date=datetime.now() + timedelta(days=60),
                    status='completed',
                    progress=100,
                    is_template=False,
                    created_by=User.objects.first()
                )
            ])

        # Create goal progress entries
        for goal in goals:
            GoalProgress.objects.create(
                goal=goal,
                progress=goal.progress,
                comments='Initial progress update',
                updated_by=User.objects.first()
            )

        # Create appraisals
        appraisals = []
        for employee in employees:
            appraisals.append(
                Appraisal.objects.create(
                    cycle=cycles[0],
                    employee=employee,
                    evaluator=Employee.objects.exclude(pk=employee.pk).first(),
                    template=templates[0],
                    status='draft',
                    overall_rating=0,
                    comments='',
                    #created_by=User.objects.first()
                )
            )

        # Create appraisal responses
        for appraisal in appraisals:
            for question in questions[:3]:  # Use first 3 questions
                AppraisalResponse.objects.create(
                    appraisal=appraisal,
                    question=question,
                    response='Sample response',
                    rating=4 if question.question_type == 'rating' else None
                )

        self.stdout.write(self.style.SUCCESS('Successfully seeded appraisal data')) 