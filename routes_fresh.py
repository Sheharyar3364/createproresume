import os
<<<<<<< HEAD
import logging
import stripe
from flask import Blueprint, render_template, request, flash, redirect, url_for, send_file, current_app, abort
from flask_login import login_user, logout_user, login_required, current_user
from flask_mail import Message
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timezone
from urllib.parse import urljoin

from app import db, mail
from models import User, Order, ContactMessage, Admin, ReferralReward
from forms import LoginForm, RegisterForm, OrderForm, ContactForm, AdminOrderUpdateForm
from utils import allowed_file, calculate_referral_discount, send_email_notification

# Initialize Stripe
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

# Blueprint definitions
main_bp = Blueprint('main', __name__)
auth_bp = Blueprint('auth', __name__)
services_bp = Blueprint('services', __name__)
dashboard_bp = Blueprint('dashboard', __name__)
admin_bp = Blueprint('admin', __name__)
referral_bp = Blueprint('referral', __name__)

# Get domain for Stripe redirects
def get_domain():
    if os.environ.get('REPLIT_DEPLOYMENT'):
        return os.environ.get('REPLIT_DEV_DOMAIN')
    return request.host

# Main routes
@main_bp.route('/')
def index():
    return render_template('index.html')

@main_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    form = ContactForm()
    if form.validate_on_submit():
        message = ContactMessage(
            name=form.name.data,
            email=form.email.data,
            subject=form.subject.data,
            message=form.message.data
        )
        db.session.add(message)
        db.session.commit()
        
        # Send notification email
        send_email_notification('contact', message.email, message.name)
        
        flash('Thank you for your message! We\'ll get back to you soon.', 'success')
        return redirect(url_for('main.contact'))
    
    return render_template('contact.html', form=form)

# Authentication routes
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.customer' if not current_user.is_admin() else 'admin.dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user)
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('dashboard.customer' if not user.is_admin() else 'admin.dashboard'))
        flash('Invalid email or password.', 'danger')
    
    return render_template('auth/login.html', form=form)

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.customer'))
    
    form = RegisterForm()
    if form.validate_on_submit():
        # Check if user exists
        if User.query.filter_by(email=form.email.data).first():
            flash('Email already registered.', 'danger')
            return render_template('auth/register.html', form=form)
        
        if User.query.filter_by(username=form.username.data).first():
            flash('Username already taken.', 'danger')
            return render_template('auth/register.html', form=form)
        
        # Check referral code
        referrer = None
        if form.referral_code.data:
            referrer = User.query.filter_by(referral_code=form.referral_code.data).first()
            if not referrer:
                flash('Invalid referral code.', 'warning')
                return render_template('auth/register.html', form=form)
        
        # Create user
        user = User(
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            username=form.username.data,
            email=form.email.data,
            password_hash=generate_password_hash(form.password.data),
            referred_by=referrer.id if referrer else None
        )
        
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! You can now log in.', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/register.html', form=form)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.index'))

# Services routes
@services_bp.route('/pricing')
def pricing():
    return render_template('services/pricing.html')

@services_bp.route('/order/<service_type>')
@login_required
def order(service_type):
    pricing = {
        'basic': 99,
        'standard': 199,
        'premium': 299
    }
    
    if service_type not in pricing:
        flash('Invalid service type.', 'danger')
        return redirect(url_for('services.pricing'))
    
    form = OrderForm()
    form.service_type.data = service_type
    
    # Pre-fill form with user data
    if current_user:
        form.full_name.data = current_user.get_full_name()
        form.email.data = current_user.email
    
    return render_template('services/order.html', form=form, service_type=service_type, price=pricing[service_type])

@services_bp.route('/submit_order', methods=['POST'])
@login_required
def submit_order():
    form = OrderForm()
    
    if form.validate_on_submit():
        service_type = form.service_type.data
        pricing = {'basic': 99, 'standard': 199, 'premium': 299}
        
        if service_type not in pricing:
            flash('Invalid service type.', 'danger')
            return redirect(url_for('services.pricing'))
        
        price = pricing[service_type]
        
        # Apply referral discount
        referral_discount = 0
        referrer = None
        if form.referral_code.data:
            referrer = User.query.filter_by(referral_code=form.referral_code.data).first()
            if referrer and referrer.id != current_user.id:
                referral_discount = calculate_referral_discount(price)
                price -= referral_discount
        
        # Create order
        order = Order(
            user_id=current_user.id,
            service_type=service_type,
            price=price,
            full_name=form.full_name.data,
            email=form.email.data,
            phone=form.phone.data,
            target_position=form.target_position.data,
            industry=form.industry.data,
            experience_level=form.experience_level.data,
            special_requirements=form.special_requirements.data,
            referral_used=form.referral_code.data if referrer else None,
            referral_discount=referral_discount
        )
        
        # Handle file uploads
        upload_folder = current_app.config['UPLOAD_FOLDER']
        
        if form.resume_file.data:
            filename = secure_filename(f"resume_{current_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{form.resume_file.data.filename}")
            filepath = os.path.join(upload_folder, filename)
            form.resume_file.data.save(filepath)
            order.resume_file = filename
        
        if form.cover_letter_file.data:
            filename = secure_filename(f"cover_letter_{current_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{form.cover_letter_file.data.filename}")
            filepath = os.path.join(upload_folder, filename)
            form.cover_letter_file.data.save(filepath)
            order.cover_letter_file = filename
        
        if form.job_description_file.data:
            filename = secure_filename(f"job_desc_{current_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{form.job_description_file.data.filename}")
            filepath = os.path.join(upload_folder, filename)
            form.job_description_file.data.save(filepath)
            order.job_description_file = filename
        
        db.session.add(order)
        db.session.commit()
        
        # Create Stripe checkout session
        try:
            domain = get_domain()
            checkout_session = stripe.checkout.Session.create(
=======
import stripe
import json
import uuid
from datetime import datetime, timedelta
from flask import render_template, request, redirect, url_for, flash, send_file, jsonify, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
from flask_mail import Message
from sqlalchemy import func, desc
from app import db, mail, cache, limiter
from models import (Admin, Service, Order, ContactMessage, Testimonial, FAQ, 
                   Portfolio, DiscountCode, Referral, OrderTracking, Template,
                   NewsletterSubscriber, LiveChat, ChatMessage, Analytics, OrderDiscount)
from forms import (OrderForm, ContactForm, AdminLoginForm, OrderStatusForm,
                  TestimonialForm, FAQForm, DiscountCodeForm, ReferralForm,
                  NewsletterForm, LiveChatForm, AdminResponseForm, DiscountApplicationForm)
from utils import (track_event, validate_discount_code, apply_discount_to_order,
                  save_uploaded_file, calculate_estimated_delivery, generate_referral_code,
                  generate_session_id, format_price, get_service_features_list,
                  log_user_action, send_admin_notification_email)

def register_routes(app):
    
    # Configure Stripe
    @app.before_request
    def set_stripe_key():
        stripe.api_key = current_app.config.get('STRIPE_SECRET_KEY')
        # Set user session for analytics
        if 'user_id' not in session:
            session['user_id'] = str(uuid.uuid4())
    
    @app.route('/')
    @cache.cached(timeout=300)  # Cache for 5 minutes
    def index():
        track_event('page_view', {'page': 'home'})
        services = Service.query.filter_by(active=True).all()
        testimonials = Testimonial.query.filter_by(featured=True, approved=True).limit(6).all()
        portfolio_items = Portfolio.query.filter_by(featured=True, active=True).limit(4).all()
        faqs = FAQ.query.filter_by(active=True).order_by(FAQ.order_index.asc()).limit(5).all()
        return render_template('index.html', services=services, testimonials=testimonials, 
                             portfolio_items=portfolio_items, faqs=faqs)

    # New Enhanced Routes
    @app.route('/testimonials')
    @cache.cached(timeout=600)
    def testimonials():
        track_event('page_view', {'page': 'testimonials'})
        page = request.args.get('page', 1, type=int)
        industry_filter = request.args.get('industry', 'all')
        rating_filter = request.args.get('rating', 'all', type=str)
        
        query = Testimonial.query.filter_by(approved=True)
        if industry_filter != 'all':
            query = query.filter(Testimonial.industry == industry_filter)
        if rating_filter != 'all':
            query = query.filter(Testimonial.rating >= int(rating_filter))
        
        testimonials = query.order_by(desc(Testimonial.created_at)).paginate(
            page=page, per_page=12, error_out=False
        )
        
        industries = db.session.query(Testimonial.industry).distinct().filter(
            Testimonial.industry.isnot(None), Testimonial.approved == True
        ).all()
        industries = [i[0] for i in industries if i[0]]
        
        return render_template('testimonials.html', testimonials=testimonials,
                             industries=industries, current_industry=industry_filter,
                             current_rating=rating_filter)
    
    @app.route('/faq')
    @cache.cached(timeout=600)
    def faq():
        track_event('page_view', {'page': 'faq'})
        category_filter = request.args.get('category', 'all')
        
        query = FAQ.query.filter_by(active=True)
        if category_filter != 'all':
            query = query.filter(FAQ.category == category_filter)
            
        faqs = query.order_by(FAQ.order_index.asc(), FAQ.created_at.desc()).all()
        
        faq_categories = {}
        for faq_item in faqs:
            if faq_item.category not in faq_categories:
                faq_categories[faq_item.category] = []
            faq_categories[faq_item.category].append(faq_item)
        
        categories = ['general', 'pricing', 'process', 'delivery', 'revisions']
        
        return render_template('faq.html', faq_categories=faq_categories,
                             categories=categories, current_category=category_filter)

    @app.route('/track-order')
    def track_order():
        order_id = request.args.get('order_id')
        email = request.args.get('email')
        
        if not order_id or not email:
            return render_template('track_order.html')
        
        order = Order.query.filter_by(id=order_id, email=email).first()
        if not order:
            flash('Order not found. Please check your order ID and email.', 'error')
            return render_template('track_order.html')
        
        tracking_updates = OrderTracking.query.filter_by(order_id=order.id).order_by(
            OrderTracking.created_at.desc()).all()
        
        track_event('order_tracked', {'order_id': order.id})
        
        return render_template('track_order.html', order=order, tracking_updates=tracking_updates)

    @app.route('/refer', methods=['GET', 'POST'])
    def refer_friend():
        form = ReferralForm()
        
        if form.validate_on_submit():
            existing = Referral.query.filter_by(
                referrer_email=form.referrer_email.data,
                referred_email=form.referred_email.data
            ).first()
            
            if existing:
                flash('You have already referred this person!', 'warning')
                return render_template('referral.html', form=form)
            
            referral_code = generate_referral_code()
            referral = Referral(
                referrer_email=form.referrer_email.data,
                referrer_name=form.referrer_name.data,
                referred_email=form.referred_email.data,
                referred_name=form.referred_name.data,
                referral_code=referral_code,
                reward_amount=25.0
            )
            
            db.session.add(referral)
            db.session.commit()
            
            try:
                send_referral_emails(referral)
                flash('Referral sent successfully! Your friend will receive an email with your special offer.', 'success')
                track_event('referral_sent', {'referral_code': referral_code})
            except Exception as e:
                current_app.logger.error(f"Referral email error: {e}")
                flash('Referral created but email could not be sent. Please contact support.', 'warning')
            
            return redirect(url_for('refer_friend'))
        
        return render_template('referral.html', form=form)

    @app.route('/newsletter-signup', methods=['POST'])
    @limiter.limit("5 per hour")
    def newsletter_signup():
        form = NewsletterForm()
        
        if form.validate_on_submit():
            existing = NewsletterSubscriber.query.filter_by(email=form.email.data).first()
            
            if existing:
                if not existing.active:
                    existing.active = True
                    db.session.commit()
                    flash('Welcome back! You have been re-subscribed to our newsletter.', 'success')
                else:
                    flash('You are already subscribed to our newsletter!', 'info')
            else:
                subscriber = NewsletterSubscriber(
                    email=form.email.data,
                    name=form.name.data
                )
                db.session.add(subscriber)
                db.session.commit()
                
                try:
                    send_newsletter_welcome_email(subscriber)
                except Exception as e:
                    current_app.logger.error(f"Newsletter welcome email error: {e}")
                
                flash('Thank you for subscribing! Check your email for a welcome message.', 'success')
                track_event('newsletter_signup', {'email': form.email.data})
        
        return redirect(request.referrer or url_for('index'))
    
    @app.route('/order')
    def order():
        form = OrderForm()
        services = Service.query.filter_by(active=True).all()
        form.service_id.choices = [(s.id, s.name) for s in services]
        return render_template('order.html', form=form, services=services)
    
    @app.route('/submit-order', methods=['POST'])
    def submit_order():
        form = OrderForm()
        services = Service.query.filter_by(active=True).all()
        form.service_id.choices = [(s.id, s.name) for s in services]
        
        if form.validate_on_submit():
            # Get selected service
            service = Service.query.get(form.service_id.data)
            if not service:
                flash('Invalid service selected.', 'error')
                return render_template('order.html', form=form, services=services)
            
            # Calculate total amount based on tier
            tier_prices = {
                'basic': service.price_basic,
                'standard': service.price_standard,
                'premium': service.price_premium
            }
            total_amount = tier_prices.get(form.service_tier.data)
            
            if not total_amount:
                flash('Invalid service tier selected.', 'error')
                return render_template('order.html', form=form, services=services)
            
            # Create order
            order = Order(  # type: ignore
                first_name=form.first_name.data,
                last_name=form.last_name.data,
                email=form.email.data,
                phone=form.phone.data,
                service_id=form.service_id.data,
                service_tier=form.service_tier.data,
                total_amount=total_amount,
                current_position=form.current_position.data,
                target_position=form.target_position.data,
                industry=form.industry.data,
                experience_years=form.experience_years.data,
                career_goals=form.career_goals.data,
                special_requirements=form.special_requirements.data
            )
            
            # Handle file uploads
            upload_folder = current_app.config['UPLOAD_FOLDER']
            
            if form.current_resume.data:
                filename = secure_filename(form.current_resume.data.filename)
                filename = f"resume_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
                file_path = os.path.join(upload_folder, filename)
                form.current_resume.data.save(file_path)
                order.uploaded_resume_path = filename
            
            if form.cover_letter.data:
                filename = secure_filename(form.cover_letter.data.filename)
                filename = f"cover_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
                file_path = os.path.join(upload_folder, filename)
                form.cover_letter.data.save(file_path)
                order.uploaded_cover_letter_path = filename
            
            if form.job_description.data:
                filename = secure_filename(form.job_description.data.filename)
                filename = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
                file_path = os.path.join(upload_folder, filename)
                form.job_description.data.save(file_path)
                order.uploaded_job_description_path = filename
            
            db.session.add(order)
            db.session.commit()
            
            # Send confirmation email
            try:
                send_order_confirmation_email(order)
            except Exception as e:
                current_app.logger.error(f"Failed to send confirmation email: {e}")
            
            # Redirect to Stripe checkout
            return redirect(url_for('create_checkout_session', order_id=order.id))
        
        return render_template('order.html', form=form, services=services)
    
    @app.route('/create-checkout-session/<int:order_id>')
    def create_checkout_session(order_id):
        order = Order.query.get_or_404(order_id)
        
        if not stripe.api_key:
            flash('Payment system is not configured. Please contact support.', 'error')
            return redirect(url_for('index'))
        
        try:
            # Get domain for success/cancel URLs
            domain = request.host_url.rstrip('/')
            
            # Create Stripe checkout session
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
>>>>>>> ded7f2e4447248a018f7dd7d09de9c43eb09fa0d
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {
<<<<<<< HEAD
                            'name': order.get_service_display_name(),
                        },
                        'unit_amount': int(price * 100),  # Stripe expects cents
=======
                            'name': f'{order.service.name} - {order.service_tier.title()}',
                            'description': f'Resume writing service for {order.full_name}',
                        },
                        'unit_amount': int(order.total_amount * 100),  # Convert to cents
>>>>>>> ded7f2e4447248a018f7dd7d09de9c43eb09fa0d
                    },
                    'quantity': 1,
                }],
                mode='payment',
<<<<<<< HEAD
                success_url=f'https://{domain}/payment/success?order_id={order.id}',
                cancel_url=f'https://{domain}/payment/cancel?order_id={order.id}',
                metadata={'order_id': str(order.id)}
            )
            
            # Update order with Stripe session ID
            order.stripe_payment_id = checkout_session.id
            db.session.commit()
            
            return redirect(checkout_session.url, code=303)
            
        except Exception as e:
            logging.error(f"Stripe error: {str(e)}")
            flash('Payment processing error. Please try again.', 'danger')
            return redirect(url_for('services.order', service_type=service_type))
    
    flash('Please correct the errors below.', 'danger')
    return render_template('services/order.html', form=form)

@services_bp.route('/payment/success')
def payment_success():
    order_id = request.args.get('order_id')
    if order_id:
        order = Order.query.get_or_404(order_id)
        order.payment_status = 'completed'
        order.status = 'processing'
        db.session.commit()
        
        # Process referral reward
        if order.referral_used:
            referrer = User.query.filter_by(referral_code=order.referral_used).first()
            if referrer:
                reward_amount = order.referral_discount * 0.5  # 50% of discount as reward
                reward = ReferralReward(
                    referrer_id=referrer.id,
                    referred_id=order.user_id,
                    order_id=order.id,
                    reward_amount=reward_amount
                )
                referrer.referral_earnings += reward_amount
                db.session.add(reward)
                db.session.commit()
        
        # Send confirmation email
        send_email_notification('order_confirmation', order.email, order.full_name, order=order)
        
    return render_template('success.html', order=order if order_id else None)

@services_bp.route('/payment/cancel')
def payment_cancel():
    order_id = request.args.get('order_id')
    order = None
    if order_id:
        order = Order.query.get(order_id)
    return render_template('cancel.html', order=order)

# Dashboard routes
@dashboard_bp.route('/customer')
@login_required
def customer():
    if current_user.is_admin():
        return redirect(url_for('admin.dashboard'))
    
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template('dashboard/customer.html', orders=orders, user=current_user)

@dashboard_bp.route('/download/<int:order_id>/<file_type>')
@login_required
def download_file(order_id, file_type):
    order = Order.query.get_or_404(order_id)
    
    # Check if user owns the order
    if order.user_id != current_user.id:
        abort(403)
    
    # Check if order is completed
    if order.status != 'completed' and order.status != 'delivered':
        flash('Files are not yet available for download.', 'warning')
        return redirect(url_for('dashboard.customer'))
    
    # Get the appropriate file
    filename = None
    folder = current_app.config['COMPLETED_FOLDER']
    
    if file_type == 'resume' and order.completed_resume:
        filename = order.completed_resume
    elif file_type == 'cover_letter' and order.completed_cover_letter:
        filename = order.completed_cover_letter
    
    if not filename:
        flash('File not found.', 'danger')
        return redirect(url_for('dashboard.customer'))
    
    filepath = os.path.join(folder, filename)
    if not os.path.exists(filepath):
        flash('File not found on server.', 'danger')
        return redirect(url_for('dashboard.customer'))
    
    # Update order status to delivered on first download
    if order.status == 'completed':
        order.status = 'delivered'
        db.session.commit()
    
    return send_file(filepath, as_attachment=True, download_name=f"{file_type}_{order.id}.pdf")

# Admin routes
@admin_bp.route('/dashboard')
@login_required
def dashboard():
    if not current_user.is_admin():
        abort(403)
    
    orders = Order.query.order_by(Order.created_at.desc()).all()
    total_orders = len(orders)
    pending_orders = len([o for o in orders if o.status == 'pending'])
    completed_orders = len([o for o in orders if o.status == 'completed'])
    
    return render_template('dashboard/admin.html', 
                         orders=orders, 
                         total_orders=total_orders,
                         pending_orders=pending_orders,
                         completed_orders=completed_orders)

@admin_bp.route('/order/<int:order_id>')
@login_required
def view_order(order_id):
    if not current_user.is_admin():
        abort(403)
    
    order = Order.query.get_or_404(order_id)
    form = AdminOrderUpdateForm()
    return render_template('admin/order_detail.html', order=order, form=form)

@admin_bp.route('/update_order/<int:order_id>', methods=['POST'])
@login_required
def update_order(order_id):
    if not current_user.is_admin():
        abort(403)
    
    order = Order.query.get_or_404(order_id)
    form = AdminOrderUpdateForm()
    
    if form.validate_on_submit():
        order.status = form.status.data
        order.updated_at = datetime.now(timezone.utc)
        
        # Handle completed file uploads
        completed_folder = current_app.config['COMPLETED_FOLDER']
        
        if form.completed_resume.data:
            filename = secure_filename(f"completed_resume_{order.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{form.completed_resume.data.filename}")
            filepath = os.path.join(completed_folder, filename)
            form.completed_resume.data.save(filepath)
            order.completed_resume = filename
        
        if form.completed_cover_letter.data:
            filename = secure_filename(f"completed_cover_letter_{order.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{form.completed_cover_letter.data.filename}")
            filepath = os.path.join(completed_folder, filename)
            form.completed_cover_letter.data.save(filepath)
            order.completed_cover_letter = filename
        
        if form.status.data == 'completed':
            order.completed_at = datetime.now(timezone.utc)
        
        db.session.commit()
        
        # Send status update email
        send_email_notification('status_update', order.email, order.full_name, order=order)
        
        flash('Order updated successfully!', 'success')
    
    return redirect(url_for('admin.view_order', order_id=order_id))

@admin_bp.route('/download/<int:order_id>/<file_type>')
@login_required
def download_customer_file(order_id, file_type):
    if not current_user.is_admin():
        abort(403)
    
    order = Order.query.get_or_404(order_id)
    
    # Get the appropriate file
    filename = None
    folder = current_app.config['UPLOAD_FOLDER']
    
    if file_type == 'resume' and order.resume_file:
        filename = order.resume_file
    elif file_type == 'cover_letter' and order.cover_letter_file:
        filename = order.cover_letter_file
    elif file_type == 'job_description' and order.job_description_file:
        filename = order.job_description_file
    
    if not filename:
        flash('File not found.', 'danger')
        return redirect(url_for('admin.view_order', order_id=order_id))
    
    filepath = os.path.join(folder, filename)
    if not os.path.exists(filepath):
        flash('File not found on server.', 'danger')
        return redirect(url_for('admin.view_order', order_id=order_id))
    
    return send_file(filepath, as_attachment=True, download_name=f"customer_{file_type}_{order.id}.pdf")

# Referral routes
@referral_bp.route('/dashboard')
@login_required
def dashboard():
    rewards = ReferralReward.query.filter_by(referrer_id=current_user.id).all()
    return render_template('referral/dashboard.html', user=current_user, rewards=rewards)
=======
                success_url=f'{domain}/payment-success?session_id={{CHECKOUT_SESSION_ID}}',
                cancel_url=f'{domain}/payment-cancel?order_id={order.id}',
                client_reference_id=str(order.id),
                customer_email=order.email,
            )
            
            # Save session ID
            order.stripe_session_id = checkout_session.id
            db.session.commit()
            
            return redirect(checkout_session.url or url_for('order'), code=303)
            
        except Exception as e:
            current_app.logger.error(f"Stripe error: {e}")
            flash('Payment processing error. Please try again or contact support.', 'error')
            return redirect(url_for('order'))
    
    @app.route('/payment-success')
    def payment_success():
        session_id = request.args.get('session_id')
        if session_id:
            order = Order.query.filter_by(stripe_session_id=session_id).first()
            if order:
                order.payment_status = 'paid'
                order.status = 'in_progress'
                db.session.commit()
                
                # Send payment confirmation email
                try:
                    send_payment_confirmation_email(order)
                except Exception as e:
                    current_app.logger.error(f"Failed to send payment confirmation email: {e}")
                
                return render_template('success.html', order=order)
        
        return render_template('success.html')
    
    @app.route('/payment-cancel')
    def payment_cancel():
        order_id = request.args.get('order_id')
        order = None
        if order_id:
            order = Order.query.get(order_id)
        return render_template('cancel.html', order=order)
    
    @app.route('/contact', methods=['GET', 'POST'])
    def contact():
        form = ContactForm()
        if form.validate_on_submit():
            message = ContactMessage(  # type: ignore
                name=form.name.data,
                email=form.email.data,
                subject=form.subject.data,
                message=form.message.data
            )
            db.session.add(message)
            db.session.commit()
            
            # Send notification email to admin
            try:
                send_contact_notification_email(message)
            except Exception as e:
                current_app.logger.error(f"Failed to send contact notification email: {e}")
            
            flash('Thank you for your message. We will get back to you soon!', 'success')
            return redirect(url_for('contact'))
        
        return render_template('contact.html', form=form)
    
    # Admin routes
    @app.route('/admin/login', methods=['GET', 'POST'])
    def admin_login():
        if current_user.is_authenticated:
            return redirect(url_for('admin_dashboard'))
        
        form = AdminLoginForm()
        if form.validate_on_submit():
            admin = Admin.query.filter_by(username=form.username.data).first()
            if admin and admin.password_hash and check_password_hash(admin.password_hash, form.password.data or ""):
                login_user(admin)
                next_page = request.args.get('next')
                return redirect(next_page) if next_page else redirect(url_for('admin_dashboard'))
            flash('Invalid username or password.', 'error')
        
        return render_template('admin/login.html', form=form)
    
    @app.route('/admin/logout')
    @login_required
    def admin_logout():
        logout_user()
        flash('You have been logged out.', 'info')
        return redirect(url_for('index'))
    
    @app.route('/admin')
    @login_required
    def admin_dashboard():
        page = request.args.get('page', 1, type=int)
        status_filter = request.args.get('status', 'all')
        
        query = Order.query
        if status_filter != 'all':
            query = query.filter_by(status=status_filter)
        
        orders = query.order_by(Order.created_at.desc()).paginate(
            page=page, per_page=20, error_out=False
        )
        
        # Statistics
        total_orders = Order.query.count()
        pending_orders = Order.query.filter_by(status='pending').count()
        in_progress_orders = Order.query.filter_by(status='in_progress').count()
        completed_orders = Order.query.filter_by(status='completed').count()
        total_revenue = db.session.query(db.func.sum(Order.total_amount)).filter_by(payment_status='paid').scalar() or 0
        
        stats = {
            'total_orders': total_orders,
            'pending_orders': pending_orders,
            'in_progress_orders': in_progress_orders,
            'completed_orders': completed_orders,
            'total_revenue': total_revenue
        }
        
        return render_template('admin/dashboard.html', orders=orders, stats=stats, status_filter=status_filter)
    
    @app.route('/admin/order/<int:order_id>')
    @login_required
    def admin_order_detail(order_id):
        order = Order.query.get_or_404(order_id)
        form = OrderStatusForm(obj=order)
        return render_template('admin/order_detail.html', order=order, form=form)
    
    @app.route('/admin/order/<int:order_id>/update', methods=['POST'])
    @login_required
    def admin_update_order(order_id):
        order = Order.query.get_or_404(order_id)
        form = OrderStatusForm()
        
        if form.validate_on_submit():
            old_status = order.status
            order.status = form.status.data
            order.admin_notes = form.admin_notes.data
            order.updated_at = datetime.utcnow()
            
            if form.status.data == 'completed' and old_status != 'completed':
                order.completed_at = datetime.utcnow()
            
            db.session.commit()
            flash('Order updated successfully.', 'success')
            
            # Send status update email
            try:
                send_status_update_email(order, old_status)
            except Exception as e:
                current_app.logger.error(f"Failed to send status update email: {e}")
        
        return redirect(url_for('admin_order_detail', order_id=order_id))
    
    @app.route('/admin/download/<int:order_id>/<file_type>')
    @login_required
    def admin_download_file(order_id, file_type):
        order = Order.query.get_or_404(order_id)
        
        file_mapping = {
            'resume': order.uploaded_resume_path,
            'cover_letter': order.uploaded_cover_letter_path,
            'job_description': order.uploaded_job_description_path
        }
        
        filename = file_mapping.get(file_type)
        if not filename:
            flash('File not found.', 'error')
            return redirect(url_for('admin_order_detail', order_id=order_id))
        
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        if not os.path.exists(file_path):
            flash('File not found on server.', 'error')
            return redirect(url_for('admin_order_detail', order_id=order_id))
        
        return send_file(file_path, as_attachment=True)
    
    # API endpoint for service pricing
    @app.route('/api/service-pricing/<int:service_id>')
    def api_service_pricing(service_id):
        service = Service.query.get_or_404(service_id)
        return jsonify({
            'basic': service.price_basic,
            'standard': service.price_standard,
            'premium': service.price_premium
        })

def send_order_confirmation_email(order):
    """Send order confirmation email to customer"""
    if not mail:
        return
    
    msg = Message(
        subject=f'Order Confirmation #{order.id} - {order.service.name}',
        recipients=[order.email]
    )
    
    msg.body = f"""
Dear {order.full_name},

Thank you for your order! We have received your request for {order.service.name} ({order.service_tier.title()} package).

Order Details:
- Order ID: #{order.id}
- Service: {order.service.name} - {order.service_tier.title()}
- Total Amount: ${order.total_amount:.2f}
- Target Position: {order.target_position}

Your order is currently pending payment. Once payment is completed, our professional writers will begin working on your resume.

We will keep you updated on the progress of your order.

Best regards,
The CreateProResume Team
"""
    
    mail.send(msg)

def send_payment_confirmation_email(order):
    """Send payment confirmation email to customer"""
    if not mail:
        return
    
    msg = Message(
        subject=f'Payment Confirmed - Order #{order.id}',
        recipients=[order.email]
    )
    
    msg.body = f"""
Dear {order.full_name},

Your payment has been successfully processed! Our professional writing team will now begin working on your {order.service.name}.

Order Details:
- Order ID: #{order.id}
- Service: {order.service.name} - {order.service_tier.title()}
- Amount Paid: ${order.total_amount:.2f}
- Status: In Progress

Expected Delivery: 3-5 business days

You will receive email updates as your order progresses. If you have any questions, please don't hesitate to contact us.

Best regards,
The CreateProResume Team
"""
    
    mail.send(msg)

def send_status_update_email(order, old_status):
    """Send status update email to customer"""
    if not mail or old_status == order.status:
        return
    
    msg = Message(
        subject=f'Order Update - #{order.id} Status Changed',
        recipients=[order.email]
    )
    
    status_messages = {
        'in_progress': 'Our team has started working on your order.',
        'completed': 'Your order has been completed! Please check your email for the final documents.',
        'cancelled': 'Your order has been cancelled. If you have any questions, please contact us.'
    }
    
    msg.body = f"""
Dear {order.full_name},

Your order status has been updated.

Order Details:
- Order ID: #{order.id}
- Service: {order.service.name} - {order.service_tier.title()}
- New Status: {order.status.replace('_', ' ').title()}

{status_messages.get(order.status, 'Your order status has been updated.')}

Best regards,
The CreateProResume Team
"""
    
    mail.send(msg)

def send_contact_notification_email(contact_message):
    """Send notification email to admin when contact form is submitted"""
    if not mail:
        return
    
    admin_email = current_app.config.get('ADMIN_EMAIL', 'msheharyar2020@gmail.com')
    
    msg = Message(
        subject=f'New Contact Form Submission: {contact_message.subject or "General Inquiry"}',
        recipients=[admin_email]
    )
    
    msg.body = f"""
New contact form submission received:

Name: {contact_message.name}
Email: {contact_message.email}
Subject: {contact_message.subject or "General Inquiry"}

Message:
{contact_message.message}

Submitted on: {contact_message.created_at.strftime('%Y-%m-%d %H:%M:%S')}

Please respond to this inquiry promptly.

---
CreateProResume Contact Form System
"""
    
    # Also send auto-reply to customer
    reply_msg = Message(
        subject='Thank you for contacting CreateProResume',
        recipients=[contact_message.email]
    )
    
    reply_msg.body = f"""
Dear {contact_message.name},

Thank you for reaching out to CreateProResume! We have received your message and will get back to you within 24 hours.

Your inquiry details:
Subject: {contact_message.subject or "General Inquiry"}
Message: {contact_message.message[:200]}{"..." if len(contact_message.message) > 200 else ""}

If you have any urgent questions, please call us at (555) 123-4567.

Best regards,
The CreateProResume Team
"""
    
    mail.send(msg)
    mail.send(reply_msg)

# New Enhanced Email Functions
def send_referral_emails(referral):
    """Send referral emails to both referrer and referred person"""
    if not mail:
        return
    
    # Email to referred person
    referred_msg = Message(
        subject=f'{referral.referrer_name} referred you to CreateProResume - Get $25 Off!',
        recipients=[referral.referred_email]
    )
    
    referred_msg.body = f"""
Hi {referral.referred_name or 'there'}!

Great news! {referral.referrer_name} has referred you to CreateProResume and you'll receive $25 off your first order!

Use referral code: {referral.referral_code}

CreateProResume offers professional resume writing services that help you land your dream job. Our expert writers create ATS-optimized resumes that get noticed by employers.

Ready to get started? Visit: {url_for('order', ref=referral.referral_code, _external=True)}

This offer is valid for 30 days from today.

Best regards,
The CreateProResume Team
"""
    
    # Email to referrer
    referrer_msg = Message(
        subject='Thank you for referring a friend to CreateProResume!',
        recipients=[referral.referrer_email]
    )
    
    referrer_msg.body = f"""
Hi {referral.referrer_name}!

Thank you for referring {referral.referred_name} to CreateProResume! 

We've sent them a special offer for $25 off their first order. When they complete their order using referral code {referral.referral_code}, you'll receive a $25 credit that can be used towards your next order.

Keep spreading the word - there's no limit to how many friends you can refer!

Best regards,
The CreateProResume Team
"""
    
    mail.send(referred_msg)
    mail.send(referrer_msg)

def send_newsletter_welcome_email(subscriber):
    """Send welcome email to newsletter subscriber"""
    if not mail:
        return
    
    msg = Message(
        subject='Welcome to CreateProResume Newsletter!',
        recipients=[subscriber.email]
    )
    
    msg.body = f"""
Hi {subscriber.name or 'there'}!

Welcome to the CreateProResume newsletter! You'll now receive:

• Career tips and job search strategies
• Resume writing best practices  
• Industry insights and trends
• Exclusive offers and discounts
• Success stories from our clients

As a welcome gift, here's a 10% discount code for your first order: WELCOME10

Ready to transform your career? Visit: {url_for('index', _external=True)}

Best regards,
The CreateProResume Team

P.S. You can unsubscribe at any time by clicking the link in our emails.
"""
    
    mail.send(msg)
>>>>>>> ded7f2e4447248a018f7dd7d09de9c43eb09fa0d
