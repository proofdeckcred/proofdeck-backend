import click
from flask.cli import with_appcontext
from .extensions import db
from .models import User, Template
from bcrypt import hashpw, gensalt
import sys
import secrets

# Create a new Click group for admin commands
admin_cli = click.Group('admin', help='Admin commands for ProofDeck.')

@admin_cli.command('create')
@click.option('--name', prompt=True, help='The name of the admin user.')
@click.option('--email', prompt=True, help='The email of the admin user.')
@click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True, help='The password for the admin user.')
@with_appcontext
def create_admin(name, email, password):
    """Creates a new admin user."""
    if User.query.filter_by(email=email).first():
        click.echo(click.style(f"Error: User with email {email} already exists.", fg='red'))
        sys.exit(1)

    hashed_password = hashpw(password.encode('utf-8'), gensalt())
    
    # Create the admin user
    admin_user = User(
        name=name,
        email=email,
        password_hash=hashed_password.decode('utf-8'),
        role='admin',  # Set the role to 'admin'
        cert_quota=999999  # Give admins a very large quota
    )
    
    db.session.add(admin_user)
    db.session.commit()
    
    click.echo(click.style(f"Admin user '{name}' with email '{email}' created successfully!", fg='green'))

# Create a new Click group for pilot commands
pilot_cli = click.Group('pilot', help='Pilot integration commands.')

@pilot_cli.command('create')
@with_appcontext
def create_pilot():
    """Creates the standard pilot user for HannaCode."""
    email = "hannacode_pilot@proofdeck.io"
    name = "HannaCode Pilot"
    
    # Check if user already exists
    user = User.query.filter_by(email=email).first()
    
    if not user:
        password = secrets.token_urlsafe(16)
        api_key = secrets.token_hex(32)
        
        user = User(
            name=name,
            email=email,
            password_hash=hashpw(password.encode('utf-8'), gensalt()).decode('utf-8'),
            role='pro',
            cert_quota=100, 
            api_key=api_key,
            is_verified=True
        )
        db.session.add(user)
        db.session.commit()
        click.echo(click.style(f"Pilot User created!", fg='green'))
    else:
        click.echo("User already exists. Ensuring API key...")
        if not user.api_key:
            user.api_key = secrets.token_hex(32)
            db.session.commit()
    
    # Ensure they have a template
    template = Template.query.filter_by(user_id=user.id).first()
    if not template:
        new_template = Template(
            user_id=user.id,
            title="Dart Course Completion",
            layout_style="modern",
            custom_text={
                "title": "Certificate of Completion",
                "body": "has successfully completed the Dart Course"
            }
        )
        db.session.add(new_template)
        db.session.commit()
        template = new_template

    click.echo(click.style(f"\n--- CREDENTIALS FOR HANNACODE ---", fg='cyan'))
    click.echo(f"API Key: {user.api_key}")
    click.echo(f"Template ID: {template.id}")
    click.echo(f"User ID: {user.id}")


def register_commands(app):
    """Registers all custom command groups with the Flask app."""
    app.cli.add_command(admin_cli)
    app.cli.add_command(pilot_cli)