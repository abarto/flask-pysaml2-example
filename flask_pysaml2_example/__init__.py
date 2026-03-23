import logging
import json
import os

from pathlib import Path

from flask import Flask, render_template
from flask_caching import Cache
from flask_login import LoginManager, login_required
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
login_manager = LoginManager()
cache = Cache()


def create_app(test_config=None):
    logging.basicConfig(level=logging.INFO)

    # create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_DATABASE_URI=f'sqlite:///{Path(app.instance_path) / "flask_pysaml2_example.sql"}',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true',
        CACHE_TYPE='SimpleCache',
        ALLOWED_REDIRECT_HOSTS=(),
        SAML_METADATA_CACHE_TTL_SECONDS=3600,
        SAML_METADATA_TIMEOUT_SECONDS=5,
        SAML_ATTRIBUTE_MAPPING={
            'first_name': ('FirstName', 'first_name', 'givenName'),
            'last_name': ('LastName', 'last_name', 'surname', 'sn'),
        },
        SAML_IDP_SETTINGS={
            # Add the settings for each IDP you want to use. Each entry in the
            # dictionary requires two keys:
            #
            # entityid: An identifier for the SP. Usually this is the same as the Single Sign On URL.
            #           It will default to the SSO URL if left empty or undefined.
            # metadata_url: This is the metadata URL for the IDP.
            #
            # 'example-oktadev': {
            #    'entityid': 'http://flask-pysaml2-example',
            #    'metadata_url': 'https://<dev-account>.okta.com/app/<app-id>/sso/saml/metadata'
            # },
        }
    )

    if test_config is None:
        # load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)

        # Optional JSON override for container/cloud deployments where mounting
        # instance/config.py is inconvenient.
        saml_idp_settings = os.environ.get('SAML_IDP_SETTINGS_JSON')
        if saml_idp_settings:
            try:
                parsed_settings = json.loads(saml_idp_settings)
            except json.JSONDecodeError as exc:
                raise RuntimeError('SAML_IDP_SETTINGS_JSON must contain valid JSON.') from exc

            if not isinstance(parsed_settings, dict):
                raise RuntimeError('SAML_IDP_SETTINGS_JSON must decode to a dictionary/object.')

            app.config['SAML_IDP_SETTINGS'] = parsed_settings
    else:
        # load the test config if passed in
        app.config.from_mapping(test_config)

    # ensure the instance folder exists
    Path(app.instance_path).mkdir(exist_ok=True)

    db.init_app(app)
    cache.init_app(app)

    with app.app_context():
        from .orm import User
        db.create_all()

    login_manager.init_app(app)

    from .auth import auth_blueprint, load_user
    
    login_manager.user_loader(load_user)

    app.register_blueprint(auth_blueprint, url_prefix='/auth')

    @app.route("/")
    def index():
        return render_template(
            'index.html',
            idp_names=[idp_name for idp_name in app.config['SAML_IDP_SETTINGS'].keys()]
        )

    @app.route("/user")
    @login_required
    def user():
        return render_template('user.html')

    @app.errorhandler(401)
    def error_unauthorized(error):
        return render_template('unauthorized.html'), 401

    @app.route('/health')
    def health():
        return {'status': 'ok'}

    return app
