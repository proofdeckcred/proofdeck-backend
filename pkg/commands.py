import click
from flask.cli import with_appcontext
from .extensions import db
from .models import User
from bcrypt import hashpw, gensalt
import sys

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

def register_commands(app):
    """Registers all custom command groups with the Flask app."""
    app.cli.add_command(admin_cli)