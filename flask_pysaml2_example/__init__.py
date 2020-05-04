import logging

from pathlib import Path

from flask import Flask, render_template
from flask_login import LoginManager, login_required
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
login_manager = LoginManager()


def create_app(test_config=None):
    logging.basicConfig(level=logging.INFO)

    # create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY='dev',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_DATABASE_URI=f'sqlite:///{Path(app.instance_path) / "flask_pysaml2_example.sql"}',
        SAML_IDP_SETTINGS={
            # Add the settings for each IDP you want to use. Each entry in the
            # dictionary requires to keys:
            #
            # entityid: An identifier for the SP. Usually this is the same as the Single Sign On URL.
            #           It will default to the SSO URL if left empty or undefined.
            # metadata_url: This is the metadata URL for the IDP.
            #
            # 'example-oktadev': {
            #    'entityid': 'http://<replace-me>.ngrok.io/auth/saml/sso/flask-pysaml2-example',
            #    'metadata_url': 'http://idp.oktadev.com/metadata'
            # },
            # 'example-okta': {
            #    'entityid': 'http://53d17b6f.ngrok.io/auth/saml/sso/example-okta',
            #    'metadata_url': 'https://dev-123456.okta.com/app/9yebOuL2hbQFhl3iZcCw/sso/saml/metadata'
            # },
        }
    )

    if test_config is None:
        # load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # load the test config if passed in
        app.config.from_mapping(test_config)

    # ensure the instance folder exists
    Path(app.instance_path).mkdir(exist_ok=True)

    db.init_app(app)

    @app.before_first_request
    def setup_db():
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

    return app
