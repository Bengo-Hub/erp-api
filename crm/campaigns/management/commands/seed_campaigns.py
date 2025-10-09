from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model
from crm.campaigns.models import Campaign
from business.models import Branch
from ecommerce.stockinventory.models import StockInventory
from datetime import timedelta

User = get_user_model()

class Command(BaseCommand):
    help = 'Seeds sample campaign data for testing and development'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting to seed campaign data...'))
        
        # Get or create admin user
        admin_user = User.objects.filter(is_superuser=True).first()
        if not admin_user:
            admin_user = User.objects.filter(is_staff=True).first()
        if not admin_user:
            admin_user = User.objects.first()
        
        if not admin_user:
            self.stdout.write(self.style.ERROR('No user found to create campaigns'))
            return
        
        # Get business branch
        branch = Branch.objects.first()
        if not branch:
            self.stdout.write(self.style.ERROR('No business branch found'))
            return
        
        # Get some products for featured products
        products = StockInventory.objects.filter(stock_level__gt=0)[:5]
        
        # Sample campaign data including banner campaigns
        campaigns_data = [
            # Banner campaigns (replacing old Banner model)
            {
                'name': 'Welcome to ProcurePro',
                'campaign_type': 'banner',
                'status': 'active',
                'priority': 1,
                'title': 'Welcome to ProcurePro',
                'description': 'Your one-stop solution for all procurement needs',
                'badge': 'best-seller',
                'start_date': timezone.now(),
                'end_date': timezone.now() + timedelta(days=365),
                'is_active': True,
                'is_default': True,
                'landing_page_url': '/ecommerce/shop/products?filter=featured',
                'cta_text': 'Shop Now'
            },
            {
                'name': 'Precision Engineering',
                'campaign_type': 'banner',
                'status': 'active',
                'priority': 2,
                'title': 'Precision Engineering',
                'description': 'Discover our latest services',
                'badge': 'solution-provider',
                'start_date': timezone.now(),
                'end_date': timezone.now() + timedelta(days=365),
                'is_active': True,
                'is_default': True,
                'landing_page_url': '/ecommerce/shop/products?filter=services',
                'cta_text': 'Learn More'
            },
            {
                'name': 'Limited Time Offer',
                'campaign_type': 'banner',
                'status': 'active',
                'priority': 3,
                'title': 'Limited Time Offer',
                'description': 'Get 20% off on your first order',
                'badge': 'special-offers',
                'start_date': timezone.now(),
                'end_date': timezone.now() + timedelta(days=30),
                'is_active': True,
                'is_default': True,
                'landing_page_url': '/ecommerce/shop/products?filter=sale',
                'cta_text': 'Shop Now'
            },
            # Regular campaigns
            {
                'name': 'Summer Sale 2024',
                'campaign_type': 'promotional',
                'status': 'active',
                'priority': 4,
                'title': 'Summer Sale - Up to 50% Off!',
                'description': 'Get ready for summer with amazing deals on all summer essentials',
                'badge': 'HOT DEAL',
                'start_date': timezone.now(),
                'end_date': timezone.now() + timedelta(days=30),
                'is_active': True,
                'is_default': False,
                'budget': 50000.00,
                'landing_page_url': '/summer-sale',
                'cta_text': 'Shop Now'
            },
            {
                'name': 'New Product Launch',
                'campaign_type': 'product_launch',
                'status': 'active',
                'priority': 5,
                'title': 'Introducing Our Latest Collection',
                'description': 'Discover our newest products designed for modern living',
                'badge': 'NEW',
                'start_date': timezone.now() - timedelta(days=7),
                'end_date': timezone.now() + timedelta(days=23),
                'is_active': True,
                'is_default': False,
                'budget': 30000.00,
                'landing_page_url': '/new-products',
                'cta_text': 'Explore'
            },
            {
                'name': 'Loyalty Program',
                'campaign_type': 'loyalty',
                'status': 'active',
                'priority': 6,
                'title': 'Join Our Loyalty Program',
                'description': 'Earn points on every purchase and unlock exclusive benefits',
                'badge': 'REWARDS',
                'start_date': timezone.now() - timedelta(days=14),
                'end_date': timezone.now() + timedelta(days=16),
                'is_active': True,
                'is_default': False,
                'budget': 20000.00,
                'landing_page_url': '/loyalty',
                'cta_text': 'Join Now'
            }
        ]
        
        created_campaigns = []
        for campaign_data in campaigns_data:
            # Create campaign
            campaign, created = Campaign.objects.get_or_create(
                name=campaign_data['name'],
                defaults={
                    **campaign_data,
                    'created_by': admin_user,
                    'branch': branch  # Set the branch for banner compatibility
                }
            )
            
            if created:
                # Add featured products if available
                if products.exists():
                    campaign.featured_products.set(products[:3])
                    campaign.stock_items.set(products[:3])  # For banner compatibility
                
                # Add target branch
                campaign.target_branches.add(branch)
                
                created_campaigns.append(campaign)
                self.stdout.write(f'Created campaign: {campaign.name}')
            else:
                self.stdout.write(f'Campaign already exists: {campaign.name}')
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully seeded {len(created_campaigns)} campaigns'
            )
        )
        
        # Display campaign summary
        total_campaigns = Campaign.objects.count()
        active_campaigns = Campaign.objects.filter(status='active').count()
        banner_campaigns = Campaign.objects.filter(campaign_type='banner').count()
        
        self.stdout.write(f'\nCampaign Summary:')
        self.stdout.write(f'Total campaigns: {total_campaigns}')
        self.stdout.write(f'Active campaigns: {active_campaigns}')
        self.stdout.write(f'Banner campaigns: {banner_campaigns}')
